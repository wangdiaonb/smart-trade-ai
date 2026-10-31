import sqlite3

import pytest

from auth import authenticate_user, hash_password, register_user, verify_password


def test_register_stores_hash_and_authenticates(tmp_path):
    db = tmp_path / "accounts.sqlite3"

    user = register_user(db, "Alice@Example.com", "correct-horse-1")

    assert user == {"id": 1, "email": "alice@example.com"}
    assert authenticate_user(db, "alice@example.com", "correct-horse-1") == user
    assert authenticate_user(db, "alice@example.com", "wrong-password") is None
    with sqlite3.connect(db) as conn:
        stored = conn.execute("SELECT salt, password_hash FROM users").fetchone()
    assert stored and "correct-horse-1" not in stored[0] + stored[1]


def test_hash_password_uses_unique_salts_and_verifies():
    first_salt, first_digest = hash_password("correct-horse-1")
    second_salt, second_digest = hash_password("correct-horse-1")

    assert first_salt != second_salt
    assert first_digest != second_digest
    assert verify_password("correct-horse-1", first_salt, first_digest)
    assert not verify_password("wrong-password", first_salt, first_digest)


def test_register_rejects_duplicate_email_case_insensitively(tmp_path):
    db = tmp_path / "accounts.sqlite3"
    register_user(db, "alice@example.com", "correct-horse-1")

    with pytest.raises(ValueError, match="email already registered"):
        register_user(db, "Alice@Example.com", "another-password")


@pytest.mark.parametrize(
    ("email", "password"),
    [("bad", "correct-horse-1"), ("a@b.co", "short"), ("a@b.co", "x" * 129)],
)
def test_register_rejects_invalid_fields(tmp_path, email, password):
    with pytest.raises(ValueError, match="invalid email or password"):
        register_user(tmp_path / "accounts.sqlite3", email, password)
