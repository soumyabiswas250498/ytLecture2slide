import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "job_id": getattr(record, "job_id", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str, directory: Path) -> None:
    logger = logging.getLogger("app")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        RotatingFileHandler(directory / "app.log", maxBytes=5_000_000, backupCount=3),
    ]
    for handler in handlers:
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    # Prevent httpx/httpcore from logging request URLs containing API keys.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
