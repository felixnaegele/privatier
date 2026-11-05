"""The encrypted key file that links tokens back to real values.

Format (all local, one file):
    b"PRIVATIER1" | 16-byte salt | 12-byte nonce | AES-256-GCM ciphertext

The encryption key is derived from the user's password with scrypt, a
deliberately slow algorithm that makes password guessing expensive. Without
the password the file is useless; if the password is lost, the mapping cannot
be recovered (by design).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"PRIVATIER1"


class WrongPasswordError(Exception):
    pass


def _derive_key(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode("utf-8"))


def save_vault(path: Path, data: dict, password: str) -> None:
    salt, nonce = os.urandom(16), os.urandom(12)
    plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(_derive_key(password, salt)).encrypt(nonce, plaintext, MAGIC)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(MAGIC + salt + nonce + ciphertext)
    os.replace(tmp, path)


def load_vault(path: Path, password: str) -> dict:
    blob = Path(path).read_bytes()
    if not blob.startswith(MAGIC):
        raise ValueError(f"{path} is not a Privatier key file")
    salt = blob[len(MAGIC) : len(MAGIC) + 16]
    nonce = blob[len(MAGIC) + 16 : len(MAGIC) + 28]
    try:
        plaintext = AESGCM(_derive_key(password, salt)).decrypt(nonce, blob[len(MAGIC) + 28 :], MAGIC)
    except InvalidTag as exc:
        raise WrongPasswordError("Wrong password, or the key file was modified.") from exc
    return json.loads(plaintext)
