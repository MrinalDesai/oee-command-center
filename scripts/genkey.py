r"""Generate an RSA key pair for Snowflake key-pair authentication.

Writes:
  %USERPROFILE%\.snowflake\rsa_key.p8   (private key - keep secret)
  %USERPROFILE%\.snowflake\rsa_key.pub  (public key)

Prints the single-line public key body to paste into:
  ALTER USER <name> SET RSA_PUBLIC_KEY='<paste>';
"""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pathlib import Path

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

private_pem = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)

public_pem = key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)

out_dir = Path.home() / ".snowflake"
out_dir.mkdir(exist_ok=True)

priv_path = out_dir / "rsa_key.p8"
pub_path = out_dir / "rsa_key.pub"

priv_path.write_bytes(private_pem)
pub_path.write_bytes(public_pem)

body = (
    public_pem.decode()
    .replace("-----BEGIN PUBLIC KEY-----", "")
    .replace("-----END PUBLIC KEY-----", "")
)
one_line = "".join(body.split())

print()
print("private key :", priv_path)
print("public key  :", pub_path)
print()
print("Copy the line below into the ALTER USER statement:")
print()
print(one_line)
print()

