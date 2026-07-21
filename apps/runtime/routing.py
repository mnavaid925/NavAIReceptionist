"""Channels websocket routes for Module 3 — flat at the app root, never a package.

**Empty in 3.1 by design.** 3.1 is the HTTP half of the call path: it answers the
Twilio voice webhook and returns the ``<Connect><Stream>`` TwiML. The
``wss://…/ws/media-stream/`` route the TwiML points at is added by **3.2** (the
media consumer), which is also when ``config/asgi.py`` wires this list into the
``ProtocolTypeRouter`` — there is no websocket route to serve until then, so 3.1
leaves both this list empty and ``asgi.py`` untouched.

ORDER IS BEHAVIOUR across the whole concatenated ``URLRouter`` list, not just this
file. When 3.2 adds the media-stream route, a greedy ``<str:token>`` segment must
be checked against every websocket pattern the project mounts, first-match-wins —
the same rule ``urls/__init__.py`` obeys for HTTP.
"""

websocket_urlpatterns = []
