from slowapi import Limiter
from slowapi.util import get_remote_address

# uses client IP address as the key for rate limiting
limiter = Limiter(key_func=get_remote_address)