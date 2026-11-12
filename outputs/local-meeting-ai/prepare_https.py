"""Issue an IP-specific, self-signed end-entity certificate. Distribute only the .cer."""
import datetime as dt
import ipaddress
from pathlib import Path
import sys
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ip = ipaddress.ip_address(sys.argv[1])
target = Path(__file__).resolve().parent/'state/https'
target.mkdir(exist_ok=True)
if any(target.iterdir()):
    sys.exit('Сертификат уже подготовлен. Автоматическая замена отключена.')
key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Protocol LAN '+str(ip))])
now = dt.datetime.now(dt.timezone.utc)
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-dt.timedelta(minutes=5))
        .not_valid_after(now+dt.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip), x509.DNSName('localhost'),
                       x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
        .sign(key,hashes.SHA256()))
(target/'server.key').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
(target/'server.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
(target/'Protocol-LAN.cer').write_bytes(cert.public_bytes(serialization.Encoding.DER))
print(cert.fingerprint(hashes.SHA256()).hex())
