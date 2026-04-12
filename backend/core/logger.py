"""
Structured logging with structlog.
Supports JSON format for CloudWatch and console format for development.
"""
import structlog
import sys
import logging
import logging.config
import json
from datetime import datetime

from backend.core.config import settings


def setup_logging():
    """Configure structured logging"""
    
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        timestamper,
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    
    if getattr(settings, 'LOG_FORMAT', 'json') == "json":
        structlog.configure(
            processors=shared_processors + [
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            wrapper_class=structlog.BoundLogger,
            cache_logger_on_first_use=True,
        )
    else:
        structlog.configure(
            processors=shared_processors + [
                structlog.dev.ConsoleRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            wrapper_class=structlog.BoundLogger,
            cache_logger_on_first_use=True,
        )
    
    # Configure Uvicorn loggers
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": _UvicornJSONFormatter,
            },
        },
        "handlers": {
            "default": {
                "formatter": "json",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
            "access": {
                "formatter": "json",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }
    
    logging.config.dictConfig(log_config)


class _UvicornJSONFormatter(logging.Formatter):
    """Format Uvicorn logs as JSON with request_id from thread-local"""
    def format(self, record):
        log_obj = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        
        # Get request_id from thread-local storage
        try:
            from backend.middleware.request_id import get_request_id
            req_id = get_request_id()
            if req_id:
                log_obj["request_id"] = req_id
        except:
            pass
        
        return json.dumps(log_obj)


def get_logger(name: str = None):
    """Get structured logger instance"""
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(module=name)
    return logger


# Setup on import
setup_logging()