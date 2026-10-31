import hashlib
import hmac
import re
import secrets
import sqlite3
from pathlib import Path

from database import connection, create_default_workspace, migrate

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PASSWORD_ITERATIONS = 310_000


def init_db(db_path: Path) -> None:
    migrate(db_path)


def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS
    )
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, digest_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
        expected_digest = bytes.fromhex(digest_hex)
    except (TypeError, ValueError):
        return False
    actual_digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def _normalize_and_validate(email: str, password: str) -> str:
    if not isinstance(email, str) or not isinstance(password, str):
        raise ValueError("invalid email or password")
    normalized_email = email.strip().lower()
    if (
        len(normalized_email) > 254
        or not _EMAIL_PATTERN.fullmatch(normalized_email)
        or not 8 <= len(password) <= 128
    ):
        raise ValueError("invalid email or password")
    return normalized_email


def register_user(db_path: Path, email: str, password: str) -> dict[str, object]:
    normalized_email = _normalize_and_validate(email, password)
    salt, password_hash = hash_password(password)
    init_db(db_path)
    try:
        with connection(db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO users(email, salt, password_hash) VALUES (?, ?, ?)",
                (normalized_email, salt, password_hash),
            )
            user_id = cursor.lastrowid
            create_default_workspace(conn, user_id)
    except sqlite3.IntegrityError as exc:
        if "users.email" in str(exc):
            raise ValueError("email already registered") from exc
        raise
    return {"id": int(user_id), "email": normalized_email}


def authenticate_user(
    db_path: Path, email: str, password: str
) -> dict[str, object] | None:
    if not isinstance(email, str) or not isinstance(password, str):
        return None
    normalized_email = email.strip().lower()
    init_db(db_path)
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, email, salt, password_hash FROM users WHERE email = ?",
            (normalized_email,),
        ).fetchone()
    if row is None or not verify_password(password, row[2], row[3]):
        return None
    return {"id": int(row[0]), "email": row[1]}
