import os
import logging
import sys
from typing import Any, Dict
from pythonjsonlogger import jsonlogger
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(
        self,
        log_record: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = datetime.now(timezone.utc).isoformat()
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["module"] = record.module
        log_record["function"] = record.funcName
        log_record["line"] = record.lineno

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)


def setup_logger(name: str = "app", level: str = None) -> logging.Logger:
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    formatter = CustomJsonFormatter(
        "%(timestamp)s %(level)s %(name)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False

    return logger


def get_logger(name: str = None) -> logging.Logger:
    if name:
        return logging.getLogger(f"app.{name}")
    return logging.getLogger("app")
