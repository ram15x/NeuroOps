import structlog
import sys
from datetime import datetime
from typing import Any, Dict

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
    
    if settings.LOG_FORMAT == "json":
        # JSON format for production
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
        # Human-readable format for development
        structlog.configure(
            processors=shared_processors + [
                structlog.dev.ConsoleRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            wrapper_class=structlog.BoundLogger,
            cache_logger_on_first_use=True,
        )


def get_logger(name: str = None):
    """Get structured logger instance"""
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(module=name)
    return logger


# Setup on import
setup_logging()