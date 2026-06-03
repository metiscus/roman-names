import sys
from pathlib import Path

# Ensure the project root is on the path when Passenger loads this file
sys.path.insert(0, str(Path(__file__).parent.parent))

from a2wsgi import ASGIMiddleware
from server.main import app as _asgi_app

# Passenger expects a module-level `application` variable
application = ASGIMiddleware(_asgi_app)
