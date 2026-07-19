"""The telephony control seam for Module 2 — connection check (2.2), test call (2.4).

**This module is the only place in Module 2 that could ever reach a carrier**, so
the safety rules live here rather than being repeated at each call site:

1. `PROVIDER_MODE` selects the backend. `fake` is the default for dev, tests and
   seeders.
2. `FakeTelephonyBackend` **cannot** reach a provider — it does not import
   `twilio` and opens no socket. That is structural, not a policy it follows.
3. `LiveTelephonyBackend` **refuses to initialise** unless
   `PROVIDER_MODE == 'live'`, and live mode additionally requires real
   credentials. Missing credentials in live mode is the hard failure.

A path that can place a real call from a test, a seeder or a dev context is a
Critical defect, not a configuration choice — hence the belt-and-braces guard in
both `get_backend()` and the live backend's own `__init__`.

**Module 3 handoff.** When `apps/runtime/providers/telephony.py` exists it becomes
the real implementation and this module delegates to it. `get_backend()` already
import-guards for it, so THE CALL SITES IN VIEWS DO NOT CHANGE — the same pattern
already used by `tenants.views.Location._agent_setting_for` and
`tenants.views._helpers.future_appointment_count`.
"""
import logging
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)

__all__ = [
    'TelephonyResult',
    'FakeTelephonyBackend',
    'LiveTelephonyBackend',
    'get_backend',
    'check_connection',
    'place_test_call',
]


@dataclass
class TelephonyResult:
    """The outcome of a connection check or a test call.

    Never carries a credential. `detail` is rendered to the user, so anything
    placed in it is effectively public.
    """

    ok: bool
    summary: str
    detail: str = ''
    mode: str = 'fake'
    simulated: bool = True
    data: dict = field(default_factory=dict)


class BaseTelephonyBackend:
    mode = 'fake'
    simulated = True

    def check_connection(self, setting):  # pragma: no cover - interface
        raise NotImplementedError

    def place_test_call(self, setting, destination):  # pragma: no cover - interface
        raise NotImplementedError


class FakeTelephonyBackend(BaseTelephonyBackend):
    """Simulates the provider. Reaches nothing.

    Note what is deliberately absent: no `import twilio`, no `httpx`, no socket.
    The safety property is that this class COULD NOT call a carrier even if a bug
    invoked it in production, rather than that it chooses not to.
    """

    mode = 'fake'
    simulated = True

    def check_connection(self, setting):
        missing = []
        if not setting.twilio_account_sid:
            missing.append('account SID')
        if not setting.twilio_auth_token:
            missing.append('auth token')
        if not setting.inbound_phone_number:
            missing.append('inbound number')

        if missing:
            return TelephonyResult(
                ok=False,
                summary='Not connected',
                detail='Missing: ' + ', '.join(missing) + '.',
                mode=self.mode,
            )

        if not setting.twilio_account_sid.startswith('AC'):
            return TelephonyResult(
                ok=False,
                summary='Not connected',
                detail='A Twilio account SID starts with "AC".',
                mode=self.mode,
            )

        return TelephonyResult(
            ok=True,
            summary='Credentials look valid (simulated)',
            detail='PROVIDER_MODE is not "live", so nothing was sent to Twilio. '
                   'The shape of the credentials was checked locally.',
            mode=self.mode,
            data={'account_sid': setting.twilio_account_sid,
                  'number': setting.inbound_phone_number},
        )

    def place_test_call(self, setting, destination):
        return TelephonyResult(
            ok=True,
            summary='Test call simulated',
            detail=f'In live mode this would ring {destination} from '
                   f'{setting.inbound_phone_number}. PROVIDER_MODE is '
                   f'"{settings.PROVIDER_MODE}", so no call was placed and nothing '
                   'was billed.',
            mode=self.mode,
            data={'destination': destination,
                  'from': setting.inbound_phone_number},
        )


