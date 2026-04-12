"""
Request ID Middleware
Adds X-Request-ID header to every response and makes it available globally.
"""
import uuid
import threading
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Thread-local storage for request_id
_thread_local = threading.local()


def get_request_id():
    """Get the current request ID from thread-local storage."""
    return getattr(_thread_local, 'request_id', None)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        
        # Store in thread-local (accessible from anywhere in this thread)
        _thread_local.request_id = request_id
        
        # Also store in request state
        request.state.request_id = request_id
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        
        # Clean up
        delattr(_thread_local, 'request_id')
        
        return response