"""Seed demo businesses and their locations.

Idempotent by design — safe to run repeatedly without `--flush`. Every demo tenant
gets TWO locations in different timezones, because a single-location demo tenant
hides every cross-location scoping bug in the product.

    venv\\Scripts\\python.exe manage.py seed_tenants
    venv\\Scripts\\python.exe manage.py seed_tenants --flush

This seeder touches no provider of any kind. `seed_accounts` builds the users and
their location assignments on top of these rows.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.tenants.models import Location, Tenant

# The demo dataset. Two tenants, two locations each, deliberately in different
# timezones so a location-scoped bug shows up as a wrong wall-clock time.
DEMO_TENANTS = [
    {
        'slug': 'acme',
        'name': 'Acme Dental Group',
        'customer_id': 'ACME-1001',
        'timezone': 'America/Chicago',
        'locations': [
            {
                'slug': 'downtown',
                'name': 'Acme Downtown',
                'address_line1': '410 W Adams St',
                'city': 'Chicago',
                'state': 'IL',
                'postal_code': '60606',
                'timezone': 'America/Chicago',
                'phone': '+13125550142',
            },
            {
                'slug': 'uptown',
                'name': 'Acme Uptown',
                'address_line1': '1155 N Broadway',
                'city': 'Chicago',
                'state': 'IL',
                'postal_code': '60640',
                'timezone': 'America/Chicago',
                'phone': '+13125550188',
            },
        ],
    },
    {
        'slug': 'globex',
        'name': 'Globex Health',
        'customer_id': 'GLBX-2002',
        'timezone': 'America/Los_Angeles',
        'locations': [
            {
                'slug': 'riverside',
                'name': 'Globex Riverside',
                'address_line1': '88 Riverside Dr',
                'city': 'Portland',
                'state': 'OR',
                'postal_code': '97209',
                'timezone': 'America/Los_Angeles',
                'phone': '+15035550119',
            },
            {
                'slug': 'lakeside',
                'name': 'Globex Lakeside',
                'address_line1': '2400 Lakeside Ave',
                'city': 'Denver',
                'state': 'CO',
                'postal_code': '80202',
                'timezone': 'America/Denver',
                'phone': '+13035550173',
            },
        ],
    },
]


class Command(BaseCommand):
    help = 'Seed demo businesses (tenants) and their locations. Idempotent.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--flush',
            action='store_true',
            help='Delete the demo tenants (and everything cascading from them) '
                 'before re-seeding.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        slugs = [spec['slug'] for spec in DEMO_TENANTS]

        if options['flush']:
            deleted, _ = Tenant.objects.filter(slug__in=slugs).delete()
            self.stdout.write(self.style.WARNING(
                f'Flushed {deleted} demo row(s) across the tenant cascade.'
            ))

        created_tenants = 0
        created_locations = 0

        for spec in DEMO_TENANTS:
            tenant, tenant_created = Tenant.objects.get_or_create(
                slug=spec['slug'],
                defaults={
                    'name': spec['name'],
                    'customer_id': spec['customer_id'],
                    'timezone': spec['timezone'],
                    'is_active': True,
                },
            )
            created_tenants += int(tenant_created)

            for loc_spec in spec['locations']:
                _, loc_created = Location.objects.get_or_create(
                    tenant=tenant,
                    slug=loc_spec['slug'],
                    defaults={**loc_spec, 'is_active': True},
                )
                created_locations += int(loc_created)

        if created_tenants or created_locations:
            self.stdout.write(self.style.SUCCESS(
                f'Seeded {created_tenants} tenant(s) and {created_locations} location(s).'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                'Data already exists. Use --flush to re-seed.'
            ))

        self._report(slugs)

    def _report(self, slugs):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Demo businesses'))
        for tenant in Tenant.objects.filter(slug__in=slugs).prefetch_related('locations'):
            self.stdout.write(f'  {tenant.name}  (Customer ID: {tenant.customer_id})')
            for location in tenant.locations.all():
                self.stdout.write(
                    f'    - {location.name}  [{location.timezone}]'
                )
        self.stdout.write('')
        self.stdout.write(
            'Run `manage.py seed_accounts` next — it creates the users and their '
            'location assignments on top of these businesses.'
        )
        self.stdout.write(self.style.WARNING(
            "Superuser 'admin' has no tenant — data won't appear when logged in as admin."
        ))
