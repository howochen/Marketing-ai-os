"""Small, fixed-format signed messages; no private device key reaches this module."""
import base64
import hashlib
import json
import hmac
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec,utils,rsa


def canonical(value: dict) -> bytes:
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()


def digest(value: dict) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def decode(value: str,limit: int=8192) -> bytes:
    if not isinstance(value,str) or not 1<=len(value)<=limit:raise ValueError('INVALID_ENCODING')
    return base64.b64decode(value+'='*(-len(value)%4),altchars=b'-_',validate=True)


def public(key: ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey) -> str:
    return encode(key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo))


def signing_key(value: str) -> ec.EllipticCurvePublicKey:
    key=serialization.load_der_public_key(decode(value,512))
    if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256R1):raise ValueError('P256_REQUIRED')
    return key


def encryption_key(value: str) -> rsa.RSAPublicKey:
    key=serialization.load_der_public_key(decode(value,2048))
    if not isinstance(key,rsa.RSAPublicKey) or key.key_size!=3072:raise ValueError('RSA3072_REQUIRED')
    return key


def sign(key: ec.EllipticCurvePrivateKey,value: dict) -> str:
    r,s=utils.decode_dss_signature(key.sign(canonical(value),ec.ECDSA(hashes.SHA256())))
    return encode(r.to_bytes(32,'big')+s.to_bytes(32,'big'))


def verify(public_key: str,value: dict,signature: str) -> None:
    raw=decode(signature,128)
    if len(raw)!=64:raise ValueError('INVALID_SIGNATURE')
    signing_key(public_key).verify(utils.encode_dss_signature(int.from_bytes(raw[:32],'big'),int.from_bytes(raw[32:],'big')),
                                   canonical(value),ec.ECDSA(hashes.SHA256()))


def enrollment_message(device_id: str,nonce: str,origin: str,key: str,authority: str) -> dict:
    return {'action':'ENROLL_DEVICE','device_id':device_id,'nonce':nonce,'origin':origin,'public_key':key,'authority':authority}


def proof_message(grant_id: str,device_id: str,manifest_hash: str,nonce: str,envelope_hash: str='') -> dict:
    return {'action':'SUBMIT' if envelope_hash else 'AUTHENTICATE','grant_id':grant_id,'device_id':device_id,
            'manifest_hash':manifest_hash,'nonce':nonce,'envelope_hash':envelope_hash}


def device_receipt(identity: dict,admin_key: str) -> str:
    if len(admin_key)<30:raise ValueError('TRUSTED_ADMIN_KEY_REQUIRED')
    fields={key:identity[key] for key in ('device_id','tenant_id','public_key','authority','origin','expires_at','enrolled_by')}
    return hmac.new(admin_key.encode(),b'phone-device-v1\0'+canonical(fields),hashlib.sha256).hexdigest()


def commit_message(gid: str,envelope_hash: str) -> dict:
    return {'action':'DPAPI_COMMITTED','grant_id':gid,'envelope_hash':envelope_hash,'status':'APPLIED'}
