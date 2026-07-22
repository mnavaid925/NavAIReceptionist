"""``manage.py simulate_call`` — drive one full fake call through the real path.

3.2's observable surface (a service sub-module still ships one — ``voice-agent-
runtime`` §15). It opens a ``WebsocketCommunicator`` against the *real*
``config.asgi.application``, mints a genuine stream token exactly as 3.1's webhook
does, sends Twilio-shaped ``connected`` / ``start`` / ``media`` / ``stop`` frames
(a short synthetic caller utterance), and prints the ``CallSession`` the consumer
finalized — transcript, event log, per-turn usage, terminal status and timestamps.

It exercises the whole consumer + audio + VAD + turn-loop + provider-adapter path
end to end with **zero real credentials and no carrier**: it runs only under a
non-``live`` ``PROVIDER_MODE`` and refuses ``live`` outright. It never touches the
telephony redirect/TwiML helpers — only the websocket path — so it places no call.

    venv\\Scripts\\python.exe manage.py simulate_call
    venv\\Scripts\\python.exe manage.py simulate_call --tenant acme --location downtown
"""
import asyncio
import base64
import json
import math
import struct
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.agents.models import AgentSetting
from apps.calls.models import CallSession
from apps.runtime.providers.audio import (
    CARRIER_SAMPLE_RATE,
    CARRIER_FRAME_BYTES,
    pcm16_to_mulaw,
)
from apps.runtime.providers.base import active_mode
from apps.runtime.providers.tokens import mint_stream_token

_TONE_HZ = 200
_TONE_AMPLITUDE = 8000
#: 300 ms of speech clears VAD_MIN_SPEECH_MS; 900 ms of silence clears
#: VAD_END_SILENCE_MS, so the synthetic utterance actually endpoints.
_SPEECH_FRAMES = 15
_SILENCE_FRAMES = 45


def _speech_payload():
    """One 20 ms 8 kHz μ-law frame of a tone loud enough to read as speech."""
    step = 2 * math.pi * _TONE_HZ / CARRIER_SAMPLE_RATE
    pcm = struct.pack(
        '<%dh' % CARRIER_FRAME_BYTES,
        *(int(_TONE_AMPLITUDE * math.sin(step * n)) for n in range(CARRIER_FRAME_BYTES)),
    )
    return base64.b64encode(pcm16_to_mulaw(pcm)).decode('ascii')


def _silence_payload():
    """One 20 ms 8 kHz μ-law frame of silence."""
    pcm = b'\x00\x00' * CARRIER_FRAME_BYTES
    return base64.b64encode(pcm16_to_mulaw(pcm)).decode('ascii')


