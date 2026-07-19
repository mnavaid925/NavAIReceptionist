"""Private view helpers shared by more than one sub-module of `accounts`.

Helpers used by a single entity stay in that entity's own module; these are here
because two or more sub-modules call them.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from apps.accounts.middleware import ACTIVE_LOCATION_SESSION_KEY

logger = logging.getLogger(__name__)

__all__ = [
    'get_client_ip',
    'set_active_location',
    'activate_sole_location',
    'safe_redirect_target',
    'send_credential_change_notice',
    'tier_required',
]


# --------------------------------------------------------------------------- #
# Request inspection
# --------------------------------------------------------------------------- #

def get_client_ip(request):
    """Best-effort client IP, used as a throttle key.

    `X-Forwarded-For` is only meaningful behind a proxy that sets it. Treat this as
    a rate-limiting hint, never as an authorization input.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def safe_redirect_target(request, param='next', default='accounts:dashboard'):
    """Resolve a `next` parameter, refusing anything off-site.

    An unchecked redirect target is an open redirect: a phishing link can route a
    user through a genuine page of ours and back out to an attacker's. Every view
    that honours a caller-supplied destination goes through here — login and the
    location switcher both do.
    """
    candidate = request.POST.get(param) or request.GET.get(param) or ''
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return default


# --------------------------------------------------------------------------- #
# Active location
# --------------------------------------------------------------------------- #

def set_active_location(request, location):
    """Write the active location into the session.

    The CALLER is responsible for having proved the user is assigned to this
    location — every caller resolves it out of `user.assigned_locations()`, never
    out of a raw id from a form or a URL. `ActiveLocationMiddleware` re-validates
    it on the next request regardless, so a mistake here degrades to "no active
    location" rather than to a cross-location read.
    """
    if location is None:
        request.session.pop(ACTIVE_LOCATION_SESSION_KEY, None)
        return None
    request.session[ACTIVE_LOCATION_SESSION_KEY] = location.pk
    return location


def activate_sole_location(request, user):
    """Activate the user's only assignment, if they have exactly one.

    With two or more the choice belongs to the user, through the switcher.
    """
    candidates = list(user.assigned_locations()[:2])
    if len(candidates) == 1:
        return set_active_location(request, candidates[0])
    return None


# --------------------------------------------------------------------------- #
# Credential change notice — the account-takeover tripwire
# --------------------------------------------------------------------------- #

CREDENTIAL_NOTICE_SUBJECTS = {
    'password': 'Your NavAIReceptionist password was changed',
    'email': 'The email address on your NavAIReceptionist account was changed',
}

CREDENTIAL_NOTICE_BODY = """Hello {name},

{summary} for your NavAIReceptionist account at {business}.

If this was you, no action is needed. If it was not, contact your administrator
immediately — someone else may have access to your account.
"""

CREDENTIAL_NOTICE_SUMMARIES = {
    'password': 'Your password was just changed',
    'email': 'The sign-in email address was just changed{detail}',
}


def send_credential_change_notice(user, kind, to_email=None, detail=''):
    """Tell the account holder that a credential changed.

    This is the account-takeover tripwire: if someone else changed the password or
    the address, the real owner finds out. For an EMAIL change it must be sent to
    the OLD address — sending only to the new one tells the attacker and nobody
    else, which is the entire failure this exists to prevent.

    Never raises. A mail-server problem must not roll back a change the user
    successfully made, nor leak through as a 500.
    """
    recipient = to_email or user.email
    if not recipient:
        return False

    summary = CREDENTIAL_NOTICE_SUMMARIES.get(kind, 'A credential was just changed')
    try:
        send_mail(
            CREDENTIAL_NOTICE_SUBJECTS.get(kind, 'Your NavAIReceptionist account changed'),
            CREDENTIAL_NOTICE_BODY.format(
                name=user.display_name,
                summary=summary.format(detail=detail),
                business=user.tenant.name if user.tenant_id else 'your business',
            ),
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
        return True
    except Exception:
        # Log the failure with the user id only — never the address, which is PII.
        logger.exception('Credential-change notice failed for user_id=%s kind=%s',
                         user.pk, kind)
        return False


# --------------------------------------------------------------------------- #
# Authorization
# --------------------------------------------------------------------------- #

def tier_required(*allowed_tiers):
    """Restrict a view to the given `User.tier` values.

    `@login_required` only proves WHO is calling; this proves they are allowed to.
    Without it any staff-tier user could open the user-management pages and promote
    themselves to owner — a privilege escalation reachable from the normal UI.

    Redirects rather than 403s so a mis-clicked link is a readable message, not a
    dead end. The views it guards still scope every queryset by tenant, so this is
    defence in depth rather than the only control.
    """
    def decorator(view):
        def wrapper(request, *args, **kwargs):
            from django.contrib import messages

            user = request.user
            if not user.is_authenticated:
                return redirect(settings.LOGIN_URL)
            # The platform superuser has no tenant and no product tier; it is not
            # granted product-side authority by accident.
            if user.tier not in allowed_tiers:
                messages.error(
                    request, 'You do not have permission to open that page.'
                )
                return redirect('accounts:dashboard')
            return view(request, *args, **kwargs)

        wrapper.__name__ = getattr(view, '__name__', 'wrapped_view')
        wrapper.__doc__ = view.__doc__
        return wrapper

    return decorator
