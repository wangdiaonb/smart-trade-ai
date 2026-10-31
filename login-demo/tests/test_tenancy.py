import sqlite3

import pytest

from fastapi.testclient import TestClient

from app import create_app
from auth import hash_password
from database import connection


def account(client, email="first@example.com"):
    response = client.post("/api/register", json={"email": email, "password": "correct-horse-1"})
    assert response.status_code == 201
    return response.json()


def test_registration_creates_exactly_one_default_workspace(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    client = TestClient(create_app(path, "test-secret"))
    user = account(client)
    workspace = client.get("/api/workspace")
    assert workspace.status_code == 200
    assert workspace.json()["owner_user_id"] == user["id"]
    assert workspace.json()["name"] == "我的公司"
    assert client.get("/api/workspace").json() == workspace.json()
    duplicate = client.post("/api/register", json={"email": user["email"], "password": "correct-horse-1"})
    assert duplicate.status_code == 409
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM workspaces").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM companies").fetchone()[0] == 1


def test_each_account_has_a_separate_workspace_and_cannot_forge_context(tmp_path):
    app = create_app(tmp_path / "accounts.sqlite3", "test-secret")
    first, second = TestClient(app), TestClient(app)
    account(first)
    account(second, "second@example.com")
    own = first.get("/api/workspace").json()
    other = second.get("/api/workspace").json()
    assert own["id"] != other["id"]
    spoofed = first.get("/api/workspace", headers={"X-Workspace-ID": str(other["id"])})
    assert spoofed.status_code == 404
    assert first.get(f'/api/workspace?workspace_id={other["id"]}').json() == own


def test_workspace_requires_login_and_rejects_tampered_cookie(tmp_path):
    client = TestClient(create_app(tmp_path / "accounts.sqlite3", "test-secret"))
    assert client.get("/api/workspace").status_code == 401
    account(client)
    client.cookies.clear()
    client.cookies.set("login_demo_session", "forged")
    assert client.get("/api/workspace").status_code == 401


def test_existing_demo_accounts_are_backfilled_idempotently(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    salt, digest = hash_password("correct-horse-1")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL COLLATE NOCASE UNIQUE, salt TEXT NOT NULL, password_hash TEXT NOT NULL)")
        conn.execute("INSERT INTO users(email,salt,password_hash) VALUES (?,?,?)", ("legacy@example.com", salt, digest))
    create_app(path, "test-secret")
    client = TestClient(create_app(path, "test-secret"))
    assert client.post("/api/login", json={"email": "legacy@example.com", "password": "correct-horse-1"}).status_code == 200
    assert client.get("/api/workspace").status_code == 200
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM workspaces").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM companies").fetchone()[0] == 1
        assert conn.execute("SELECT email FROM users").fetchone()[0] == "legacy@example.com"


def test_registration_rolls_back_if_workspace_creation_fails(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    client = TestClient(create_app(path, "test-secret"), raise_server_exceptions=False)
    # Simulate a storage failure after the user row has been inserted.
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER reject_workspace BEFORE INSERT ON workspaces BEGIN SELECT RAISE(ABORT, 'storage failure'); END")
    assert client.post("/api/register", json={"email": "first@example.com", "password": "correct-horse-1"}).status_code == 500
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0


def test_database_rejects_cross_workspace_company_links(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    app = create_app(path, "test-secret")
    first, second = TestClient(app), TestClient(app)
    account(first)
    account(second, "second@example.com")
    first_workspace = first.get("/api/workspace").json()["id"]
    second_company = second.get("/api/company").json()["id"]
    with pytest.raises(sqlite3.IntegrityError), connection(path) as conn:
        conn.execute("INSERT INTO customers(workspace_id,company_id,name) VALUES (?,?,?)", (first_workspace, second_company, "wrong owner"))


def test_deleted_account_cannot_keep_access_with_existing_cookie(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    client = TestClient(create_app(path, "test-secret"))
    user = account(client)
    with connection(path) as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    assert client.get("/api/company").status_code == 401
    assert client.get("/api/workspace").status_code == 401
