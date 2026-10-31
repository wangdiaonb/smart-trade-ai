import os
import secrets
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from auth import authenticate_user, init_db, register_user

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
DEFAULT_DB_PATH = APP_DIR / "data" / "accounts.sqlite3"


class Credentials(BaseModel):
    email: str
    password: str


def create_app(db_path: Path | None = None, secret_key: str | None = None) -> FastAPI:
    resolved_db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    init_db(resolved_db_path)

    app = FastAPI(title="Login Demo")
    app.state.db_path = resolved_db_path
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key or os.getenv("LOGIN_DEMO_SECRET") or secrets.token_urlsafe(32),
        session_cookie="login_demo_session",
        same_site="lax",
        https_only=False,
    )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.post("/api/register", status_code=status.HTTP_201_CREATED)
    def register(credentials: Credentials, request: Request) -> dict[str, object]:
        try:
            user = register_user(resolved_db_path, credentials.email, credentials.password)
        except ValueError as exc:
            if str(exc) == "email already registered":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already registered",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid email or password",
            ) from exc
        request.session.clear()
        request.session["user_id"] = user["id"]
        return user

    @app.post("/api/login")
    def login(credentials: Credentials, request: Request) -> dict[str, object]:
        user = authenticate_user(resolved_db_path, credentials.email, credentials.password)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        request.session.clear()
        request.session["user_id"] = user["id"]
        return user

    @app.get("/api/me")
    def current_user(request: Request) -> dict[str, object]:
        user_id = request.session.get("user_id")
        if not isinstance(user_id, int):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")
        with sqlite3.connect(resolved_db_path) as conn:
            row = conn.execute("SELECT id, email FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            request.session.clear()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")
        return {"id": int(row[0]), "email": row[1]}

    @app.post("/api/logout")
    def logout(request: Request) -> dict[str, bool]:
        request.session.clear()
        return {"ok": True}

    return app


app = create_app()
