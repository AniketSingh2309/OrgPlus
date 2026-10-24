"""Fernet encryption for stored credentials.

Generate a key with `python -m orgpulse.crypto --new-key` and put it in
CREDENTIAL_ENC_KEY. Losing the key means re-uploading the service account JSON.
"""

from __future__ import annotations

import sys

from cryptography.fernet import Fernet, InvalidToken

from orgpulse.config import get_settings


class CredentialKeyError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().credential_enc_key
    if not key:
        raise CredentialKeyError("CREDENTIAL_ENC_KEY is not set")
    try:
        return Fernet(key.encode())
    except ValueError as err:
        raise CredentialKeyError("CREDENTIAL_ENC_KEY is not a valid Fernet key") from err


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as err:
        raise CredentialKeyError("stored credential cannot be decrypted with this key") from err


if __name__ == "__main__":
    if "--new-key" in sys.argv:
        print(Fernet.generate_key().decode())
    else:
        print("usage: python -m orgpulse.crypto --new-key")
