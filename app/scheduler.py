"""One tenant-bound worker per scheduler; external service restarts this process."""
import os
import signal
import threading
import httpx
from .operations import emit


def run_once(client: httpx.Client) -> dict:
    response = client.post('/maintenance/recover')
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError('Invalid recovery response')
    emit('scheduler.completed', count=data['released'] + data['held_for_reconciliation'])
    if os.getenv('MOS_THREADS_MAINTENANCE_ENABLED','false')=='true':
        maintenance=client.post('/maintenance/threads')
        maintenance.raise_for_status()
    return data


def main() -> None:
    interval = int(os.getenv('MOS_RECOVERY_SECONDS', '60'))
    if not 10 <= interval <= 3600:
        raise ValueError('Recovery interval must be 10..3600 seconds')
    if len(os.environ.get('MOS_WORKER_TOKEN', '')) < 30:
        raise ValueError('Dedicated worker token required')
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    with httpx.Client(base_url=os.getenv('MOS_API_URL', 'http://api:8000'),
                      headers={'Authorization': 'Bearer ' + os.environ['MOS_WORKER_TOKEN']},
                      timeout=15, follow_redirects=False, trust_env=False) as client:
        while not stop.is_set():
            try:
                run_once(client)
            except (httpx.HTTPError, ValueError, KeyError):
                emit('scheduler.failed')
            stop.wait(interval)


if __name__ == '__main__':
    main()
