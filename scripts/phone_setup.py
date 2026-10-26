"""Windows-only authority and one-use DPAPI consumer. Does not start listeners or ngrok."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import hashlib
import json
import re
import hmac
import sys
import time
from collections.abc import Iterator
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec,rsa,padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app import phone_crypto as crypto
from scripts import threads_setup as setup


def authority(vault: dict) -> ec.EllipticCurvePrivateKey:
    state=vault.setdefault('phone_setup',{'operations':{}})
    if 'authority_key' not in state:
        key=ec.generate_private_key(ec.SECP256R1())
        state['authority_key']=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        setup.save(vault)
    result=serialization.load_pem_private_key(state['authority_key'].encode(),password=None)
    if not isinstance(result,ec.EllipticCurvePrivateKey):raise setup.SetupError('INVALID_AUTHORITY')
    return result


def previous_configuration(vault: dict) -> str:
    return hashlib.sha256(crypto.canonical({'app_id':vault.get('app_id',''),'app_secret':vault.get('app_secret','')})).hexdigest()


def prepare(vault: dict,device: dict,app_id: str) -> dict:
    try:
        if not hmac.compare_digest(crypto.device_receipt(device,vault['admin']),device.get('enrollment_receipt','')):
            raise ValueError()
    except (ValueError,KeyError,TypeError):raise setup.SetupError('AUTHENTICATED_DEVICE_RECEIPT_REQUIRED') from None
    for existing in vault.get('phone_setup',{}).get('operations',{}).values():
        if existing['status'] in {'CLAIMING','APPLYING','RECONCILIATION_REQUIRED'}:raise setup.SetupError('RECONCILIATION_REQUIRED')
        if existing['status']=='ISSUED' and datetime.fromisoformat(existing['manifest']['expires_at'])>datetime.now(timezone.utc):
            raise setup.SetupError('AUTHORIZATION_ALREADY_ACTIVE')
    key=authority(vault)
    if (device.get('authority')!=crypto.public(key) or device.get('status')!='ACTIVE' or not re.fullmatch(r'[0-9]{3,40}',app_id)
            or device.get('origin')!=vault.get('public_url') or device.get('tenant_id')!=vault.get('tenant_id')):raise setup.SetupError('TRUSTED_DEVICE_REQUIRED')
    expiry=datetime.now(timezone.utc)+timedelta(minutes=5)
    if datetime.fromisoformat(device['expires_at'])<expiry:raise setup.SetupError('DEVICE_EXPIRES_TOO_SOON')
    encryption=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    import uuid
    gid=str(uuid.uuid4())
    manifest={'action':'THREADS_APP_CREDENTIALS_ONLY','grant_id':gid,'tenant_id':device['tenant_id'],'device_id':device['device_id'],
        'app_id':app_id,'origin':device['origin'],'expires_at':expiry.isoformat(),'encryption_key':crypto.public(encryption),
        'authorized_by':'dpapi-authority:'+hashlib.sha256(crypto.public(key).encode()).hexdigest()}
    signature=crypto.sign(key,manifest)
    state=vault['phone_setup']['operations']
    state[gid]={'manifest':manifest,'signature':signature,'device':device,'previous_configuration':previous_configuration(vault),'status':'ISSUED',
        'key':encryption.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()}
    setup.save(vault)
    return {'tenant_id':device['tenant_id'],'manifest':manifest,'signature':signature}


@contextmanager
def locked() -> Iterator[None]:
    if sys.platform!='win32':raise setup.SetupError('WINDOWS_DPAPI_REQUIRED')
    import msvcrt
    with (setup.PRIVATE/'setup.lock').open('a+b') as stream:
        stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
        try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise setup.SetupError('SETUP_ALREADY_RUNNING') from None
        try:yield
        finally:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)


def apply_delivery(delivery: dict) -> dict:
    """No network/deployment here: persist exact credentials, leave Docker restart to trusted operator."""
    with locked():
        vault=setup.load();gid=delivery.get('manifest',{}).get('grant_id','')
        op=vault.get('phone_setup',{}).get('operations',{}).get(gid)
        if not op:raise setup.SetupError('UNKNOWN_AUTHORIZATION')
        if delivery.get('manifest')!=op['manifest'] or delivery.get('signature')!=op['signature']:raise setup.SetupError('DELIVERY_MISMATCH')
        if op['status']=='APPLIED':
            if op.get('envelope_hash')!=delivery.get('envelope_hash'):raise setup.SetupError('DELIVERY_MISMATCH')
            return applied_receipt(vault,gid,op,True)
        if op['status'] not in {'ISSUED','CLAIMING'}:raise setup.SetupError('RECONCILIATION_REQUIRED')
        try:
            m=op['manifest'];root=serialization.load_pem_private_key(vault['phone_setup']['authority_key'].encode(),password=None)
            if not isinstance(root,ec.EllipticCurvePrivateKey):raise ValueError()
            if delivery['manifest']!=m or delivery['signature']!=op['signature']:raise ValueError()
            crypto.verify(crypto.public(root),m,delivery['signature'])
            if datetime.fromisoformat(m['expires_at'])<=datetime.now(timezone.utc) or m['origin']!=vault.get('public_url'):raise ValueError()
            if previous_configuration(vault)!=op['previous_configuration']:raise ValueError()
            envelope=delivery['envelope']
            if crypto.digest(envelope)!=delivery['envelope_hash'] or set(envelope)!={'wrapped_key','nonce','ciphertext'}:raise ValueError()
            proof=delivery['device_proof'];device=op['device']
            if crypto.device_receipt(device,vault['admin'])!=device['enrollment_receipt']:raise ValueError()
            crypto.verify(device['public_key'],crypto.proof_message(gid,m['device_id'],crypto.digest(m),proof['nonce'],delivery['envelope_hash']),proof['signature'])
            op['status']='APPLYING';setup.save(vault)
            key=serialization.load_pem_private_key(op['key'].encode(),password=None)
            if not isinstance(key,rsa.RSAPrivateKey):raise ValueError()
            symmetric=key.decrypt(crypto.decode(envelope['wrapped_key'],600),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
            data=AESGCM(symmetric).decrypt(crypto.decode(envelope['nonce'],32),crypto.decode(envelope['ciphertext'],2048),crypto.canonical(m))
            body=json.loads(data)
            if set(body)!={'app_id','app_secret'} or body['app_id']!=m['app_id'] or not isinstance(body['app_secret'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,256}',body['app_secret']):raise ValueError()
            if datetime.fromisoformat(m['expires_at'])<=datetime.now(timezone.utc):raise ValueError()
            vault['app_id']=body['app_id'];vault['app_secret']=body['app_secret'];vault.pop('meta_redirect_confirmed_for',None)
            vault['phone_setup']['release_approved']=False
            op['status']='APPLIED';op['envelope_hash']=delivery['envelope_hash'];op.pop('key',None);setup.save(vault)
            return applied_receipt(vault,gid,op,False)
        except Exception:
            # Reload on error: a failed write must not accidentally persist staged plaintext credentials.
            current=setup.load();record=current.get('phone_setup',{}).get('operations',{}).get(gid)
            if record and record.get('status')=='APPLIED':return applied_receipt(current,gid,record,True)
            if record:
                record['status']='RECONCILIATION_REQUIRED';setup.save(current)
            raise setup.SetupError('RECONCILIATION_REQUIRED') from None


def applied_receipt(vault: dict,gid: str,op: dict,already: bool) -> dict:
    root=serialization.load_pem_private_key(vault['phone_setup']['authority_key'].encode(),password=None)
    if not isinstance(root,ec.EllipticCurvePrivateKey):raise setup.SetupError('INVALID_AUTHORITY')
    return {'status':'APPLIED','already_applied':already,'receipt':crypto.sign(root,crypto.commit_message(gid,op['envelope_hash']))}


def issue_authorization(device_id: str,app_id: str) -> dict:
    """Future operator command: requires a separately released, authenticated backend."""
    with locked():
        vault=setup.load()
        if vault.get('phone_setup',{}).get('release_approved') is not True:raise setup.SetupError('PUBLIC_ACTIVATION_NOT_AUTHORIZED')
        device=setup.request(setup.LOCAL,vault=vault,path='/ui/admin/phone-setup/devices/'+vault['tenant_id']+'/'+device_id,admin=True)
        body=prepare(vault,device,app_id)
        result: dict=setup.request(setup.LOCAL,vault=vault,path='/ui/admin/phone-setup/grants',payload=body,admin=True)
        return result


def consume(gid: str) -> dict:
    with locked():
        vault=setup.load()
        if vault.get('phone_setup',{}).get('release_approved') is not True:raise setup.SetupError('PUBLIC_ACTIVATION_NOT_AUTHORIZED')
        op=vault['phone_setup']['operations'][gid]
        if op['status']!='ISSUED':raise setup.SetupError('RECONCILIATION_REQUIRED')
        op['status']='CLAIMING';setup.save(vault)
    try:delivery=setup.request(setup.LOCAL,vault=vault,path='/ui/admin/phone-setup/grants/'+gid+'/claim',payload={},admin=True)
    except Exception:
        with locked():
            current=setup.load();current['phone_setup']['operations'][gid]['status']='RECONCILIATION_REQUIRED';setup.save(current)
        raise setup.SetupError('CLAIM_RESULT_UNKNOWN') from None
    try:result=apply_delivery(delivery)
    except setup.SetupError:
        setup.request(setup.LOCAL,vault=vault,path='/ui/admin/phone-setup/grants/'+gid+'/finish',payload={'status':'RECONCILIATION_REQUIRED'},admin=True)
        raise
    setup.request(setup.LOCAL,vault=vault,path='/ui/admin/phone-setup/grants/'+gid+'/finish',payload={'status':'APPLIED','receipt':result['receipt']},admin=True)
    current=setup.load();setup.compose(current,'up','-d','api');setup.wait_ready(current)
    return result


def wait_and_consume(gid: str) -> dict:
    vault=setup.load()
    if vault.get('phone_setup',{}).get('release_approved') is not True:raise setup.SetupError('PUBLIC_ACTIVATION_NOT_AUTHORIZED')
    op=vault['phone_setup']['operations'][gid]
    while datetime.fromisoformat(op['manifest']['expires_at'])>datetime.now(timezone.utc):
        result=setup.request(setup.LOCAL,vault=vault,path='/ui/admin/phone-setup/grants/'+gid+'/status',admin=True)
        if result['status']=='SEALED':return consume(gid)
        if result['status'] not in {'OPEN','AUTHENTICATED'}:raise setup.SetupError('CHANNEL_CLOSED')
        time.sleep(2)
    close_expired();raise setup.SetupError('AUTHORIZATION_EXPIRED')


def close_expired() -> dict:
    with locked():
        vault=setup.load();closed=0
        for operation in vault.get('phone_setup',{}).get('operations',{}).values():
            if operation['status']=='ISSUED' and datetime.fromisoformat(operation['manifest']['expires_at'])<=datetime.now(timezone.utc):
                operation['status']='EXPIRED';operation.pop('key',None);closed+=1
        if closed:setup.save(vault)
        return {'closed':closed}
