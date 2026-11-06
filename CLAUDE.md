# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Findora is a FastAPI backend using MongoDB (via Motor, the async driver). The project is in early scaffolding stage — the error-handling, logging, config, and database layers are built out, but the `api/v1/{dependencies,models,routes,schemas,services}` packages are currently empty stubs waiting for feature code.

## Environment & commands

This project uses `uv` for dependency management (`uv.lock` present) and requires Python >=3.13.

```bash
# Install dependencies
uv sync

# Run the app (reads PORT from .env, defaults to 5001)
uv run main.py
# or
uv run uvicorn main:app --reload
```

Tests (needs a local MongoDB; each test uses a throwaway database that is dropped afterwards, override with `TEST_MONGO_URI`):

```bash
uv run pytest            # full API suite
uv run python -m scripts.evaluate_image_search <dataset_dir> --k 1 3 5   # image-search Precision@K on real photos
```

There is no lint config or CI configured yet.

Configuration is loaded from a `.env` file (see `.env.example` for required keys: `PORT`, `MONGO_URI`, `MONGO_DB_NAME`, `MONGO_MAX_POOL_SIZE`, `MONGO_MIN_POOL_SIZE`, `MONGO_SERVER_SELECTION_TIMEOUT_MS`) via `api/v1/utils/config.py` (`pydantic-settings`). Import the shared `config` singleton from there rather than reading env vars directly.

## Architecture

- **`main.py`** — FastAPI app factory/entrypoint. Wires up the DB lifespan (`api/database.py`), CORS, index creation (`api/indexes.py`), and registers exception handlers before mounting `v1_router`.
- **`api/database.py`** — `MongoDB` class wraps a Motor `AsyncIOMotorClient` as a module-level singleton (`db`). Call `await db.connect()`/`await db.disconnect()` only from the app lifespan; use the `get_db()` FastAPI dependency (or `db.get_db()`) elsewhere to obtain the active `AsyncIOMotorDatabase` handle. `db.get_db()` raises `RuntimeError` if called before `connect()`.
- **`api/indexes.py`** — `create_indexes(database)` is called once at startup (in the lifespan) to ensure all collection indexes exist. Add new collection index definitions here.
- **`api/response.py`** — `success_response(message, status_code, data)` builds the standard success envelope (`{success, status_code, message, data}`). Use it for all successful route responses.
- **`api/v1/routes/__init__.py`** — defines `v1_router = APIRouter(prefix="/api/v1")`. Feature routers should be created under `api/v1/routes/` and included into `v1_router`.
- **`api/v1/middlewares/errors.py`** — one handler per exception type, each returning the standard error envelope (`{success: False, status_code, message, ...}`). Covers FastAPI/Starlette validation and HTTP errors plus an extensive set of granular PyMongo/Motor exceptions (duplicate key, bulk write, timeouts, connection failures, protocol errors, etc.), each mapped to an appropriate HTTP status. All handlers are registered explicitly in `main.py` — when adding a new exception type, register its handler there too, keeping more specific exceptions before their parent classes (e.g. `ExecutionTimeout` before the generic `OperationFailure`/`PyMongoError` handlers, and `Exception` registered last as the catch-all).
- **`api/v1/middlewares/logging.py`** — `LoggingMiddleware` (Starlette `BaseHTTPMiddleware`) assigns a `request_id` (`X-Request-ID` header) and logs request start/completion/failure with timing. Not currently added to `app` in `main.py`.
- **`api/v1/utils/logger.py`** — structured JSON logging via `python-json-logger`. `setup_logger()` configures the root `"app"` logger once (called at import time in `main.py`); use `get_logger("<module>")` (returns a logger namespaced under `app.<module>`) in every module rather than `logging.getLogger` directly, and pass contextual fields via the `extra={...}` kwarg so they land as structured JSON fields.
- **`api/v1/utils/config.py`** — `Config(BaseSettings)` singleton instance `config`, loaded from `.env`. Add new environment-driven settings here as typed fields rather than reading `os.environ` ad hoc.

## Domain notes

- Lost and found reports share one `Items` collection (`report_type`, `status`: pending -> active/rejected, active|matched -> resolved). Only `active`/`matched` items are publicly searchable.
- Photo matching uses a 64-bit perceptual hash (`utils/image_hash.py`) stored in `ItemImages` at upload time and copied onto the item; `services/matching.py` holds the hybrid scoring weights and thresholds.
- Admin routes live in `routes/admin.py` behind `require_admin`; every admin mutation calls `record_audit()`. Create the first admin with `uv run python -m scripts.create_admin <email> <name> <password>`.
- Default categories are seeded at startup (`seed_categories`).

## Conventions to follow when adding features

- New collections' index definitions go in `create_indexes()` in `api/indexes.py`, not scattered across route/service files.
- New routers live under `api/v1/routes/`, get included into `v1_router`, and success responses go through `success_response()` in `api/response.py` for a consistent envelope.
- New PyMongo/Starlette/FastAPI exception types need both a handler function in `api/v1/middlewares/errors.py` and a corresponding `app.add_exception_handler(...)` registration in `main.py`, ordered from most-specific to most-generic.
- Use `get_logger(__name__ equivalent)` per module and log with the `extra={...}` pattern already used throughout (e.g. `_request_meta(request)` style dicts) to keep log output structured.
