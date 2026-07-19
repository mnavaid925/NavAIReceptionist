"""Seed demo users and their location assignments.

Idempotent — safe to run repeatedly without `--flush`. Depends on `seed_tenants`
having run first; it is invoked automatically when no demo tenant exists yet.

    venv\\Scripts\\python.exe manage.py seed_accounts
    venv\\Scripts\\python.exe manage.py seed_accounts --flush

Each demo tenant gets a full-access owner assigned to BOTH of its locations, plus
a single-location manager. That second account is the important one: it is what
makes cross-location leakage testable, because a bug that shows Uptown's data to a
Downtown-only user is invisible when every demo user can see everything.

This seeder touches no provider of any kind.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import User, UserLocation
from apps.tenants.models import Location, Tenant
from apps.tenants.services import has_configured_hours, set_provider_hours

# One shared password for every demo account. Long enough to satisfy the
# configured AUTH_PASSWORD_VALIDATORS; obviously not a production secret.
DEMO_PASSWORD = 'navai-demo-2026'

SUPERUSER_EMAIL = 'admin@navai.local'

DEMO_USERS = [
    {
        'tenant_slug': 'acme',
        'users': [
            {
                'email': 'admin@acme.test',
                'username': 'admin_acme',
                'first_name': 'Ada',
                'last_name': 'Okafor',
                'tier': User.TIER_OWNER,
                'is_provider': False,
                'primary_phone': '+13125550101',
                # Both sites — the full-access account.
                'locations': ['downtown', 'uptown'],
            },
            {
                'email': 'downtown.manager@acme.test',
                'username': 'acme_downtown',
                'first_name': 'Marco',
                'last_name': 'Reyes',
                'tier': User.TIER_MANAGER,
                'is_provider': True,
                'primary_phone': '+13125550102',
                # Deliberately ONE site — the cross-location isolation probe.
                'locations': ['downtown'],
            },
            {
                # Added for Module 4: without a provider at Uptown, availability
                # search returns nothing there forever and the calendar's
                # by-provider view has a single column. Kept OFF Downtown so
                # Marco stays the single-site isolation probe.
                'email': 'uptown.provider@acme.test',
                'username': 'acme_uptown',
                'first_name': 'Sofia',
                'last_name': 'Lindqvist',
                'tier': User.TIER_STAFF,
                'is_provider': True,
                'primary_phone': '+13125550103',
                'locations': ['uptown'],
            },
        ],
    },
    {
        'tenant_slug': 'globex',
        'users': [
            {
                'email': 'admin@globex.test',
                'username': 'admin_globex',
                'first_name': 'Priya',
                'last_name': 'Raman',
                'tier': User.TIER_OWNER,
                'is_provider': False,
                'primary_phone': '+15035550101',
                'locations': ['riverside', 'lakeside'],
            },
            {
                'email': 'riverside.staff@globex.test',
                'username': 'globex_riverside',
                'first_name': 'Tom',
                'last_name': 'Bergstrom',
                'tier': User.TIER_STAFF,
                'is_provider': True,
                'primary_phone': '+15035550102',
                'locations': ['riverside'],
            },
            {
                # Same reasoning as Sofia — Lakeside needs its own provider.
                'email': 'lakeside.provider@globex.test',
                'username': 'globex_lakeside',
                'first_name': 'Ines',
                'last_name': 'Duarte',
                'tier': User.TIER_STAFF,
                'is_provider': True,
                'primary_phone': '+13035550103',
                'locations': ['lakeside'],
            },
        ],
    },
]

#: Working hours stamped on every seeded provider, per location.
#:
#: WITHOUT THIS the availability engine finds nothing. `get_provider_intervals`
#: documents that no configured hours means UNAVAILABLE — never "available all
#: day" — so a provider seeded with `is_provider=True` and an empty
#: `provider_hours` is a provider nobody can ever book. That combination is not a
#: neutral default; it is a broken one.
DEMO_PROVIDER_HOURS = [
    {'start_time': '09:00', 'end_time': '13:00',
     'days': ['mon', 'tue', 'wed', 'thu', 'fri']},
    {'start_time': '14:00', 'end_time': '17:30',
     'days': ['mon', 'tue', 'wed', 'thu', 'fri']},
]


class Command(BaseCommand):
    help = 'Seed demo users and UserLocation assignments. Idempotent.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--flush',
            action='store_true',
            help='Delete the demo users before re-seeding.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        tenant_slugs = [spec['tenant_slug'] for spec in DEMO_USERS]

        if not Tenant.objects.filter(slug__in=tenant_slugs).exists():
            self.stdout.write(self.style.WARNING(
                'No demo businesses found — running seed_tenants first.'
            ))
            call_command('seed_tenants')

        if options['flush']:
            emails = [u['email'] for spec in DEMO_USERS for u in spec['users']]
            deleted, _ = User.objects.filter(email__in=emails).delete()
            self.stdout.write(self.style.WARNING(f'Flushed {deleted} demo row(s).'))

        created_users = 0
        created_assignments = 0
        stamped_hours = 0

        # The platform superuser. No tenant, by design.
        superuser = User.objects.filter(email=SUPERUSER_EMAIL).first()
        if superuser is None:
            User.objects.create_superuser(email=SUPERUSER_EMAIL, password=DEMO_PASSWORD)
            created_users += 1

        for spec in DEMO_USERS:
            tenant = Tenant.objects.filter(slug=spec['tenant_slug']).first()
            if tenant is None:
                self.stdout.write(self.style.ERROR(
                    f"Tenant '{spec['tenant_slug']}' is missing — run seed_tenants."
                ))
                continue

            for user_spec in spec['users']:
                location_slugs = user_spec.pop('locations')

                user = User.objects.filter(tenant=tenant, email=user_spec['email']).first()
                if user is None:
                    user = User.objects.create_user(
                        tenant=tenant, password=DEMO_PASSWORD, **user_spec
                    )
                    created_users += 1

                # Restore the popped key so a second pass over DEMO_USERS in the
                # same process still has it.
                user_spec['locations'] = location_slugs

                for slug in location_slugs:
                    location = Location.objects.filter(tenant=tenant, slug=slug).first()
                    if location is None:
                        continue
                    _, made = UserLocation.objects.get_or_create(
                        user=user, location=location, defaults={'tenant': tenant}
                    )
                    created_assignments += int(made)

                    # Stamp working hours for every provider at every site they
                    # work. Only when unset, so a demo edited through the 1.4
                    # Working Hours page survives a re-seed.
                    if user.is_provider and not has_configured_hours(user, location.pk):
                        set_provider_hours(
                            user, location.pk, DEMO_PROVIDER_HOURS, commit=True
                        )
                        stamped_hours += 1

        if created_users or created_assignments or stamped_hours:
            self.stdout.write(self.style.SUCCESS(
                f'Seeded {created_users} user(s), {created_assignments} '
                f'assignment(s) and working hours for {stamped_hours} '
                'provider-location pair(s).'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                'Data already exists. Use --flush to re-seed.'
            ))

        self._report()

    def _report(self):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Demo sign-in details'))
        self.stdout.write(f'  Password for every demo account: {DEMO_PASSWORD}')
        self.stdout.write('')

        for spec in DEMO_USERS:
            tenant = Tenant.objects.filter(slug=spec['tenant_slug']).first()
            if tenant is None:
                continue
            self.stdout.write(f'  {tenant.name}  —  Customer ID: {tenant.customer_id}')
            for user_spec in spec['users']:
                user = User.objects.filter(tenant=tenant, email=user_spec['email']).first()
                if user is None:
                    continue
                names = ', '.join(
                    location.name for location in user.assigned_locations()
                ) or 'none'
                self.stdout.write(
                    f'    {user.email}  (or username {user.username})  '
                    f'[{user.get_tier_display()}]'
                )
                self.stdout.write(f'      can switch into: {names}')
            self.stdout.write('')

        self.stdout.write(self.style.WARNING(
            "Superuser 'admin' has no tenant — data won't appear when logged in as admin. "
            f'Sign in at /admin/ with {SUPERUSER_EMAIL}.'
        ))
        self.stdout.write(
            'Sign in to the product at /login/ with a Customer ID above, then the '
            'email or username, then the password.'
        )