class LiveTelephonyBackend(BaseTelephonyBackend):
    """Talks to the real carrier. Guarded on every side."""

    mode = 'live'
    simulated = False

    def __init__(self):
        # Checked in __init__ rather than per method, so an instance cannot exist
        # in a non-live process at all.
        if settings.PROVIDER_MODE != 'live':
            raise RuntimeError(
                'LiveTelephonyBackend refuses to initialise while PROVIDER_MODE is '
                f'"{settings.PROVIDER_MODE}". This guard is what stops a test, a '
                'seeder or a dev run from placing a real call.'
            )

    def _client(self, setting):
        if not (setting.twilio_account_sid and setting.twilio_auth_token):
            # In live mode, absent credentials are a hard failure — never a
            # silent fall back to the fake path.
            raise RuntimeError('Live mode requires real Twilio credentials.')
        from twilio.rest import Client

        return Client(setting.twilio_account_sid, setting.twilio_auth_token)

    def check_connection(self, setting):
        try:
            client = self._client(setting)
            account = client.api.accounts(setting.twilio_account_sid).fetch()
            numbers = client.incoming_phone_numbers.list(
                phone_number=setting.inbound_phone_number, limit=1
            )
        except Exception as exc:
            # Never echo the provider's exception text — it can carry the SID and
            # request bodies. Log the type only.
            logger.error('Twilio connection check failed: %s', type(exc).__name__)
            return TelephonyResult(
                ok=False, summary='Connection failed',
                detail='Twilio rejected the credentials or could not be reached.',
                mode=self.mode, simulated=False,
            )

        if not numbers:
            return TelephonyResult(
                ok=False, summary='Number not owned by this account',
                detail='The account is valid, but that number is not on it.',
                mode=self.mode, simulated=False,
            )
        return TelephonyResult(
            ok=True, summary='Connected',
            detail=f'Account "{account.friendly_name}" owns this number.',
            mode=self.mode, simulated=False,
        )

    def place_test_call(self, setting, destination):
        try:
            client = self._client(setting)
            call = client.calls.create(
                to=destination,
                from_=setting.inbound_phone_number,
                url=f'{settings.TWILIO_WEBHOOK_BASE_URL}/runtime/voice/',
            )
        except Exception as exc:
            logger.error('Twilio test call failed: %s', type(exc).__name__)
            return TelephonyResult(
                ok=False, summary='Test call failed',
                detail='Twilio would not place the call.',
                mode=self.mode, simulated=False,
            )
        return TelephonyResult(
            ok=True, summary='Test call placed',
            detail=f'Ringing {destination} now.',
            mode=self.mode, simulated=False,
            data={'sid': call.sid},
        )


def get_backend():
    """The backend for the current `PROVIDER_MODE`.

    Prefers Module 3's adapter once it exists; otherwise uses Module 2's own.
    Anything that is not exactly 'live' resolves to the fake — an unrecognised
    mode must fail SAFE, never toward the carrier.
    """
    try:
        from apps.runtime.providers.telephony import get_backend as runtime_backend
    except (ImportError, ModuleNotFoundError):
        pass
    else:
        return runtime_backend()

    if settings.PROVIDER_MODE == 'live':
        return LiveTelephonyBackend()
    return FakeTelephonyBackend()


def check_connection(setting):
    """Verify credentials and number ownership. Places no call."""
    return get_backend().check_connection(setting)


def place_test_call(setting, destination):
    """Ring `destination` so the tenant can hear their own agent.

    `destination` is resolved SERVER-SIDE by the caller from the signed-in user's
    own profile — it is never accepted from a form field. An arbitrary
    caller-supplied destination would make this endpoint a toll-fraud gadget:
    authenticated users could dial premium-rate numbers on the tenant's account.
    """
    if not destination:
        return TelephonyResult(
            ok=False, summary='No destination',
            detail='Add a phone number to your profile to receive the test call.',
            mode=settings.PROVIDER_MODE,
        )
    return get_backend().place_test_call(setting, destination)
