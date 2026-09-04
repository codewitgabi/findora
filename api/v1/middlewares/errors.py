from fastapi import Request, status, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from starlette.exceptions import HTTPException as StarletteHTTPException

from pymongo.errors import (
    BulkWriteError,
    ConfigurationError,
    CursorNotFound,
    DocumentTooLarge,
    DuplicateKeyError,
    ExecutionTimeout,
    InvalidOperation,
    OperationFailure,
    ProtocolError,
    PyMongoError,
    WriteError,
    WTimeoutError,
)

from api.v1.utils.logger import get_logger

logger = get_logger("exception_handler")


def _request_meta(request: Request) -> dict:
    """Return a dict of common request fields for structured log entries."""
    return {
        "request_id": getattr(request.state, "request_id", None),
        "path": request.url.path,
        "method": request.method,
    }


def _error_response(status_code: int, message: str, **extra) -> JSONResponse:
    """
    Build a uniform JSON error response.

    Args:
        status_code: HTTP status code to return.
        message:     Human-readable error description.
        **extra:     Any additional top-level fields (e.g. ``errors``).

    Returns:
        JSONResponse with the standard error envelope.
    """
    body = {"success": False, "status_code": status_code, "message": message}
    body.update(extra)
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


def _field_from_index(index_name: str) -> str:
    """
    Derive a human-friendly field name from a MongoDB index name.

    MongoDB index names typically follow the pattern ``field_1`` or
    ``field_-1``. This helper strips the direction suffix so callers can
    embed the bare field name in user-facing messages.

    Args:
        index_name: Raw index name returned by MongoDB (e.g. ``email_1``).

    Returns:
        The field portion of the index name, or ``"field"`` as a fallback.
    """
    if not index_name or index_name == "unknown":
        return "field"
    return index_name.split("_")[0] if "_" in index_name else index_name


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Handle Pydantic / FastAPI request-body and query-param validation errors.

    Pydantic v2 raises ``RequestValidationError`` when incoming data fails
    schema validation. Each violated field is normalised into a flat dict so
    clients receive a predictable ``errors`` list.

    Returns HTTP 422 Unprocessable Entity.
    """
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"] if loc != "body")
        errors.append(
            {
                "field": field or "body",
                "message": error["msg"],
                "type": error["type"],
            }
        )

    logger.warning(
        "Validation error",
        extra={**_request_meta(request), "errors": errors},
    )

    return _error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Validation error",
        errors=errors,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Handle explicit ``HTTPException`` raises from route handlers.

    These are intentional errors raised with ``raise HTTPException(...)`` inside
    application code (e.g. 404 Not Found, 401 Unauthorized). The handler
    forwards the status code and detail message verbatim.
    """
    logger.warning(
        "HTTP exception",
        extra={
            **_request_meta(request),
            "status_code": exc.status_code,
            "detail": exc.detail,
        },
    )
    return _error_response(exc.status_code, exc.detail)


async def starlette_http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """
    Handle low-level Starlette HTTP exceptions (routing layer errors).

    Starlette raises its own ``HTTPException`` subclass for framework-level
    errors such as 404 (route not found) and 405 (method not allowed) before
    any route code executes. This handler provides meaningful messages for the
    most common status codes and falls back gracefully for anything else.

    Errors below 500 are logged at WARNING; 500+ are logged at ERROR.
    """
    _status_messages = {
        400: "Bad request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Resource not found",
        405: "Method not allowed",
        408: "Request timeout",
        409: "Conflict",
        410: "Resource gone",
        429: "Too many requests",
        500: "Internal server error",
        502: "Bad gateway",
        503: "Service unavailable",
        504: "Gateway timeout",
    }
    message = exc.detail or _status_messages.get(exc.status_code, "An error occurred")

    log_level = "warning" if exc.status_code < 500 else "error"
    getattr(logger, log_level)(
        "Starlette HTTP exception",
        extra={
            **_request_meta(request),
            "status_code": exc.status_code,
            "response_message": message,
        },
    )
    return _error_response(exc.status_code, message)


async def mongodb_duplicate_key_error_handler(
    request: Request, exc: DuplicateKeyError
) -> JSONResponse:
    """
    Handle MongoDB unique-index violations (error code 11000).

    Raised when an insert or update would create a duplicate value in a field
    that has a unique index. The handler attempts to extract the field name
    from the index metadata so the message is actionable for the client.

    Returns HTTP 409 Conflict.
    """
    details = exc.details or {}
    field_name = _field_from_index(details.get("index", "unknown"))
    message = f"A record with this {field_name} already exists"

    logger.warning(
        "MongoDB duplicate key error",
        extra={
            **_request_meta(request),
            "index": details.get("index"),
            "error_code": details.get("code"),
        },
    )
    return _error_response(status.HTTP_409_CONFLICT, message)


