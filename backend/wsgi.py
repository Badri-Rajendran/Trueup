"""WSGI entrypoint. The only place the application object is constructed for serving."""

from __future__ import annotations

from app import create_app

app = create_app()
