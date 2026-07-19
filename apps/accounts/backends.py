"""Authentication backend.

Login is **customer id + email-or-username + password**. The tenant is resolved
from `Tenant.customer_id` before any credential is checked, which is what allows
the same email address to exist in more than one business — `(tenant, email)` is
the unique pair, not `email` alone.

Every failure path returns `None`. The caller renders ONE message for all of them,
so a wrong customer id, an unknown user, a wrong password, an inactive tenant and a
suspended account are indistinguishable from outside.
"""
import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import check_password, make_password

from apps.accounts import throttling
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)

# Hashing a throwaway password costs the same as hashing a real one. Running it on
# the "no such user" path keeps the response time of a miss indistinguishable from
# the response time of a wrong password, closing the timing side channel that
# would otherwise re-open account enumeration.
_TIMING_EQUALISER = make_password('navai-timing-equaliser')


class CustomerScopedBackend(BaseBackend):
    """Resolve the tenant by customer id, then match email OR username within it."""

    def authenticate(self, request, customer_id=None, identifier=None, password=None,
                     username=None, **kwargs):
        User = get_user_model()

        # Django's admin login form posts `username`/`password` with no customer
        # id. Route that to the tenant-less staff accounts so /admin/ keeps working
        # without adding a second backend.
        if customer_id is None and identifier is None and username is not None:
            return self._authenticate_platform_staff(username, password)

        client_ip = _client_ip(request)
        keys = throttling.build_keys(customer_id, identifier, client_ip)

        # Checked BEFORE the credential comparison, so a throttled caller learns
        # nothing about whether the credentials were right.
        if throttling.is_throttled(keys):
            logger.warning('Login blocked by throttle for ip=%s', client_ip)
            return None

        user = self._lookup(User, customer_id, identifier)

        if user is None:
            # Spend the same time a real password check would, then count it.
            check_password(password or '', _TIMING_EQUALISER)
            throttling.register_failure(keys)
            return None

        if not user.check_password(password or ''):
            throttling.register_failure(keys)
            return None

        if not user.is_active:
            # A suspended or deactivated account fails exactly like a wrong
            # password — including counting against the throttle.
            throttling.register_failure(keys)
            return None

        throttling.clear(keys)
        return user

    def _lookup(self, User, customer_id, identifier):
        """Find the user, or None. Never raises, never distinguishes failures."""
        customer_id = (customer_id or '').strip()
        identifier = (identifier or '').strip()
        if not customer_id or not identifier:
            return None

        tenant = Tenant.objects.filter(
            customer_id__iexact=customer_id, is_active=True
        ).first()
        if tenant is None:
            # Covers both "no such business" and "business deactivated". An
            # inactive tenant is blocked here, at login, rather than mid-call.
            return None

        return (
            User.objects.filter(tenant=tenant)
            .filter(**{'email__iexact': identifier})
            .first()
            or User.objects.filter(tenant=tenant)
            .filter(**{'username__iexact': identifier})
            .first()
        )

    def _authenticate_platform_staff(self, username, password):
        """The /admin/ path: tenant-less staff only, never a tenant user."""
        User = get_user_model()
        user = User.objects.filter(
            tenant__isnull=True, is_staff=True, email__iexact=(username or '').strip()
        ).first()
        if user is None:
            check_password(password or '', _TIMING_EQUALISER)
            return None
        if user.check_password(password or '') and user.is_active:
            return user
        return None

    def get_user(self, user_id):
        User = get_user_model()
        return User.objects.filter(pk=user_id).select_related('tenant').first()


def _client_ip(request):
    """Best-effort client IP for the throttle key.

    `X-Forwarded-For` is only trustworthy behind a proxy that sets it; treat the
    value as a hint for rate limiting, never as an authorization input.
    """
    if request is None:
        return ''
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')
