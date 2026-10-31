from fastapi.testclient import TestClient

from app import create_app


def test_registration_login_me_and_logout(tmp_path):
    client = TestClient(create_app(tmp_path / "accounts.sqlite3", "test-secret"))
    payload = {"email": "a@example.com", "password": "correct-horse-1"}

    created = client.post("/api/register", json=payload)
    assert created.status_code == 201
    assert created.json() == {"id": 1, "email": "a@example.com"}
    cookie = created.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert client.get("/api/me").json() == created.json()

    assert client.post("/api/logout").json() == {"ok": True}
    assert client.get("/api/me").status_code == 401

    logged_in = client.post("/api/login", json=payload)
    assert logged_in.status_code == 200
    assert logged_in.json() == created.json()


def test_workspace_identity_requires_login_and_invalid_login_is_generic(tmp_path):
    client = TestClient(create_app(tmp_path / "accounts.sqlite3", "test-secret"))

    assert client.get("/api/me").status_code == 401
    bad = client.post(
        "/api/login",
        json={"email": "missing@example.com", "password": "wrong-password"},
    )
    assert bad.status_code == 401
    assert bad.json() == {"detail": "Invalid email or password"}


def test_duplicate_registration_returns_conflict(tmp_path):
    client = TestClient(create_app(tmp_path / "accounts.sqlite3", "test-secret"))
    payload = {"email": "a@example.com", "password": "correct-horse-1"}

    assert client.post("/api/register", json=payload).status_code == 201
    duplicate = client.post("/api/register", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Email already registered"}


def test_invalid_registration_is_unprocessable(tmp_path):
    client = TestClient(create_app(tmp_path / "accounts.sqlite3", "test-secret"))

    response = client.post(
        "/api/register", json={"email": "bad", "password": "short"}
    )

    assert response.status_code == 422


def test_root_serves_login_ui(tmp_path):
    client = TestClient(create_app(tmp_path / "accounts.sqlite3", "test-secret"))

    response = client.get("/")

    assert response.status_code == 200
    assert 'id="login-form"' in response.text
    assert 'id="register-form"' in response.text
    assert 'id="workspace"' in response.text
    assert 'id="register-form" class="auth-form" hidden' in response.text
    assert 'id="register-email" name="email" type="email"' in response.text
    assert 'id="register-password" name="password" type="password" autocomplete="new-password" minlength="8" maxlength="128" required' in response.text
    assert "novalidate" not in response.text


def test_static_assets_are_served(tmp_path):
    client = TestClient(create_app(tmp_path / "accounts.sqlite3", "test-secret"))

    css = client.get("/static/app.css")
    javascript = client.get("/static/app.js")

    assert css.status_code == 200
    assert "--accent" in css.text
    assert javascript.status_code == 200
    assert "restoreSession" in javascript.text
