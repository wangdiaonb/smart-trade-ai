# Independent Login Demo Design

## Goal

Create a small, local browser-based demonstration of open account registration and login. It is a separate application and must not import or modify Smart Trade AI modules, license checks, trial handling, or activation behavior.

## Scope

- Open registration using email and password.
- Login and logout with a server-managed session.
- A minimal Chinese-language workspace showing the signed-in email and a logout control.
- Local SQLite persistence so accounts survive application restarts.
- Passwords are stored only as salted, computationally expensive hashes; never store or log plaintext passwords.
- Clear validation for invalid email/password input, duplicate email addresses, and incorrect credentials.

Email verification, password reset, external identity providers, roles, billing, remote hosting, and the original product's business features are out of scope.

## Architecture

The new `login-demo/` directory will contain a standalone FastAPI application, its own static HTML/CSS/JavaScript, and its own SQLite database file. It will not import code from the existing `trade` package. The browser communicates with the local FastAPI server over same-origin HTTP endpoints. Registration and login write/read the demo database; successful login places only the account identifier in an HttpOnly, SameSite session cookie. Logout clears that session.

The app is intended for local demonstration, not public production deployment. Session signing configuration and cookie settings will be isolated in the new app. The UI must distinguish unauthenticated and authenticated states and must not expose account data before authentication.

## Main flows

1. A visitor opens the app and sees login and registration forms.
2. Registration validates fields, normalizes the email, hashes the password, and creates a unique account. Duplicate email returns a clear error without revealing existing account details beyond the duplicate-registration case.
3. Login validates credentials and establishes a session. Invalid credentials return a generic error.
4. The workspace requires a valid session and displays the signed-in email.
5. Logout invalidates the session and returns the visitor to the login screen.

## Verification

Automated tests will cover successful registration and login, duplicate registration, invalid credentials, access to the workspace without a session, authenticated workspace access, logout, and persistence across app restarts where practical. A basic frontend smoke check will verify that the login/register forms and authenticated workspace render and connect to the API.

## Acceptance criteria

- The application runs independently from the original Smart Trade AI application.
- A new user can register, sign in, view the protected workspace, and sign out.
- Passwords are never stored in plaintext.
- Duplicate accounts and invalid credentials are handled without server errors.
- No original trial, license, or activation code is changed or bypassed.
