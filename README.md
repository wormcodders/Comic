# ComicVault

Comic library and reader built with Flask, SQLAlchemy, Pillow, and PyMuPDF.
Python 3.11 or newer is required.

## Run locally

From the project directory on Windows:

    py -m venv venv
    .\venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2"
    .\venv\Scripts\python.exe -m pip install -r requirements.txt
    .\venv\Scripts\python.exe -m flask --app main create-admin
    .\venv\Scripts\python.exe main.py

The administrator command prompts for a username, email, and password. The app
starts at http://127.0.0.1:5000. Development creates a random persistent secret
in instance/.secret_key when SECRET_KEY is unset. Keep this file private.

There is no automatic administrator with a shared password. To recover an
existing administrator, use its existing username and email:

    .\venv\Scripts\python.exe -m flask --app main create-admin --reset-password

This command changes the password locally and invalidates prior sessions.
Administrator accounts cannot recover passwords through security questions.

## Production and Docker

Copy .env.example to .env and generate a secret:

    .\venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"

Set SECRET_KEY to that generated value. Docker Compose supplies Redis for shared
rate limits and selects production configuration:

    docker compose up --build -d
    docker compose exec web python -m flask --app main create-admin

Use HTTPS in production. For local Docker testing over HTTP only, set
SESSION_COOKIE_SECURE=false in .env. A production installation outside Docker
also needs APP_ENV=production and a shared RATELIMIT_STORAGE_URI, such as
redis://localhost:6379/0. Configure a reverse proxy's trusted forwarded-header
addresses in Gunicorn when terminating HTTPS at that proxy.

Route uploaded media through Flask. Serving static/uploads directly through a
proxy or CDN bypasses the application's access checks.

Catbox and UpFiles publish public URLs. Private comics, drafts, and pending user
submissions use local storage. Existing public cloud URLs cannot become
confidential merely by changing a comic's visibility.

## Credentials after upgrading

Replace legacy default administrator passwords with the local recovery command.
Rotate any real credentials that were committed to Git. Removing files from
tracking does not erase earlier commits.

Encrypted API settings depend on a stable encryption key. After replacing a
legacy secret, re-enter the provider credentials in the administrator settings.
An optional, independently generated CREDENTIAL_ENCRYPTION_KEY keeps settings
encryption separate from session-key rotation.

## Tests

    .\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
    .\venv\Scripts\python.exe -m unittest discover -s tests -v
    node --test tests/frontend.test.cjs
    .\venv\Scripts\python.exe -m pip_audit --progress-spinner off

Tests use temporary databases and media. External uploads and AI calls are
mocked. CI runs Python 3.11 and 3.14 tests, JavaScript checks, dependency auditing,
and a container build.

See [SECURITY_REVIEW.md](SECURITY_REVIEW.md) for the audit findings and validation.