class Command(BaseCommand):
    help = 'Drive one fake inbound call through the real media-stream consumer.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Tenant slug or customer_id (optional).')
        parser.add_argument('--location', help='Location slug (optional).')

    def handle(self, *args, **options):
        mode = active_mode()
        if mode == 'live':
            raise CommandError(
                'simulate_call refuses to run under PROVIDER_MODE=live — it drives '
                'a synthetic call and must never touch a real provider. Run it with '
                'PROVIDER_MODE=fake.'
            )

        setting = self._resolve_setting(options.get('tenant'), options.get('location'))
        session = CallSession.objects.create(
            provider_call_sid=f'SIM-{uuid.uuid4().hex[:24]}',
            tenant=setting.tenant,
            location=setting.location,
            from_number='+15005550006',
            to_number=setting.inbound_phone_number or '+15005550001',
            status=CallSession.STATUS_IN_PROGRESS,
            mode=setting.voice_provider,
            started_at=timezone.now(),
        )
        token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

        self.stdout.write(
            f'Simulating a call at {setting.location} '
            f'(tenant={setting.tenant}, mode={mode})…'
        )
        asyncio.run(self._run(session, token))

        session.refresh_from_db()
        self._report(session)

    def _resolve_setting(self, tenant_hint, location_hint):
        qs = AgentSetting.objects.select_related('tenant', 'location').filter(
            enabled=True, inbound_phone_number__isnull=False)
        if tenant_hint:
            qs = qs.filter(tenant__slug=tenant_hint) | qs.filter(
                tenant__customer_id=tenant_hint)
        if location_hint:
            qs = qs.filter(location__slug=location_hint)
        setting = qs.first()
        if setting is None:
            raise CommandError(
                'No enabled AgentSetting with an inbound number found'
                + (' for the given --tenant/--location.' if (tenant_hint or location_hint)
                   else ' — seed one (seed_agents) or enable a location first.')
            )
        return setting

    def _origin_header(self):
        """A valid Origin for the ASGI app's AllowedHostsOriginValidator.

        The validator rejects a websocket with no Origin (or a disallowed one), so
        even this local diagnostic must present one that matches
        ``settings.ALLOWED_HOSTS``.
        """
        from django.conf import settings
        hosts = [h for h in settings.ALLOWED_HOSTS if h and h != '*']
        if '*' in settings.ALLOWED_HOSTS or 'localhost' in hosts or not hosts:
            host = 'localhost'
        else:
            host = hosts[0].lstrip('.')
        return [(b'origin', f'http://{host}'.encode('latin1'))]

    async def _run(self, session, token):
        # Imported here so a plain `manage.py` import of this module does not pull
        # in the ASGI app and Channels before they are needed.
        from channels.testing import WebsocketCommunicator

        from config.asgi import application

        communicator = WebsocketCommunicator(
            application, '/ws/media-stream/', headers=self._origin_header())
        connected, _ = await communicator.connect()
        if not connected:
            raise CommandError('The media-stream consumer refused the connection.')

        stream_sid = f'MZ{uuid.uuid4().hex[:30]}'
        await communicator.send_json_to({'event': 'connected', 'protocol': 'Call',
                                         'version': '1.0.0'})
        await communicator.send_json_to({
            'event': 'start',
            'streamSid': stream_sid,
            'start': {
                'streamSid': stream_sid,
                'callSid': session.provider_call_sid,
                'customParameters': {'streamToken': token,
                                     'sessionId': str(session.pk)},
            },
        })

        # Let the deterministic greeting play out (paced outbound frames) before
        # the caller "speaks", so it is not swallowed by the echo guard.
        await self._drain(communicator)

        # One synthetic caller utterance: speech then silence to endpoint it.
        for _ in range(_SPEECH_FRAMES):
            await communicator.send_json_to(
                {'event': 'media', 'media': {'payload': _speech_payload()}})
        for _ in range(_SILENCE_FRAMES):
            await communicator.send_json_to(
                {'event': 'media', 'media': {'payload': _silence_payload()}})

        # Let the reply turn run and play back.
        await self._drain(communicator)

        await communicator.send_json_to({'event': 'stop'})
        await communicator.disconnect()

    async def _drain(self, communicator, quiet=0.6, cap=2000):
        """Read outbound frames until the wire goes quiet for ``quiet`` seconds."""
        received = 0
        while received < cap:
            if await communicator.receive_nothing(timeout=quiet):
                return received
            await communicator.receive_from()
            received += 1
        return received

    def _report(self, session):
        self.stdout.write(self.style.SUCCESS(
            f'\nCallSession {session.provider_call_sid} — status={session.status}'))
        self.stdout.write(f'  started_at : {session.started_at}')
        self.stdout.write(f'  ended_at   : {session.ended_at}')
        self.stdout.write(f'  duration   : {session.duration_display}')
        self.stdout.write(f'  total cost : ${session.total_cost_usd}')

        transcript = session.transcript or []
        self.stdout.write(f'\n  transcript ({len(transcript)} turns):')
        for turn in transcript:
            self.stdout.write(f"    [{turn.get('role')}] {turn.get('text')}")

        usage = session.usage or []
        self.stdout.write(f'\n  usage ({len(usage)} turns): '
                          + json.dumps(usage, indent=2))
        logs = session.logs or []
        self.stdout.write(f'\n  logs ({len(logs)} events):')
        for entry in logs:
            self.stdout.write(
                f"    {entry.get('level')}/{entry.get('category')}: {entry.get('title')}")

        if session.status == CallSession.STATUS_IN_PROGRESS:
            raise CommandError(
                'The session is still in_progress after the call — the consumer '
                'did not finalize it. That is a real defect, not a warning.'
            )
