"""Encryption, fingerprints and masking for sensitive values.

Three tools, three jobs:
  encrypt / decrypt   keep the full value unreadable in the database
  fingerprint         compare two values without decrypting either
  mask                what people see by default (***-**-3390)
"""
import hashlib
import hmac
import os
import re

from cryptography.fernet import Fernet

SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-(\d{4})\b")


def _key() -> bytes:
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return key.encode()


def encrypt(value: str | bytes) -> bytes:
    data = value.encode() if isinstance(value, str) else value
    return Fernet(_key()).encrypt(data)


def decrypt(token: bytes) -> bytes:
    return Fernet(_key()).decrypt(bytes(token))


def fingerprint(value: str) -> str:
    """Keyed hash (HMAC-SHA256). Same input -> same output, but without the key
    nobody can test guesses against it. Digits only, so '666-74-3390' and
    '666743390' match."""
    normalized = re.sub(r"\D", "", value)
    hmac_key = hashlib.sha256(b"workpaper-hmac:" + _key()).digest()
    return hmac.new(hmac_key, normalized.encode(), hashlib.sha256).hexdigest()


def last4(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return digits[-4:]


def mask_ssn(value: str) -> str:
    return f"***-**-{last4(value)}"


def mask_generic(value: str) -> str:
    return f"****{last4(value)}"


def mask_text(text: str | None, secrets: list[str]) -> str | None:
    """Mask every SSN-shaped number plus any known secret (account numbers,
    PINs) inside free text such as printed document pages."""
    if text is None:
        return None
    out = SSN_PATTERN.sub(lambda m: f"***-**-{m.group(1)}", text)
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret and secret in out:
            out = out.replace(secret, mask_generic(secret))
    out = re.sub(r"\bPIN (\d{5})\b", "PIN *****", out)  # e-signature PINs
    return out
