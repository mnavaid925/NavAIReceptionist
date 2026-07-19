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
* 4.2  Service, Resource — a catalogue mixing all-location and site-specific
       services, and rooms at BOTH locations of each tenant so a cross-location
       bug has somewhere to show up.
* 4.3  Appointment — bookings at every demo location spanning all five statuses,
       anchored to deterministic days so a re-run matches instead of duplicating.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from datetime import datetime, time as dt_time, timedelta

from django.db.models import Q

from apps.accounts.models import User
from apps.scheduling.availability import _local_naive_to_utc
from apps.scheduling.models import Contact, Resource, Service
from apps.scheduling.services import normalize_e164
from apps.tenants.models import Location, Tenant

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


# -- 4.2 Services ----------------------------------------------------------- #
# `location_slug=None` means the service is offered at EVERY site — the common
# case, and the one a naive `filter(location=...)` would wrongly hide.
DEMO_SERVICES = {
    'acme': [
        {'name': 'Routine check-up', 'location_slug': None,
         'duration_minutes': 30, 'buffer_minutes': 10, 'requires_resource': True,
         'display_order': 10,
         'description': 'A standard examination and clean, about half an hour.'},
        {'name': 'Emergency appointment', 'location_slug': None,
         'duration_minutes': 20, 'buffer_minutes': 10, 'requires_resource': True,
         'display_order': 20,
         'description': 'Same-day slot for pain or a broken tooth.'},
        {'name': 'Teeth whitening', 'location_slug': 'downtown',
         'duration_minutes': 60, 'buffer_minutes': 15, 'requires_resource': True,
         'display_order': 30,
         'description': 'Cosmetic whitening, about an hour. Downtown only.'},
        {'name': 'Phone consultation', 'location_slug': None,
         'duration_minutes': 15, 'buffer_minutes': 0, 'requires_resource': False,
         'display_order': 40,
         'description': 'A quick call with a dentist. No room needed.'},
        {'name': 'Orthodontic review', 'location_slug': 'uptown',
         'duration_minutes': 45, 'buffer_minutes': 15, 'requires_resource': True,
         'display_order': 50, 'is_active': False,
         'description': 'Brace adjustment and review. Uptown only.'},
    ],
    'globex': [
        {'name': 'New patient assessment', 'location_slug': None,
         'duration_minutes': 45, 'buffer_minutes': 15, 'requires_resource': True,
         'display_order': 10,
         'description': 'First visit, including a full history.'},
        {'name': 'Follow-up', 'location_slug': None,
         'duration_minutes': 20, 'buffer_minutes': 5, 'requires_resource': True,
         'display_order': 20,
         'description': 'A shorter review after a previous visit.'},
        {'name': 'Telehealth call', 'location_slug': None,
         'duration_minutes': 20, 'buffer_minutes': 0, 'requires_resource': False,
         'display_order': 30,
         'description': 'A video or phone appointment. No room needed.'},
        {'name': 'Physiotherapy session', 'location_slug': 'riverside',
         'duration_minutes': 50, 'buffer_minutes': 10, 'requires_resource': True,
         'display_order': 40,
         'description': 'Hands-on session in the Riverside gym.'},
    ],
}

# -- 4.2 Resources ---------------------------------------------------------- #
# Keyed by location slug, NOT by tenant: a resource is physically at one site.
# Both locations of both tenants get rooms, so a cross-location scoping bug shows
# up as the wrong site's rooms appearing rather than as an empty page.
DEMO_RESOURCES = {
    'downtown': [
        {'name': 'Surgery 1', 'resource_number': '1', 'display_order': 10,
         'description': 'Ground floor, wheelchair accessible.'},
        {'name': 'Surgery 2', 'resource_number': '2', 'display_order': 20,
         'description': 'First floor.'},
        {'name': 'Hygienist room', 'resource_number': 'H', 'display_order': 30,
         'description': ''},
    ],
    'uptown': [
        # Same name as a Downtown room on purpose — the unique constraint is
        # (location, name), so this must be allowed.
        {'name': 'Surgery 1', 'resource_number': '1', 'display_order': 10,
         'description': 'Shares a name with the Downtown room. That is allowed.'},
        {'name': 'Consult room', 'resource_number': 'C', 'display_order': 20,
         'description': ''},
        {'name': 'Spare chair', 'resource_number': 'X', 'display_order': 30,
         'description': 'Out of service pending repair.', 'is_active': False},
    ],
    'riverside': [
        {'name': 'Consult room A', 'resource_number': 'A', 'display_order': 10,
         'description': ''},
        {'name': 'Physio gym', 'resource_number': 'G', 'display_order': 20,
         'description': 'Large room with equipment.'},
    ],
    'lakeside': [
        {'name': 'Consult room A', 'resource_number': 'A', 'display_order': 10,
         'description': ''},
        {'name': 'Consult room B', 'resource_number': 'B', 'display_order': 20,
         'description': ''},
    ],
}


