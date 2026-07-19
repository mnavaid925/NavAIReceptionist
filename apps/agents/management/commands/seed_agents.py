"""Seed one AgentSetting per demo location.

Idempotent — safe to run repeatedly without `--flush`.

    venv\\Scripts\\python.exe manage.py seed_agents

NO REAL PROVIDER IS TOUCHED. The Twilio SIDs and tokens below are obviously fake
strings, and `PROVIDER_MODE` stays `fake`, so the telephony backend resolves to
the fake implementation which cannot reach a carrier. A seeder that could place a
real call is a defect, not a configuration choice.

The inbound numbers are distinct across every seeded location because the column
is globally unique — that is what lets an inbound webhook resolve the tenant and
location from the dialled number alone.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.agents.models import AgentSetting
from apps.tenants.models import Location, Tenant

DEMO_PASSWORD_NOTE = 'These credentials are fake and reach nothing.'

GREETING = (
    "Thanks for calling {{business_name}}, {{location_name}}. "
    "You're through to our virtual receptionist — how can I help?"
)

PROMPT = """You are the virtual receptionist for {{business_name}} at {{location_name}}.

Today is {{current_date}} and the local time is {{current_time}}.

You can check availability and book, reschedule or cancel an appointment. Ask for
the caller's name and a contact number before booking. Confirm the date and time
back to the caller before you finalise anything.

If the caller asks for a person, offer to put them through. Transfer availability
right now is: {{transfer_available}}.

Be brief and warm. Never invent an availability slot, a price or a policy — if you
do not know, say so and offer to take a message.
"""

DEMO_SETTINGS = {
    'acme': {
        'downtown': {
            'inbound_phone_number': '+13125550140',
            'twilio_account_sid': 'ACfake0000000000000000000000000001',
            'twilio_auth_token': 'fake-token-downtown-0000000000001',
            'enabled': True,
            'transfer_enabled': True,
            'transfer_phone_number': '+13125550101',
            'transfer_secondary_number': '+13125550102',
            'transfer_timezone': 'America/Chicago',
            'variables': {'parking': 'There is street parking on Adams.'},
            'keywords': ['front desk', 'receptionist'],
            'business_hours': True,
        },
        'uptown': {
            'inbound_phone_number': '+13125550141',
            'twilio_account_sid': 'ACfake0000000000000000000000000002',
            'twilio_auth_token': 'fake-token-uptown-00000000000001',
            'enabled': True,
            'transfer_enabled': False,
            'transfer_phone_number': '',
            'transfer_secondary_number': '',
            'transfer_timezone': 'America/Chicago',
            'variables': {},
            'keywords': [],
            'business_hours': False,
        },
    },
    'globex': {
        'riverside': {
            'inbound_phone_number': '+15035550150',
            'twilio_account_sid': 'ACfake0000000000000000000000000003',
            'twilio_auth_token': 'fake-token-riverside-000000000001',
            'enabled': True,
            'transfer_enabled': True,
            'transfer_phone_number': '+15035550101',
            'transfer_secondary_number': '',
            'transfer_timezone': 'America/Los_Angeles',
            'variables': {},
            'keywords': ['nurse'],
            'business_hours': True,
        },
        'lakeside': {
            # Deliberately NOT configured — an unconfigured location is what the
            # readiness check and the "not configured" surfaces need to exercise.
            'inbound_phone_number': '',
            'twilio_account_sid': '',
            'twilio_auth_token': '',
            'enabled': False,
            'transfer_enabled': False,
            'transfer_phone_number': '',
            'transfer_secondary_number': '',
            'transfer_timezone': 'America/Denver',
            'variables': {},
            'keywords': [],
            'business_hours': False,
        },
    },
}

WEEKDAY_HOURS = {
    'monday': {'enabled': True, 'start': '09:00', 'end': '17:00'},
    'tuesday': {'enabled': True, 'start': '09:00', 'end': '17:00'},
    'wednesday': {'enabled': True, 'start': '09:00', 'end': '17:00'},
    'thursday': {'enabled': True, 'start': '09:00', 'end': '17:00'},
    'friday': {'enabled': True, 'start': '09:00', 'end': '16:00'},
    'saturday': {'enabled': False, 'start': '', 'end': ''},
    'sunday': {'enabled': False, 'start': '', 'end': ''},
}


class Command(BaseCommand):
    help = 'Seed one AgentSetting per demo location. Idempotent.'

    def add_arguments(self, parser):
        parser.add_argument('--flush', action='store_true',
                            help='Delete the demo agent settings before re-seeding.')

    @transaction.atomic
    def handle(self, *args, **options):
        if not Tenant.objects.filter(slug__in=DEMO_SETTINGS).exists():
            self.stdout.write(self.style.WARNING(
                'No demo businesses found — running seed_accounts first.'
            ))
            call_command('seed_accounts')

        if options['flush']:
            deleted, _ = AgentSetting.objects.filter(
                tenant__slug__in=DEMO_SETTINGS
            ).delete()
            self.stdout.write(self.style.WARNING(f'Flushed {deleted} row(s).'))

        created = 0
        for tenant_slug, locations in DEMO_SETTINGS.items():
            tenant = Tenant.objects.filter(slug=tenant_slug).first()
            if tenant is None:
                continue

            for location_slug, spec in locations.items():
                location = Location.objects.filter(
                    tenant=tenant, slug=location_slug
                ).first()
                if location is None:
                    continue

                if AgentSetting.objects.filter(tenant=tenant, location=location).exists():
                    continue

                AgentSetting.objects.create(
                    tenant=tenant,
                    location=location,
                    enabled=spec['enabled'],
                    greeting=GREETING if spec['enabled'] else '',
                    prompt_text=PROMPT if spec['enabled'] else '',
                    variables=spec['variables'],
                    inbound_phone_number=spec['inbound_phone_number'] or None,
                    twilio_account_sid=spec['twilio_account_sid'],
                    twilio_auth_token=spec['twilio_auth_token'],
                    transfer_enabled=spec['transfer_enabled'],
                    transfer_phone_number=spec['transfer_phone_number'],
                    transfer_secondary_number=spec['transfer_secondary_number'],
                    transfer_timezone=spec['transfer_timezone'],
                    transfer_working_hours=dict(WEEKDAY_HOURS) if spec['business_hours'] else {},
                    transfer_keywords=spec['keywords'],
                )
                created += 1

        if created:
            self.stdout.write(self.style.SUCCESS(f'Seeded {created} agent setting(s).'))
        else:
            self.stdout.write(self.style.WARNING(
                'Data already exists. Use --flush to re-seed.'
            ))

        self._report()

    def _report(self):
        from django.conf import settings

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Demo agents'))
        for setting in AgentSetting.objects.select_related('tenant', 'location'):
            state = 'enabled' if setting.enabled else 'disabled'
            number = setting.inbound_phone_number or 'no number'
            self.stdout.write(
                f'  {setting.location.name:22} {state:9} {number}'
            )
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            f'PROVIDER_MODE={settings.PROVIDER_MODE} — the Twilio credentials above '
            'are fake and reach nothing. No call can be placed.'
        ))