async def mongodb_bulk_write_error_handler(
    request: Request, exc: BulkWriteError
) -> JSONResponse:
    """
    Handle errors that arise during ``collection.bulk_write()`` operations.

    PyMongo collects individual write failures and surfaces them together as a
    ``BulkWriteError``. This handler inspects each sub-error for duplicate-key
    violations (code 11000) and returns 409 if found, otherwise 400.

    Returns HTTP 409 Conflict or HTTP 400 Bad Request.
    """
    write_errors = exc.details.get("writeErrors", [])
    duplicate_error = next((e for e in write_errors if e.get("code") == 11000), None)

    if duplicate_error:
        index_name = duplicate_error.get("indexPattern", {}).get("index", "unknown")
        field_name = _field_from_index(index_name)
        message = f"A record with this {field_name} already exists"
        status_code = status.HTTP_409_CONFLICT
    else:
        message = "Database write operation failed"
        status_code = status.HTTP_400_BAD_REQUEST

    logger.warning(
        "MongoDB bulk write error",
        extra={
            **_request_meta(request),
            "write_errors_count": len(write_errors),
            "error_code": duplicate_error.get("code") if duplicate_error else None,
        },
    )
    return _error_response(status_code, message)


async def mongodb_write_error_handler(
    request: Request, exc: WriteError
) -> JSONResponse:
    """
    Handle generic MongoDB write errors from single-document operations.

    ``WriteError`` is raised for failed inserts, updates, or deletes that are
    not covered by the more specific ``DuplicateKeyError``. Code 11000 is still
    possible here (e.g. from ``update`` with ``upsert=True``).

    Returns HTTP 409 Conflict for duplicates, HTTP 400 Bad Request otherwise.
    """
    details = exc.details or {}
    error_code = details.get("code", 0)

    if error_code == 11000:
        field_name = _field_from_index(details.get("index", "unknown"))
        message = f"A record with this {field_name} already exists"
        status_code = status.HTTP_409_CONFLICT
    else:
        message = "Database write operation failed"
        status_code = status.HTTP_400_BAD_REQUEST

    logger.warning(
        "MongoDB write error",
        extra={**_request_meta(request), "error_code": error_code},
    )
    return _error_response(status_code, message)


async def mongodb_wtimeout_error_handler(
    request: Request, exc: WTimeoutError
) -> JSONResponse:
    """
    Handle MongoDB write-concern timeout errors.

    ``WTimeoutError`` is raised when a write operation does not receive the
    requested number of acknowledgements within the specified ``wtimeout``
    window. The write may or may not have been applied to the primary.

    Returns HTTP 504 Gateway Timeout.
    """
    logger.warning(
        "MongoDB write concern timeout",
        extra={**_request_meta(request), "error_message": str(exc)},
    )
    return _error_response(
        status.HTTP_504_GATEWAY_TIMEOUT,
        "Database write acknowledgement timed out. The operation may have partially succeeded.",
    )


async def mongodb_connection_error_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """
    Handle MongoDB connectivity errors.

    Covers three related exception types that should be registered separately
    in ``main.py`` but share this single handler:

    * ``ServerSelectionTimeoutError`` — no suitable server could be found
      within the configured ``serverSelectionTimeoutMS``.
    * ``ConnectionFailure`` — the driver lost or could not establish a
      connection to the MongoDB host.
    * ``NetworkTimeout`` — a network-level timeout occurred mid-operation.

    Returns HTTP 503 Service Unavailable.
    """
    logger.error(
        "MongoDB connection error",
        extra={
            **_request_meta(request),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        },
    )
    return _error_response(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Database connection unavailable. Please try again later.",
    )


async def mongodb_protocol_error_handler(
    request: Request, exc: ProtocolError
) -> JSONResponse:
    """
    Handle MongoDB wire-protocol errors.

    ``ProtocolError`` indicates that the driver received a response from the
    server that does not conform to the MongoDB wire protocol. This usually
    points to a version mismatch or a corrupted connection.

    Returns HTTP 502 Bad Gateway.
    """
    logger.error(
        "MongoDB protocol error",
        extra={
            **_request_meta(request),
            "error_message": str(exc),
        },
    )
    return _error_response(
        status.HTTP_502_BAD_GATEWAY,
        "Unexpected response from the database. Please contact support.",
    )


async def mongodb_operation_failure_handler(
    request: Request, exc: OperationFailure
) -> JSONResponse:
    """
    Handle MongoDB server-side operation failures.

    ``OperationFailure`` is the base class for errors returned by the MongoDB
    server (e.g. authentication failures, authorisation errors, or query plan
    executor errors). Common codes handled explicitly:

    * ``11000`` — duplicate key (fallback if not caught earlier in the chain).
    * ``13``    — unauthorised / insufficient privileges.
    * ``50``    — ``MaxTimeMSExpired``.

    Returns HTTP 409, 403, 408, or 400 depending on the error code.
    """
    error_code = exc.code if hasattr(exc, "code") else None

    if error_code == 11000:
        message = "A record with this value already exists"
        status_code = status.HTTP_409_CONFLICT
    elif error_code == 13:
        message = "Insufficient database privileges"
        status_code = status.HTTP_403_FORBIDDEN
    elif error_code == 50:
        message = "Database operation timed out"
        status_code = status.HTTP_408_REQUEST_TIMEOUT
    else:
        message = "Database operation failed"
        status_code = status.HTTP_400_BAD_REQUEST

    logger.warning(
        "MongoDB operation failure",
        extra={
            **_request_meta(request),
            "error_code": error_code,
            "error_message": str(exc),
        },
    )
    return _error_response(status_code, message)