# -- 4.3 Appointments -------------------------------------------------------- #
#
# `day_offset` is counted from the LOCATION's local today, and `hour`/`minute`
# are LOCAL wall-clock times converted through `Location.tzinfo`. Both matter for
# idempotency: a `now()`-derived start never matches on a second run and would
# duplicate every appointment, every time (Seed Rule 1). The `(location, contact,
# start_at)` triple is the dedupe key, so a fixed offset+hour reproduces exactly.
#
# Statuses deliberately span all five so every branch of the shared badge partial
# has a row, and the cancelled one proves a cancelled slot is genuinely re-bookable.
DEMO_APPOINTMENTS = {
    'downtown': [
        {'contact': ('Dana', 'Whitfield'), 'service': 'Routine check-up',
         'resource': 'Surgery 1', 'day_offset': 1, 'hour': 9, 'minute': 0,
         'status': 'scheduled', 'source': 'ai_phone',
         'reason': 'Six-month check-up'},
        {'contact': ('Marcus', 'Whitfield'), 'service': 'Emergency appointment',
         'resource': 'Surgery 2', 'day_offset': 1, 'hour': 10, 'minute': 30,
         'status': 'confirmed', 'source': 'ai_phone',
         'reason': 'Broken filling, in pain'},
        {'contact': ('Priya', 'Raman'), 'service': 'Teeth whitening',
         'resource': 'Surgery 1', 'day_offset': 2, 'hour': 14, 'minute': 0,
         'status': 'scheduled', 'source': 'web', 'reason': 'Whitening'},
        {'contact': ('Owen', 'Baptiste'), 'service': 'Phone consultation',
         'resource': None, 'day_offset': 2, 'hour': 11, 'minute': 0,
         'status': 'scheduled', 'source': 'manual',
         'reason': 'Wants to discuss options first'},
        {'contact': ('Dana', 'Whitfield'), 'service': 'Routine check-up',
         'resource': 'Surgery 1', 'day_offset': -14, 'hour': 9, 'minute': 30,
         'status': 'completed', 'source': 'manual', 'reason': 'Previous visit'},
        {'contact': ('Marcus', 'Whitfield'), 'service': 'Routine check-up',
         'resource': 'Surgery 2', 'day_offset': -7, 'hour': 15, 'minute': 0,
         'status': 'no_show', 'source': 'ai_phone', 'reason': 'Did not attend'},
        {'contact': ('Priya', 'Raman'), 'service': 'Routine check-up',
         'resource': 'Surgery 1', 'day_offset': 3, 'hour': 9, 'minute': 0,
         'status': 'cancelled', 'source': 'ai_phone',
         'reason': 'Called to cancel',
         'cancellation_reason': 'Caller rearranged around work'},
    ],
    'uptown': [
        {'contact': ('Dana', 'Whitfield'), 'service': 'Orthodontic review',
         'resource': 'Surgery 1', 'day_offset': 1, 'hour': 9, 'minute': 30,
         'status': 'scheduled', 'source': 'manual',
         'reason': 'Brace adjustment'},
        {'contact': ('Owen', 'Baptiste'), 'service': 'Routine check-up',
         'resource': 'Consult room', 'day_offset': 2, 'hour': 15, 'minute': 0,
         'status': 'confirmed', 'source': 'ai_phone', 'reason': 'Check-up'},
    ],
    'riverside': [
        {'contact': ('Helena', 'Ostrom'), 'service': 'New patient assessment',
         'resource': 'Consult room A', 'day_offset': 1, 'hour': 9, 'minute': 0,
         'status': 'scheduled', 'source': 'ai_phone', 'reason': 'First visit'},
        {'contact': ('Theo', 'Nakamura'), 'service': 'Physiotherapy session',
         'resource': 'Physio gym', 'day_offset': 2, 'hour': 10, 'minute': 0,
         'status': 'confirmed', 'source': 'manual', 'reason': 'Knee rehab'},
        {'contact': ('Helena', 'Ostrom'), 'service': 'Telehealth call',
         'resource': None, 'day_offset': 3, 'hour': 16, 'minute': 0,
         'status': 'scheduled', 'source': 'web', 'reason': 'Follow-up by phone'},
    ],
    'lakeside': [
        {'contact': ('Theo', 'Nakamura'), 'service': 'Follow-up',
         'resource': 'Consult room A', 'day_offset': 1, 'hour': 11, 'minute': 0,
         'status': 'scheduled', 'source': 'ai_phone', 'reason': 'Review'},
        {'contact': ('Helena', 'Ostrom'), 'service': 'New patient assessment',
         'resource': 'Consult room B', 'day_offset': 4, 'hour': 9, 'minute': 30,
         'status': 'scheduled', 'source': 'manual', 'reason': 'New to Lakeside'},
    ],
}


