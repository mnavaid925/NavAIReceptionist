"""`agents.AgentSetting` — everything one location's voice agent needs.

ONE row per location, carrying three field groups that three sub-modules edit
separately: the agent configuration (2.1), the Twilio connection (2.2) and the
transfer settings (2.3). They are one table rather than three because a call
needs all of it at once, resolved from a single lookup on the dialed number.

TWO CONSTRAINTS DO REAL WORK HERE.

`unique (tenant, location)` — a location with two agent rows would answer
differently depending on which one a query happened to return first.

`inbound_phone_number` unique **globally, across every tenant** — this is the
routing key. An inbound webhook has no session and no `request.tenant`; it
resolves both from the number that was dialed:

    setting = AgentSetting.objects.get(inbound_phone_number=to_number)

Two businesses owning the same DID would make that lookup ambiguous, which is a
cross-tenant data leak, so the database refuses it. The column is nullable rather
than blank-defaulted because NULLs are distinct in a unique index while empty
strings are not — several locations may have no number yet, but no two may share
one.
"""
from apps.agents.fields import EncryptedCharField, mask_secret
from apps.agents.models._base import *  # noqa: F401,F403

__all__ = ['AgentSetting']


class AgentSetting(TenantLocationOwned):  # noqa: F405
    """One location's agent, telephony and transfer configuration."""

    VOICE_LIVE = 'live'
    VOICE_GOOGLE = 'google'
    VOICE_GEMINI = 'gemini'
    VOICE_PROVIDER_CHOICES = [
        (VOICE_LIVE, 'Live (realtime speech)'),
        (VOICE_GOOGLE, 'Google'),
        (VOICE_GEMINI, 'Gemini'),
    ]

    # -- 2.1 Agent configuration ------------------------------------------ #

    enabled = models.BooleanField(  # noqa: F405
        default=False,
        help_text='The master switch for this location. While off, the agent does '
                  'not answer.',
    )
    voice_provider = models.CharField(  # noqa: F405
        max_length=16,
        choices=VOICE_PROVIDER_CHOICES,
        default=VOICE_LIVE,
    )
    greeting = models.TextField(  # noqa: F405
        blank=True,
        help_text='Spoken the moment the call connects. Rendered server-side from '
                  'this text and costs zero LLM tokens, so the caller hears '
                  'something immediately.',
    )
    prompt_text = models.TextField(  # noqa: F405
        blank=True,
        help_text='The system prompt for this location. Supports {{variable}} '
                  'placeholders.',
    )
    variables = models.JSONField(  # noqa: F405
        default=dict,
        blank=True,
        help_text='The {{variable}} substitution map, merged with server-computed '
                  'runtime values at call setup. Runtime values win on a clash.',
    )

    # -- 2.2 Twilio connection -------------------------------------------- #

    inbound_phone_number = models.CharField(  # noqa: F405
        max_length=32,
        null=True,
        blank=True,
        unique=True,
        help_text='E.164, e.g. +13125550142. Globally unique across all '
                  'businesses — it is what routes an inbound call to this location.',
    )
    twilio_account_sid = models.CharField(max_length=64, blank=True)  # noqa: F405
    twilio_auth_token = EncryptedCharField(
        blank=True,
        default='',
        help_text='Encrypted at rest and write-only in forms. Never rendered, '
                  'never logged, never returned by a view.',
    )

    # -- 2.3 Transfer settings -------------------------------------------- #

    transfer_enabled = models.BooleanField(default=False)  # noqa: F405
    transfer_phone_number = models.CharField(max_length=32, blank=True)  # noqa: F405
    transfer_secondary_number = models.CharField(  # noqa: F405
        max_length=32,
        blank=True,
        help_text='A second destination, e.g. another language or an overflow line.',
    )
    transfer_timezone = models.CharField(  # noqa: F405
        max_length=100,
        default='America/Chicago',
        help_text='The timezone the transfer windows below are evaluated in.',
    )
    transfer_working_hours = models.JSONField(  # noqa: F405
        default=dict,
        blank=True,
        help_text='{"monday": {"enabled": true, "start": "09:00", "end": "17:00"}, ...}. '
                  'Empty means no restriction.',
    )
    transfer_keywords = models.JSONField(  # noqa: F405
        default=list,
        blank=True,
        help_text='Extra lowercased caller phrases that trigger a handoff. These '
                  'are ADDED to the runtime built-in set, not a replacement for it.',
    )

    class Meta:
        ordering = ['location__name']
        constraints = [
            models.UniqueConstraint(  # noqa: F405
                fields=['tenant', 'location'], name='uniq_agentsetting_tenant_location'
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'enabled'],  # noqa: F405
                        name='idx_agentsetting_enabled'),
        ]
        verbose_name = 'Agent setting'

    def __str__(self):
        return f'Agent for {self.location}'

    # -- normalisation ----------------------------------------------------- #

    def clean(self):
        super().clean()
        # '' would defeat the global unique index — several locations legitimately
        # have no number yet, and empty strings collide where NULLs do not.
        self.inbound_phone_number = (self.inbound_phone_number or '').strip() or None

    def save(self, *args, **kwargs):
        # Mirrors clean() so a seeder, a shell or an import cannot bypass the
        # normalisation the unique index depends on.
        self.inbound_phone_number = (self.inbound_phone_number or '').strip() or None
        return super().save(*args, **kwargs)

    # -- credential state (never the value) -------------------------------- #

    @property
    def has_auth_token(self):
        """Whether a token is stored. The value itself is never exposed."""
        return bool(self.twilio_auth_token)

    @property
    def masked_auth_token(self):
        """A safe-to-render hint, e.g. `••••••••3f2a`. Shows only the tail."""
        return mask_secret(self.twilio_auth_token)

    @property
    def twilio_connected(self):
        """Both halves of the Twilio credential are present."""
        return bool(self.twilio_account_sid and self.twilio_auth_token)

    # -- readiness --------------------------------------------------------- #

    @property
    def is_ready(self):
        """True when this location could actually take a live call."""
        return not self.readiness_issues()

    def readiness_issues(self):
        """Everything blocking this location from answering, in fixing order.

        Used by the setup page and by the test-call view, so the same answer is
        given wherever it is asked.
        """
        issues = []
        if not self.greeting.strip():
            issues.append('No greeting — the caller would hear silence on answer.')
        if not self.prompt_text.strip():
            issues.append('No system prompt — the agent has no instructions.')
        if not self.inbound_phone_number:
            issues.append('No inbound number — no call can reach this location.')
        if not self.twilio_account_sid:
            issues.append('No Twilio account SID.')
        if not self.twilio_auth_token:
            issues.append('No Twilio auth token.')
        if self.transfer_enabled and not self.transfer_phone_number:
            issues.append(
                'Transfer is enabled but no destination number is set — the agent '
                'would promise a handoff it cannot make.'
            )
        return issues
