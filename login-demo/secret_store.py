"""Local persistent encryption for provider keys; ciphertext is tenant-bound."""

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecretStore:
    def __init__(self, key_path: Path):
        key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            key = key_path.read_bytes()
        except FileNotFoundError:
            key = Fernet.generate_key()
            try:
                descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                key = key_path.read_bytes()
            else:
                with os.fdopen(descriptor, 'wb') as target:
                    target.write(key)
        self.cipher = Fernet(key)

    def encrypt(self, workspace_id: int, key: str) -> str:
        payload = json.dumps({"workspace_id": workspace_id, "key": key}).encode()
        return self.cipher.encrypt(payload).decode()

    def decrypt(self, workspace_id: int, ciphertext: str) -> str:
        try:
            payload = json.loads(self.cipher.decrypt(ciphertext.encode()))
            if payload["workspace_id"] != workspace_id:
                raise ValueError("Workspace mismatch")
            return payload["key"]
        except (InvalidToken, KeyError, ValueError, TypeError) as exc:
            raise ValueError("模型密钥无法解密，请在模型设置重新填写。") from exc

