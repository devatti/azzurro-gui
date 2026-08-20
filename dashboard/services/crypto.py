"""Symmetric encryption helpers for storing ZCS credentials at rest.

Values are encrypted with Fernet (AES-CBC + HMAC) using a key derived from
Django's ``SECRET_KEY``, so credentials never live in plain text in the
database.

NOTE: the cipher key is derived from ``SECRET_KEY``. If you rotate
``SECRET_KEY`` the stored credentials can no longer be decrypted.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from django.conf import settings


def _fernet():
    digest = hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plain):
    """Encrypt a string for storage. Empty/None stay empty."""
    if not plain:
        return ''
    return _fernet().encrypt(plain.encode('utf-8')).decode('ascii')


def decrypt(token):
    """Decrypt a stored ciphertext. Invalid/empty tokens return ''."""
    if not token:
        return ''
    try:
        return _fernet().decrypt(token.encode('ascii')).decode('utf-8')
    except (InvalidToken, ValueError):
        return ''