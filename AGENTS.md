# Repository Guide

## Runtime and setup

- Use Python 3.8 (`runtime.txt` pins 3.8.14). The 2019-2020 dependency pins are not compatible with a current Python interpreter.
- Install Python dependencies with `python -m pip install -r requirements.txt` and frontend dependencies with Yarn Classic: `yarn install --frozen-lockfile` (`yarn.lock` is v1).
- Configuration is loaded at `import gavel` time. Either create ignored `config.yaml` from `config.template.yaml`, or set `IGNORE_CONFIG_FILE=true` and provide the required environment variables: `BASE_URL`, `ADMIN_PASSWORD`, `SECRET_KEY`, `EMAIL_FROM`, `EMAIL_USER`, and `EMAIL_PASSWORD`. Email values are still read when `DISABLE_EMAIL=true`, so empty values must exist.
- `docker compose up -d postgres redis` starts only PostgreSQL and Redis; the application services are commented out. For a host-run app, override the URLs to `DATABASE_URL=postgresql://postgres:postgres@localhost/postgres` and `REDIS_URL=redis://localhost:6379/0`. The Compose credentials do not match `.env.example`, and `init.sql` is not mounted automatically.
- Initialize tables with `python initialize.py`, then run the development server with `python runserver.py`. Run the asynchronous worker separately with `celery -A gavel:celery worker -E -P eventlet --loglevel=info` when exercising email or Socket.IO background tasks.

## Application wiring

- `gavel/__init__.py` is the application entrypoint: importing it creates the Flask app, applies Eventlet monkey-patching, initializes SQLAlchemy/Marshmallow/Celery/Socket.IO/assets, and imports `gavel.controllers` to register routes and handlers. There is no app factory to call in tests or scripts.
- HTTP behavior is split among `gavel/controllers/{judge,admin,api}.py`; real-time handlers and model-event broadcasts are in `gavel/controllers/socket.py`. Data models and transaction retry behavior are under `gavel/models/`; ranking and project selection use `gavel/crowd_bt.py` and `gavel/controllers/judge.py`.
- Database transactions run at `SERIALIZABLE` isolation. Preserve `with_retries(...)` around write flows that can conflict; it handles PostgreSQL serialization failures and rolls back before retrying.

## Frontend assets

- Edit styles in `gavel/static/css/` and build `gavel/static/generated.scss` with `yarn build`; use `yarn build:watch` during style work. Production builds purge classes by scanning `gavel/**/*.html` and `gavel/**/*.js`, so dynamically constructed class names may be removed.
- Flask-Assets compiles `generated.scss` into `gavel/static/all.css` and combines admin scripts into `gavel/static/admin_all.js`. These three outputs and `.webassets-cache/` are intentionally ignored; do not commit them.
- Templates are server-rendered Jinja under `gavel/templates/`; JavaScript is mostly inline or in `gavel/static/js/admin/`, not a separate SPA.

## Verification

- There is no checked-in automated test, lint, formatter, typecheck, migration, or CI workflow. Do not claim those checks ran.
- At minimum, syntax-check Python edits with `python -m compileall gavel initialize.py runserver.py workers.py`. For frontend changes, run `yarn build`. Changes to startup, models, routes, Celery, or Socket.IO require a configured PostgreSQL/Redis smoke test because importing the app initializes all integrations.
