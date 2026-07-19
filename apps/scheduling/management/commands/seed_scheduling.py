"""Seed demo calendar and booking data.

Idempotent by design — safe to run repeatedly without `--flush`.

    venv\\Scripts\\python.exe manage.py seed_scheduling
    venv\\Scripts\\python.exe manage.py seed_scheduling --flush

Runs on top of `seed_tenants` (which creates the Acme and Globex businesses and
two locations each) and `seed_accounts` (which creates their users). Neither
tenant nor location rows are invented here — they are looked up by the slugs
those seeders use, so this command fails loudly rather than quietly building a
second demo universe.

This seeder touches no provider of any kind.

Sub-modules seeded so far:

* 4.1  Contact — a directory per tenant, spanning all three `source` values and
       including a deliberately shared phone line.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.scheduling.models import Contact
from apps.scheduling.services import normalize_e164
from apps.tenants.models import Tenant

# Contacts per tenant slug. The shapes here are chosen to exercise the module's
# real edge cases rather than to look tidy:
#
# * an anonymous caller with a number and no name at all (what the agent creates
#   the instant an unknown number rings),
# * two people sharing one phone line, so the "also on this number" panel and
#   the duplicate-warning path have something to show,
# * a contact with no number but an email (a web enquiry),
# * mixed `source` values so the source filter has more than one bucket.
DEMO_CONTACTS = {
    'acme': [
        {
            'first_name': 'Dana', 'last_name': 'Whitfield',
            'phone_e164': '+13125550101', 'email': 'dana.whitfield@example.test',
            'date_of_birth': '1984-03-22',
            'source': Contact.SOURCE_MANUAL,
            'notes': 'Prefers morning appointments. Parks in the Adams St garage.',
        },
        {
            'first_name': 'Marcus', 'last_name': 'Whitfield',
            # Deliberately the same line as Dana — a household on one number.
            'phone_e164': '+13125550101', 'email': '',
            'date_of_birth': '1981-11-09',
            'source': Contact.SOURCE_AI_PHONE,
            'notes': 'Shares a line with Dana. Confirm which one is calling.',
        },
        {
            'first_name': 'Priya', 'last_name': 'Raman',
            'phone_e164': '3125550188', 'email': 'priya.raman@example.test',
            'date_of_birth': None,
            'source': Contact.SOURCE_WEB,
            # Typed without a country code on purpose: proves normalize_e164
            # runs on the seeder's writes too, not just on the form's.
            'notes': 'Booked through the website contact form.',
        },
        {
            'first_name': '', 'last_name': '',
            'phone_e164': '+13125550990', 'email': '',
            'date_of_birth': None,
            'source': Contact.SOURCE_AI_PHONE,
            'notes': 'Rang after hours and hung up before giving a name.',
        },
        {
            'first_name': 'Owen', 'last_name': 'Baptiste',
            'phone_e164': '', 'email': 'owen.baptiste@example.test',
            'date_of_birth': '1996-07-14',
            'source': Contact.SOURCE_WEB,
            'notes': 'Email-only enquiry — no number on file yet.',
        },
    ],
    'globex': [
        {
            'first_name': 'Helena', 'last_name': 'Ostrom',
            'phone_e164': '+15035550210', 'email': 'helena.ostrom@example.test',
            'date_of_birth': '1972-01-30',
            'source': Contact.SOURCE_MANUAL,
            'notes': 'Usually visits Riverside but has booked at Lakeside too.',
        },
        {
            'first_name': 'Theo', 'last_name': 'Nakamura',
            'phone_e164': '+13035550311', 'email': 'theo.nakamura@example.test',
            'date_of_birth': None,
            'source': Contact.SOURCE_AI_PHONE,
            'notes': 'Denver number, books at Lakeside.',
        },
        {
            'first_name': '', 'last_name': '',
            'phone_e164': '+15035550777', 'email': '',
            'date_of_birth': None,
            'source': Contact.SOURCE_AI_PHONE,
            'notes': 'Unknown caller — agent had not asked a name before the '
                     'call ended.',
        },
    ],
}


class Command(BaseCommand):
    help = 'Seed demo contacts for the calendar and bookings module. Idempotent.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--flush',
            action='store_true',
            help='Delete this module\'s demo rows for the demo tenants before '
                 're-seeding.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        slugs = list(DEMO_CONTACTS)
        tenants = {t.slug: t for t in Tenant.objects.filter(slug__in=slugs)}

        missing = [slug for slug in slugs if slug not in tenants]
        if missing:
            self.stderr.write(self.style.ERROR(
                f'Missing demo tenant(s): {", ".join(missing)}. '
                'Run `manage.py seed_tenants` first.'
            ))
            return

        if options['flush']:
            deleted, _ = Contact.objects.filter(
                tenant__slug__in=slugs
            ).delete()
            self.stdout.write(self.style.WARNING(
                f'Flushed {deleted} demo contact row(s).'
            ))

        created = 0
        skipped = 0

        for slug, specs in DEMO_CONTACTS.items():
            tenant = tenants[slug]
            for spec in specs:
                spec = dict(spec)
                # `get_or_create` cannot key on phone alone: the Whitfields share
                # a line by design, and the two anonymous callers share a blank
                # name. Key on the whole identifying triple instead, which is
                # what makes a second run a no-op rather than a duplicate.
                #
                # The number MUST be normalised before the lookup. `Contact.save`
                # normalises on write, so a spec carrying a national-format number
                # is stored as +1… and a lookup on the raw spec value would match
                # nothing — re-creating that row on every single run.
                lookup = {
                    'tenant': tenant,
                    'first_name': spec['first_name'],
                    'last_name': spec['last_name'],
                    'phone_e164': normalize_e164(spec['phone_e164']),
                }
                if Contact.objects.filter(**lookup).exists():
                    skipped += 1
                    continue
                Contact.objects.create(tenant=tenant, **spec)
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Contacts: {created} created, {skipped} already present.'
        ))

        if skipped and not created:
            self.stdout.write(
                'Nothing to do. Use --flush to rebuild the demo directory.'
            )

        self.stdout.write('')
        self.stdout.write('Sign in as a TENANT ADMIN to see this data:')
        for slug, tenant in sorted(tenants.items()):
            self.stdout.write(
                f'  {tenant.name}  (customer id {tenant.customer_id})  '
                f'-> admin_{slug}'
            )
        self.stdout.write(
            '  Password for every demo account: navai-demo-2026'
        )
        self.stdout.write(self.style.WARNING(
            "  Superuser 'admin' has no tenant — data won't appear when logged "
            'in as admin.'
        ))
        self.stdout.write(
            '  Contacts are business-wide, so they are visible from EITHER '
            'location — that is correct, not a scoping bug.'
        )
