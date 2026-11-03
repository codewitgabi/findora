import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.database import db
from api.indexes import create_indexes
from api.v1.middlewares.logging import LoggingMiddleware
from api.v1.middlewares.errors import (
    general_exception_handler,
    http_exception_handler,
    mongodb_bulk_write_error_handler,
    mongodb_configuration_error_handler,
    mongodb_connection_error_handler,
    mongodb_cursor_not_found_handler,
    mongodb_document_too_large_handler,
    mongodb_duplicate_key_error_handler,
    mongodb_execution_timeout_handler,
    mongodb_generic_error_handler,
    mongodb_invalid_operation_handler,
    mongodb_operation_failure_handler,
    mongodb_protocol_error_handler,
    mongodb_wtimeout_error_handler,
    mongodb_write_error_handler,
    starlette_http_exception_handler,
    validation_exception_handler,
)
from api.v1.routes import v1_router
from api.v1.services.categories import seed_categories
from api.v1.utils.config import config
from api.v1.utils.logger import setup_logger
from pymongo.errors import (
    BulkWriteError,
    ConfigurationError,
    ConnectionFailure,
    CursorNotFound,
    DocumentTooLarge,
    DuplicateKeyError,
    ExecutionTimeout,
    InvalidOperation,
    NetworkTimeout,
    OperationFailure,
    ProtocolError,
    PyMongoError,
    ServerSelectionTimeoutError,
    WriteError,
    WTimeoutError,
)
from fastapi.middleware.cors import CORSMiddleware

setup_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await create_indexes(db.get_db())
    await seed_categories(db.get_db())
    yield
    await db.disconnect()


app = FastAPI(
    title="Findora API",
    lifespan=lifespan,
    version="1.0.0",
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
)

# Cors middleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(LoggingMiddleware)

# Exception handlers

app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, starlette_http_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(DuplicateKeyError, mongodb_duplicate_key_error_handler)
app.add_exception_handler(BulkWriteError, mongodb_bulk_write_error_handler)
app.add_exception_handler(WTimeoutError, mongodb_wtimeout_error_handler)
app.add_exception_handler(WriteError, mongodb_write_error_handler)
app.add_exception_handler(ServerSelectionTimeoutError, mongodb_connection_error_handler)
app.add_exception_handler(NetworkTimeout, mongodb_connection_error_handler)
app.add_exception_handler(ConnectionFailure, mongodb_connection_error_handler)
app.add_exception_handler(ProtocolError, mongodb_protocol_error_handler)
app.add_exception_handler(ExecutionTimeout, mongodb_execution_timeout_handler)
app.add_exception_handler(CursorNotFound, mongodb_cursor_not_found_handler)
app.add_exception_handler(DocumentTooLarge, mongodb_document_too_large_handler)
app.add_exception_handler(InvalidOperation, mongodb_invalid_operation_handler)
app.add_exception_handler(ConfigurationError, mongodb_configuration_error_handler)
app.add_exception_handler(OperationFailure, mongodb_operation_failure_handler)
app.add_exception_handler(PyMongoError, mongodb_generic_error_handler)
app.add_exception_handler(Exception, general_exception_handler)

app.include_router(v1_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