async def mongodb_configuration_error_handler(
    request: Request, exc: ConfigurationError
) -> JSONResponse:
    """
    Handle MongoDB driver configuration errors.

    ``ConfigurationError`` is raised when the PyMongo driver is initialised
    with invalid options (e.g. a malformed URI, conflicting TLS settings, or
    unsupported read-preference mode). These are programming errors and should
    be surfaced prominently in logs.

    Returns HTTP 500 Internal Server Error.
    """
    logger.error(
        "MongoDB configuration error",
        extra={**_request_meta(request), "error_message": str(exc)},
    )
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Database configuration error. Please contact support.",
    )


async def mongodb_execution_timeout_handler(
    request: Request, exc: ExecutionTimeout
) -> JSONResponse:
    """
    Handle MongoDB cursor / aggregation execution timeouts.

    ``ExecutionTimeout`` is raised when a ``maxTimeMS`` budget is exhausted
    while the server is executing a query or aggregation pipeline. Unlike
    ``OperationFailure`` with code 50, this exception has its own class in
    PyMongo and should be registered before the generic ``OperationFailure``
    handler.

    Returns HTTP 408 Request Timeout.
    """
    logger.warning(
        "MongoDB execution timeout",
        extra={**_request_meta(request), "error_message": str(exc)},
    )
    return _error_response(
        status.HTTP_408_REQUEST_TIMEOUT,
        "Database operation timed out. Please try again.",
    )


async def mongodb_cursor_not_found_handler(
    request: Request, exc: CursorNotFound
) -> JSONResponse:
    """
    Handle expired or invalid MongoDB server-side cursors.

    ``CursorNotFound`` is raised when the application tries to iterate a
    cursor that has already been closed on the server — typically because the
    ``cursorTimeoutMS`` was exceeded during a long-running batch iteration.

    Returns HTTP 410 Gone.
    """
    logger.warning(
        "MongoDB cursor not found",
        extra={**_request_meta(request), "error_message": str(exc)},
    )
    return _error_response(
        status.HTTP_410_GONE,
        "The database cursor expired. Please retry the request from the beginning.",
    )


async def mongodb_document_too_large_handler(
    request: Request, exc: DocumentTooLarge
) -> JSONResponse:
    """
    Handle attempts to insert or update a document that exceeds the 16 MB BSON limit.

    MongoDB enforces a hard 16 MB cap on individual documents. This handler
    converts the driver-level exception into a meaningful client error rather
    than leaking a 500.

    Returns HTTP 413 Request Entity Too Large.
    """
    logger.warning(
        "MongoDB document too large",
        extra={**_request_meta(request), "error_message": str(exc)},
    )
    return _error_response(
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        "The document exceeds the maximum allowed size of 16 MB.",
    )


async def mongodb_invalid_operation_handler(
    request: Request, exc: InvalidOperation
) -> JSONResponse:
    """
    Handle invalid PyMongo driver operations.

    ``InvalidOperation`` is raised for driver-level misuse, such as iterating
    an already-exhausted cursor a second time or calling an operation that is
    not valid in the current context.

    Returns HTTP 400 Bad Request.
    """
    logger.warning(
        "MongoDB invalid operation",
        extra={**_request_meta(request), "error_message": str(exc)},
    )
    return _error_response(
        status.HTTP_400_BAD_REQUEST,
        "Invalid database operation requested.",
    )


async def mongodb_generic_error_handler(
    request: Request, exc: PyMongoError
) -> JSONResponse:
    """
    Catch-all handler for any remaining ``PyMongoError`` subclass.

    This handler sits at the bottom of the PyMongo handler chain and catches
    any driver error that was not matched by a more specific handler above.
    It should be registered *before* the generic ``Exception`` handler in
    ``main.py``.

    Returns HTTP 500 Internal Server Error.
    """
    logger.error(
        "Unhandled PyMongo error",
        extra={
            **_request_meta(request),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        },
        exc_info=True,
    )
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "An unexpected database error occurred. Please try again later.",
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler for any unhandled Python exception.

    This is the last line of defence and should always be registered last in
    ``main.py``. It logs the full traceback (``exc_info=True``) so that
    developers can diagnose novel failures, while returning a safe, opaque
    message to the client.

    Returns HTTP 500 Internal Server Error.
    """
    logger.error(
        "Unexpected error",
        extra={
            **_request_meta(request),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        },
        exc_info=True,
    )
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "An unexpected error occurred. Please try again later.",
    )
