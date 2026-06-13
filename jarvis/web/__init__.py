"""Web / PWA front-end for JARVIS.

Wraps the same provider-agnostic `Assistant` used by the terminal CLI in an
HTTP API and serves an installable Progressive Web App, so JARVIS can be driven
from a phone browser while the real brain (Ollama, shell, files) runs on your
own machine.
"""

from .server import create_app

__all__ = ["create_app"]
