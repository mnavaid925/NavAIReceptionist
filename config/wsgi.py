"""WSGI entry point.

Present for completeness and for tooling that expects it, but NOT how this project
is served: the Twilio media stream is a websocket, so the real entry point is
`config.asgi:application` under Daphne. A WSGI deployment silently loses every
realtime surface.
"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()