class Command(BaseCommand):
    help = ('Seed demo contacts, services, resources and appointments for the '
            'calendar and bookings module. Idempotent.')

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
            # ORDER MATTERS. `Appointment.contact` is PROTECT, so deleting
            # contacts while any booking still references them raises
            # ProtectedError and the whole flush rolls back. Children first,
            # parents after — appointments, then the catalogue, then contacts.
            from apps.scheduling.models import Appointment

            deleted, _ = Appointment.objects.filter(
                tenant__slug__in=slugs
            ).delete()
            self.stdout.write(self.style.WARNING(
                f'Flushed {deleted} demo appointment row(s).'
            ))
            deleted, _ = Resource.objects.filter(tenant__slug__in=slugs).delete()
            self.stdout.write(self.style.WARNING(
                f'Flushed {deleted} demo resource row(s).'
            ))
            deleted, _ = Service.objects.filter(tenant__slug__in=slugs).delete()
            self.stdout.write(self.style.WARNING(
                f'Flushed {deleted} demo service row(s).'
            ))
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

        self._seed_services(tenants)
        self._seed_resources(tenants)
        self._seed_appointments(tenants)

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
        self.stdout.write(
            '  Services with no location are offered everywhere; resources '
            'belong to ONE site, so switch location to see the other set.'
        )
        self.stdout.write(
            '  Appointments are location-scoped: each site has its own diary, '
            'and availability only offers slots where a provider has hours.'
        )

    def _seed_appointments(self, tenants):
        """Seed bookings at every demo location.

        Dedupe key is `(location, contact, start_at)`. `start_at` is derived from
        a FIXED day offset and local hour rather than from `now()`, which is what
        makes a second run a no-op: a `now()`-relative start would differ by
        milliseconds every time and duplicate the whole diary on every run.
        """
        from apps.scheduling.models import Appointment, Contact, Resource, Service

        created = 0
        skipped = 0
        unresolved = 0

        locations = {
            location.slug: location
            for location in Location.objects.filter(tenant__in=tenants.values())
            .select_related('tenant')
        }

        for location_slug, specs in DEMO_APPOINTMENTS.items():
            location = locations.get(location_slug)
            if location is None:
                continue
            tenant = location.tenant
            today_local = location.local_now().date()

            for spec in specs:
                first, last = spec['contact']
                contact = Contact.objects.filter(
                    tenant=tenant, first_name=first, last_name=last
                ).first()
                service = (
                    Service.objects.filter(tenant=tenant, name=spec['service'])
                    .filter(
                        Q(location=location) | Q(location__isnull=True)
                    ).first()
                )
                if contact is None or service is None:
                    unresolved += 1
                    continue

                resource = None
                if spec['resource']:
                    resource = Resource.objects.filter(
                        location=location, name=spec['resource']
                    ).first()

                # Local wall time -> UTC through THIS location's zone. A naive
                # `make_aware` against the server default would put a Denver
                # booking an hour out from a Chicago one.
                local_day = today_local + timedelta(days=spec['day_offset'])
                start_utc = _local_naive_to_utc(
                    datetime.combine(
                        local_day, dt_time(spec['hour'], spec['minute'])
                    ),
                    location.tzinfo,
                )
                if start_utc is None:
                    # The chosen wall time falls in a DST gap at this location.
                    unresolved += 1
                    continue

                if Appointment.objects.filter(
                    tenant=tenant, location=location, contact=contact,
                    start_at=start_utc,
                ).exists():
                    skipped += 1
                    continue

                provider = User.objects.filter(
                    tenant=tenant, is_provider=True,
                    user_locations__location=location,
                ).distinct().first()

                appointment = Appointment.objects.create(
                    tenant=tenant, location=location, contact=contact,
                    provider=provider, resource=resource, service=service,
                    start_at=start_utc,
                    end_at=start_utc + timedelta(
                        minutes=service.duration_minutes
                    ),
                    status=spec['status'], reason=spec.get('reason', ''),
                    source=spec['source'],
                )
                if spec['status'] == Appointment.STATUS_CANCELLED:
                    appointment.cancelled_at = start_utc - timedelta(days=1)
                    appointment.cancellation_reason = spec.get(
                        'cancellation_reason', ''
                    )
                    appointment.save(update_fields=[
                        'cancelled_at', 'cancellation_reason', 'updated_at',
                    ])
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Appointments: {created} created, {skipped} already present.'
        ))
        if unresolved:
            self.stdout.write(self.style.WARNING(
                f'  {unresolved} appointment(s) skipped — a contact, service or '
                'time could not be resolved at that location.'
            ))

    # -- 4.2 ---------------------------------------------------------------- #

    def _seed_services(self, tenants):
        """Seed the service catalogue.

        Keyed on `(tenant, location, name)` — the same tuple `ServiceForm`
        validates against — so a re-run is a no-op. Keying on name alone would
        collapse a Downtown-only service and an all-locations one that happen to
        share a name.
        """
        created = 0
        skipped = 0

        for slug, specs in DEMO_SERVICES.items():
            tenant = tenants[slug]
            for spec in specs:
                spec = dict(spec)
                location_slug = spec.pop('location_slug')
                location = None
                if location_slug:
                    location = Location.objects.filter(
                        tenant=tenant, slug=location_slug
                    ).first()
                    if location is None:
                        self.stderr.write(self.style.WARNING(
                            f'  Skipping service "{spec["name"]}" — no location '
                            f'"{location_slug}" for {tenant.slug}.'
                        ))
                        continue

                if Service.objects.filter(
                    tenant=tenant, location=location, name=spec['name']
                ).exists():
                    skipped += 1
                    continue

                Service.objects.create(tenant=tenant, location=location, **spec)
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Services: {created} created, {skipped} already present.'
        ))

    def _seed_resources(self, tenants):
        """Seed rooms and equipment, keyed by LOCATION slug.

        A resource belongs to one site, so the lookup is `(location, name)` —
        matching the model's unique constraint exactly. Downtown and Uptown both
        get a "Surgery 1" on purpose, to prove that constraint is scoped to the
        location and not to the tenant.
        """
        created = 0
        skipped = 0

        locations = {
            location.slug: location
            for location in Location.objects.filter(
                tenant__in=tenants.values()
            ).select_related('tenant')
        }

        for location_slug, specs in DEMO_RESOURCES.items():
            location = locations.get(location_slug)
            if location is None:
                self.stderr.write(self.style.WARNING(
                    f'  Skipping resources for "{location_slug}" — no such '
                    'location. Run `manage.py seed_tenants` first.'
                ))
                continue

            for spec in specs:
                if Resource.objects.filter(
                    location=location, name=spec['name']
                ).exists():
                    skipped += 1
                    continue
                Resource.objects.create(
                    tenant=location.tenant, location=location, **spec
                )
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Resources: {created} created, {skipped} already present.'
        ))
