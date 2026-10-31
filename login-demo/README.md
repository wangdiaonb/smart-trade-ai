# Workroom Login Demo

A standalone local registration and login demo. It does not import or change the Smart Trade AI application.

## Run on Windows

From this directory:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000` in a browser.

## Run on macOS or Linux

From this directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn app:app --reload
```

## Test

```sh
python -m pytest tests -q
```

Accounts are stored in `login-demo/data/accounts.sqlite3` when the app runs from the repository root, or in `data/accounts.sqlite3` when run from this directory. Passwords are stored as salted PBKDF2 hashes.

Set `LOGIN_DEMO_SECRET` before starting the server if sessions should remain valid across restarts. Without it, a fresh local secret is generated on each process start, invalidating existing sessions after restart.

This is a local demonstration, not a production deployment. Do not expose it to a public network without adding production-grade deployment configuration and additional security controls.
