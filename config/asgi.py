"""ASGI entry point — this is the one the project actually runs under.

    venv\\Scripts\\python.exe -m daphne -b 127.0.0.1 -p 8000 config.asgi:application

`manage.py runserver` serves the WSGI path, which has no protocol router, so the
websocket routes simply do not exist under it. Anything touching the Twilio media
stream or a live-call surface must go through this module.

`websocket_urlpatterns` is empty until Module 3 (Call Runtime) adds
`apps/runtime/routing.py`. The Channels URLRouter is first-match-wins, so when
routes are added here a greedy `<str:token>` pattern must be checked against the
whole concatenated list, not just its own file.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# The Django ASGI application is instantiated FIRST so the app registry is
# populated before any consumer module is imported.
django_asgi_application = get_asgi_application()

from django.conf import settings  # noqa: E402
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

# Serving /static/ in development is a `runserver` convenience that ASGI does NOT
# inherit: `get_asgi_application()` contains no staticfiles handler, so under
# Daphne every stylesheet and script 404s and the whole site renders as unstyled
# HTML — with no error anywhere, because a 404 on a <link> is silent. Since this
# project forbids `runserver` outright (the media stream is a websocket), the
# handler has to be wired in explicitly here.
#
# DEBUG only. In production a real web server or WhiteNoise serves the collected
# static files, and this wrapper must not be in the path.
http_application = (
    ASGIStaticFilesHandler(django_asgi_application)
    if settings.DEBUG
    else django_asgi_application
)

websocket_urlpatterns = []

application = ProtocolTypeRouter(
    {
        'http': http_application,
        'websocket': AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns)),
    }
)
