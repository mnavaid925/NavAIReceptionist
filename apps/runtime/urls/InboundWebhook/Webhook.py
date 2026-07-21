"""The inbound Twilio voice webhook route.

Mounted at ``voice/`` under the app's ``runtime/`` prefix, so the public path is
``/runtime/voice/`` — the exact URL Module 2's live test call already hardcodes
(``apps/agents/telephony.py``), and the URL a real Twilio number's Voice webhook
must be pointed at. The handler is the flat ``apps/runtime/webhooks.py`` module,
not a view package, because it answers a carrier, not a signed-in user.
"""
from django.urls import path

from apps.runtime import webhooks

__all__ = ['urlpatterns']

urlpatterns = [
    path('voice/', webhooks.voice_webhook, name='voice_webhook'),
]
