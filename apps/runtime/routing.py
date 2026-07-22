"""Channels websocket routes for Module 3 — flat at the app root, never a package.

3.2 mounts the carrier media stream. Twilio's cloud opens ``wss://…/ws/media-stream/``
(the URL 3.1's ``media_stream_ws_url()`` names in its connect TwiML); the consumer
authorizes it from the signed ``<Parameter>`` token in the ``start`` frame, never
from anything in this URL — the route carries no identity segment on purpose.

ORDER IS BEHAVIOUR across the whole concatenated ``URLRouter`` list, not just this
file. This is the only websocket route today, but a later sub-module's staff
live-call surface adds another; a greedy ``<str:token>`` segment on either must be
checked against every pattern the project mounts, first-match-wins — the same rule
``urls/__init__.py`` obeys for HTTP.
"""
from django.urls import path

from apps.runtime.consumers import MediaStreamConsumer

websocket_urlpatterns = [
    path('ws/media-stream/', MediaStreamConsumer.as_asgi()),
]
