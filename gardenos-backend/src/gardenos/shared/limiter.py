"""Rate limiting shared by every module.

Counters live in this process's memory (`memory://`): fine for a single server
process, but each worker would count separately and a restart resets everything.
When GardenOS runs several workers, point `storage_uri` at a shared store.
Behind a reverse proxy `get_remote_address` sees the proxy's IP, so deployment
must forward the real client IP (e.g. werkzeug's ProxyFix) or everyone shares one bucket.
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func = get_remote_address,
    storage_uri = "memory://",
    headers_enabled = True,  # X-RateLimit-* and Retry-After on responses
)
