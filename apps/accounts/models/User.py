"""`accounts.User` — AUTH_USER_MODEL — and its manager.

Login is **customer id + email-or-username + password**: the tenant is resolved
from `Tenant.customer_id` BEFORE authentication, which is what lets the same email
address exist in more than one business. See `apps.accounts.backends`.

Two deliberate deviations from `NavAIReceptionist-ERD.md` §3.1, both recorded in
that document:

1. **`last_login`, not `last_login_at`.** `AbstractBaseUser` already contributes
   `last_login`, and Django's `update_last_login` signal receiver and
   `PasswordResetTokenGenerator._make_hash_value` both read it by that name.
   Renaming it would mean removing the inherited field, disconnecting a built-in
   signal receiver and subclassing the token generator — three permanent pieces of
   framework-fighting for a cosmetic difference. The inherited field is used.

2. **`is_active` is a property over `status`, not a column.** Django's auth and
   admin machinery expect a truthy `is_active`; `status` is the domain field. A
   second stored column would be a second source of truth that a view could desync.
"""
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin

from apps.accounts.models._base import *  # noqa: F401,F403

__all__ = ['User', 'UserManager']


class UserManager(BaseUserManager):
    """Creates tenant users and the tenant-less superuser.

    NOTE — `use_in_migrations` must stay False here, and the reason is structural.
    Setting it True makes Django serialise this manager into the migration by its
    import path, `apps.accounts.models.User.UserManager`. But the mandated backend
    layout names the entity module after its model, so `apps.accounts.models.User`
    resolves to the re-exported User *class*, not the `User.py` *module* — and the
    attribute lookup fails with `type object 'User' has no attribute 'UserManager'`
    the moment any migration is loaded. The same trap waits on every `<Entity>.py`
    in this project. Data migrations that need this manager should import it inside
    the migration function instead.
    """

    use_in_migrations = False

    def _create(self, email, password, **extra):
        if not email:
            raise ValueError('A user must have an email address.')
        email = self.normalize_email(email)
        # An empty username must be stored as NULL, never '': the unique index
        # over (tenant, username) treats NULLs as distinct but '' as a real
        # colliding value, so a blank string here would let exactly one user per
        # tenant exist without a username.
        if not extra.get('username'):
            extra['username'] = None
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.full_clean(exclude=['password'])
        user.save(using=self._db)
        return user

    def create_user(self, tenant, email, password=None, **extra):
        extra.setdefault('tier', User.TIER_STAFF)
        extra.setdefault('status', User.STATUS_ACTIVE)
        extra.setdefault('is_staff', False)
        extra.setdefault('is_superuser', False)
        return self._create(email, password, tenant=tenant, **extra)

    def create_superuser(self, email, password=None, **extra):
        """The platform superuser. Deliberately has NO tenant.

        Because every module view filters by `tenant=request.tenant`, a superuser
        sees no module data — that is BY DESIGN, not a bug. Log in as a tenant
        admin (`admin_<slug>`) to see seeded data.
        """
        extra['tenant'] = None
        extra['is_staff'] = True
        extra['is_superuser'] = True
        extra.setdefault('tier', User.TIER_OWNER)
        extra.setdefault('status', User.STATUS_ACTIVE)
        return self._create(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, TimeStamped):  # noqa: F405
    """A person who signs in to a business's NavAIReceptionist workspace."""

    TIER_OWNER = 'owner'
    TIER_MANAGER = 'manager'
    TIER_STAFF = 'staff'
    TIER_CHOICES = [
        (TIER_OWNER, 'Owner'),
        (TIER_MANAGER, 'Manager'),
        (TIER_STAFF, 'Staff'),
    ]

    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_SUSPENDED = 'suspended'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
        (STATUS_SUSPENDED, 'Suspended'),
    ]

    # Nullable ONLY for the platform superuser — every real user has a tenant.
    # This is why `User` declares its own FK instead of inheriting `TenantOwned`,
    # whose `tenant` is non-nullable.
    tenant = models.ForeignKey(  # noqa: F405
        'tenants.Tenant',
        null=True,
        blank=True,
        on_delete=models.CASCADE,  # noqa: F405
        related_name='users',
        help_text='Null only for the platform superuser.',
    )

    email = models.EmailField(max_length=254)  # noqa: F405
    username = models.CharField(  # noqa: F405
        max_length=150,
        null=True,
        blank=True,
        help_text='Optional login handle. Stored as NULL when unset, never as an '
                  'empty string — the unique index depends on it.',
    )

    first_name = models.CharField(max_length=128, blank=True)  # noqa: F405
    last_name = models.CharField(max_length=128, blank=True)  # noqa: F405
    full_name = models.CharField(  # noqa: F405
        max_length=255,
        blank=True,
        help_text='Canonical display label. Derived from first/last when left blank.',
    )
    primary_phone = models.CharField(max_length=32, blank=True)  # noqa: F405

    tier = models.CharField(max_length=16, choices=TIER_CHOICES, default=TIER_STAFF)  # noqa: F405
    status = models.CharField(  # noqa: F405
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True,
        help_text='Deactivate rather than delete, so historical appointments keep '
                  'a valid provider reference.',
    )

    is_provider = models.BooleanField(
        default=False,
        help_text='A provider IS the bookable clinician — there is no separate '
                  'Provider entity.',
    )
    provider_hours = models.JSONField(  # noqa: F405
        default=dict,
        blank=True,
        help_text='Weekly working hours KEYED BY LOCATION ID, because the same '
                  'person can work different days at different sites: '
                  '{"<location_id>": [{"start_time": "09:00", "end_time": "17:00", '
                  '"days": ["mon", "tue"]}]}',
    )

    inactivity_timeout = models.PositiveIntegerField(  # noqa: F405
        null=True,
        blank=True,
        help_text='Minutes of inactivity before the session is ended. Falls back '
                  'to settings.DEFAULT_INACTIVITY_TIMEOUT_MINUTES when unset.',
    )

    # Django admin access. Not a domain tier — `tier` is the product's role field.
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ['email']
        constraints = [
            models.UniqueConstraint(  # noqa: F405
                fields=['tenant', 'email'], name='uniq_user_tenant_email'
            ),
            # The ERD asks for uniqueness on (tenant, username) "where username is
            # not null". A PLAIN unique constraint already means exactly that: every
            # SQL engine this project targets treats NULLs as distinct inside a
            # unique index, so any number of users may have no username while two
            # users in one tenant may not share one. A filtered
            # UniqueConstraint(condition=...) would be worse than useless here —
            # MySQL has no partial indexes, so Django silently skips it and the rule
            # ends up unenforced.
            models.UniqueConstraint(  # noqa: F405
                fields=['tenant', 'username'], name='uniq_user_tenant_username'
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'status'], name='idx_user_tenant_status'),  # noqa: F405
        ]

    def __str__(self):
        return self.display_name

    # -- normalisation ----------------------------------------------------- #

    def clean(self):
        super().clean()
        self.email = UserManager.normalize_email(self.email or '').strip()
        # '' would defeat the (tenant, username) unique index — see the field help.
        self.username = (self.username or '').strip() or None
        if not self.full_name:
            self.full_name = f'{self.first_name} {self.last_name}'.strip()

    def save(self, *args, **kwargs):
        # Mirrors clean() so a programmatic save (a seeder, a shell, an import)
        # cannot bypass the normalisation the unique index relies on.
        self.username = (self.username or '').strip() or None
        if not self.full_name:
            self.full_name = f'{self.first_name} {self.last_name}'.strip()
        return super().save(*args, **kwargs)

    # -- auth surface ------------------------------------------------------ #

    @property
    def is_active(self):
        """Django's auth and admin machinery read this; `status` is the truth."""
        return self.status == self.STATUS_ACTIVE

    # -- display ----------------------------------------------------------- #

    @property
    def display_name(self):
        """The label shown in the topbar and anywhere a user is named."""
        return self.full_name or self.get_username() or self.email

    @property
    def initials(self):
        """Two-letter initials for `.avatar-initial`."""
        parts = [part for part in (self.display_name or '').split() if part]
        if not parts:
            return '?'
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()

    # -- locations --------------------------------------------------------- #

    def assigned_locations(self):
        """The locations this user may switch into.

        This queryset IS the authorization boundary the active-location switcher
        validates against — never a list built from a form field or a URL kwarg.
        """
        from apps.tenants.models import Location

        if self.tenant_id is None:
            return Location.objects.none()
        return Location.objects.filter(
            tenant_id=self.tenant_id,
            user_assignments__user=self,
        ).distinct()

    @property
    def effective_inactivity_timeout(self):
        """Minutes of idle time this user's session tolerates."""
        from django.conf import settings as django_settings

        return self.inactivity_timeout or django_settings.DEFAULT_INACTIVITY_TIMEOUT_MINUTES
