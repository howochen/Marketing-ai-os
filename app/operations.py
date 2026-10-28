"""Small deployment boundary and deliberately allowlisted operational events."""
import ipaddress
import asyncio
import json
import logging
import os
import re
from urllib.parse import urlsplit
from starlette.types import ASGIApp, Scope, Receive, Send, Message
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger('mos.events')


def redact(message: str) -> str:
    for key in ('MOS_THREADS_TOKEN_KEY', 'MOS_THREADS_APP_SECRET', 'MOS_ADMIN_KEY', 'ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY', 'MOS_GOOGLE_READONLY_ACCESS_TOKEN', 'MOS_WORKER_TOKEN', 'POSTGRES_PASSWORD', 'MOS_APP_PASSWORD', 'MOS_MIGRATION_PASSWORD'):
        value = os.getenv(key, '')
        if len(value) >= 8:
            message = message.replace(value, '[REDACTED]')
    message = re.sub(r'(?i)Bearer\s+[^\s"\',}]+', 'Bearer [REDACTED]', message)
    message = re.sub(r'\b(?:mos_|sk-)[A-Za-z0-9_-]{20,}', '[REDACTED]', message)
    message = re.sub(r'\b(?:AIza[A-Za-z0-9_-]{20,}|ya29\.[A-Za-z0-9._-]+)', '[REDACTED]', message)
    message = re.sub(r'''(?i)((?:x-goog-api-key|api_key|verification_access_token)["']?\s*[:=]\s*["']?)[^"',\s}]+''', r'\1[REDACTED]', message)
    message = re.sub(r'(?i)([?&](?:code|state|access_token|input_token|client_secret)=)[^&\s\"\']+', r'\1[REDACTED]', message)
    return re.sub(r'(://[^\s/:]+:)[^@\s]+@', r'\1[REDACTED]@', message)


class SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


def install_log_filter() -> None:
    loggers = [logging.getLogger(), *logging.Logger.manager.loggerDict.values()]
    for item in loggers:
        if isinstance(item, logging.Logger):
            for handler in item.handlers:
                if not any(isinstance(f, SecretFilter) for f in handler.filters):
                    handler.addFilter(SecretFilter())


def emit(event: str, *, status: int = 0, count: int = 0) -> None:
    # No arbitrary text, headers, paths, payloads or exception messages enter this logger.
    allowed = {'security.denied', 'security.throttled', 'cost.overrun', 'task.failed', 'scheduler.completed', 'scheduler.failed'}
    if event not in allowed:
        raise ValueError('Unknown operational event')
    logger.warning(json.dumps({'event': event, 'status': int(status), 'count': int(count)}))


def validate_deployment() -> None:
    mode = os.getenv('MOS_ENV', 'development')
    if mode not in {'development', 'test', 'production'}:
        raise RuntimeError('Invalid deployment mode')
    if mode != 'production':
        return
    secret = os.getenv('MOS_ADMIN_KEY', '')
    if len(secret) < 40 or len(set(secret)) < 10 or any(word in secret.lower() for word in ('test', 'replace', 'example', 'ci-only')):
        raise RuntimeError('Production requires a dedicated admin secret')
    if not os.getenv('DATABASE_URL', '').startswith('postgresql'):
        raise RuntimeError('Production requires PostgreSQL')
    url = urlsplit(os.getenv('MOS_PUBLIC_URL', ''))
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        raise RuntimeError('Production requires a public HTTPS URL')
    proxies = os.getenv('MOS_TRUSTED_PROXIES', '').split(',')
    try:
        for proxy in proxies:
            if ipaddress.ip_network(proxy.strip(), strict=False).prefixlen == 0:
                raise ValueError('Wildcard proxy network')
    except ValueError:
        raise RuntimeError('Production requires explicit proxy networks') from None
    if os.getenv('MOS_MODEL_CALLS_ENABLED', 'false').lower() != 'false' or os.getenv('MOS_LIVE_TESTS', 'false').lower() != 'false':
        raise RuntimeError('P0.5 production model calls must remain disabled')


def trusted_proxy(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
        return any(address in ipaddress.ip_network(net.strip(), strict=False)
                   for net in os.getenv('MOS_TRUSTED_PROXIES', '').split(',') if net.strip())
    except ValueError:
        return False


class Boundary:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        from starlette.responses import JSONResponse
        from starlette.concurrency import run_in_threadpool
        from .database import SessionLocal
        from .limits import consume
        headers = dict(scope['headers'])
        host = scope.get('client', ('unknown', 0))[0]
        if os.getenv('MOS_ENV') == 'production' and scope.get('scheme') != 'https':
            if not trusted_proxy(host) or headers.get(b'x-forwarded-proto') != b'https':
                return await JSONResponse({'detail': 'HTTPS required'}, 403)(scope, receive, send)
        if scope['method'] in {'POST', 'PUT', 'DELETE', 'PATCH'}:
            login = scope['path'] in {'/auth/login','/ui/session','/ui/admin/login'} or scope['path'].startswith('/admin/')
            def limited() -> bool:
                with SessionLocal() as session:
                    return consume(session, f'{host}:{"login" if login else "write"}', 10 if login else 120)
            try:
                accepted = await run_in_threadpool(limited)
            except SQLAlchemyError:
                emit('security.denied', status=503)
                return await JSONResponse({'detail': 'Rate limit storage unavailable'}, 503)(scope, receive, send)
            if not accepted:
                emit('security.throttled', status=429)
                return await JSONResponse({'detail': 'Rate limit exceeded'}, 429,
                                          headers={'Retry-After': '60'})(scope, receive, send)
        body = bytearray()
        deadline = asyncio.get_running_loop().time() + 15
        while True:
            try:
                message = await asyncio.wait_for(receive(), timeout=max(0, deadline - asyncio.get_running_loop().time()))
            except TimeoutError:
                return await JSONResponse({'detail': 'Request body timeout'}, 408)(scope, receive, send)
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > 65536:
                return await JSONResponse({'detail': 'Request too large'}, 413)(scope, receive, send)
            if not message.get('more_body', False):
                break
        delivered = False
        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        async def safe_send(message: Message) -> None:
            if message['type'] == 'http.response.start' and (message['status'] in (401,403) or (scope['path'].startswith(('/phone-setup/','/ui/admin/phone-setup/')) and message['status']>=400)):
                emit('security.denied', status=message['status'])
            if message['type']=='http.response.start' and (scope['path'].startswith(('/ui/','/threads/oauth/','/phone-setup/','/threads/privacy/'))):
                message['headers']=[(k,v) for k,v in message.get('headers',[]) if k.lower() not in {b'cache-control',b'referrer-policy'}]
                message['headers'] += [(b'cache-control',b'no-store'),(b'referrer-policy',b'no-referrer')]
            await send(message)
        # Application execution is bounded by DB/provider deadlines; no cancellation-based retry.
        await self.app(scope, replay, safe_send)
