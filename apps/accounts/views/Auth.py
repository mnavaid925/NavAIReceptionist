"""Authentication views — login, logout, forgot password, reset password.

The governing rule here is **uniform failure**. A wrong customer id, an unknown
email, a wrong password, a deactivated business and a suspended account all render
byte-identical responses. Anything that distinguishes them — a different message, a
different field error, a redirect, even a materially different response time — is
an account-enumeration channel, and the throttling elsewhere in this sub-module
cannot compensate for it.
"""
import logging

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import (
    url_has_allowed_host_and_scheme,
    urlsafe_base64_decode,
    urlsafe_base64_encode,
)

from apps.accounts import throttling
from apps.accounts.forms import (
    LoginForm,
    PasswordResetRequestForm,
    SetNewPasswordForm,
)
from apps.accounts.views._common import *  # noqa: F401,F403
from apps.accounts.views._helpers import activate_sole_location, get_client_ip

logger = logging.getLogger(__name__)

__all__ = [
    'login_view',
    'logout_view',
    'password_reset_request_view',
    'password_reset_confirm_view',
]

# ONE message for every failure path. Do not add a second.
UNIFORM_LOGIN_ERROR = (
    'Those details do not match an active account. Check your Customer ID, '
    'email or username, and password.'
)

# Shown whether or not the address matched anything.
UNIFORM_RESET_NOTICE = (
    'If that email address belongs to an account, a password reset link is on its way. '
    'The link expires shortly, so use it soon.'
)

THROTTLED_ERROR = (
    'Too many sign-in attempts. Please wait a few minutes and try again.'
)

RESET_EMAIL_SUBJECT = 'Reset your NavAIReceptionist password'
RESET_EMAIL_BODY = """Hello {name},

A password reset was requested for your NavAIReceptionist account at {business}.

Open this link to choose a new password:

{url}

The link can be used once and expires shortly. If you did not request this, you
can safely ignore this email — your password has not changed.
"""

CHANGED_EMAIL_SUBJECT = 'Your NavAIReceptionist password was changed'
CHANGED_EMAIL_BODY = """Hello {name},

The password for your NavAIReceptionist account at {business} has just been changed.

If this was you, no action is needed. If it was not, contact your administrator
immediately — someone else may have access to your account.
"""


# --------------------------------------------------------------------------- #
# Login / logout
# --------------------------------------------------------------------------- #

@require_http_methods(['GET', 'POST'])  # noqa: F405
def login_view(request):
    """Customer-scoped sign-in."""
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')  # noqa: F405

    form = LoginForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        customer_id = form.cleaned_data['customer_id']
        identifier = form.cleaned_data['identifier']
        keys = throttling.build_keys(customer_id, identifier, get_client_ip(request))

        if throttling.is_throttled(keys):
            form.add_error(None, THROTTLED_ERROR)
        else:
            user = authenticate(
                request,
                customer_id=customer_id,
                identifier=identifier,
                password=form.cleaned_data['password'],
            )
            if user is not None:
                login(request, user)
                activate_sole_location(request, user)
                logger.info('Login succeeded for user_id=%s tenant_id=%s',
                            user.pk, user.tenant_id)
                return redirect(_safe_next(request))  # noqa: F405
            # Never say WHICH part was wrong.
            form.add_error(None, UNIFORM_LOGIN_ERROR)

    return render(request, 'accounts/auth/login.html', {  # noqa: F405
        'form': form,
    })


@require_POST  # noqa: F405
def logout_view(request):
    """Sign out. POST-only, so a link prefetcher cannot end a session.

    `logout()` flushes the whole session, which clears the active location with it.
    """
    logout(request)
    messages.success(request, 'You have been signed out.')  # noqa: F405
    return redirect('accounts:login')  # noqa: F405


def _safe_next(request):
    """Resolve `?next=`, refusing anything off-site.

    An unchecked `next` is an open redirect: a phishing link can send a user
    through a genuine login form and out to an attacker's page.
    """
    candidate = request.POST.get('next') or request.GET.get('next') or ''
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return 'accounts:dashboard'


# --------------------------------------------------------------------------- #
# Password reset
# --------------------------------------------------------------------------- #

@require_http_methods(['GET', 'POST'])  # noqa: F405
def password_reset_request_view(request):
    """Request a reset link.

    The response is identical for zero, one or many matches. The tenant is NOT
    asked for again: the link is keyed on the user's primary key, which is globally
    unique, so an address shared by two businesses simply yields one link each.
    """
    form = PasswordResetRequestForm(request.POST or None)
    sent = False

    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']
        keys = throttling.build_keys('reset', email, get_client_ip(request))

        if not throttling.is_throttled(keys):
            throttling.register_failure(keys)
            for user in _resettable_users(email):
                _send_reset_email(request, user)

        # Rendered whether we sent nothing, one, or several — and whether or not
        # the request was throttled.
        sent = True

    return render(request, 'accounts/auth/password_reset_request.html', {  # noqa: F405
        'form': form,
        'sent': sent,
        'notice': UNIFORM_RESET_NOTICE,
    })


def _resettable_users(email):
    """Active users with this address, across every tenant."""
    User = get_user_model()
    return User.objects.filter(
        email__iexact=email,
        status=User.STATUS_ACTIVE,
        tenant__isnull=False,
        tenant__is_active=True,
    ).select_related('tenant')


def _send_reset_email(request, user):
    """Email one reset link. Failures are logged, never surfaced to the caller."""
    token = default_token_generator.make_token(user)
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    url = request.build_absolute_uri(
        reverse('accounts:password_reset_confirm',  # noqa: F405
                kwargs={'uidb64': uidb64, 'token': token})
    )
    try:
        send_mail(
            RESET_EMAIL_SUBJECT,
            RESET_EMAIL_BODY.format(
                name=user.display_name,
                business=user.tenant.name if user.tenant else 'your business',
                url=url,
            ),
            settings.DEFAULT_FROM_EMAIL,  # noqa: F405
            [user.email],
            fail_silently=False,
        )
    except Exception:
        # Never let a mail-server problem tell the caller the address was real.
        logger.exception('Password reset email failed for user_id=%s', user.pk)


@require_http_methods(['GET', 'POST'])  # noqa: F405
def password_reset_confirm_view(request, uidb64, token):
    """Choose a new password behind a valid token.

    The token is single-use for free: `default_token_generator` hashes the current
    password hash, so changing the password invalidates every outstanding link for
    that account. An invalid or expired token renders a friendly prompt — never a
    500, never a Django debug page.
    """
    user = _user_from_uid(uidb64)
    valid = user is not None and default_token_generator.check_token(user, token)

    if not valid:
        return render(request, 'accounts/auth/password_reset_confirm.html', {  # noqa: F405
            'valid': False,
        })

    form = SetNewPasswordForm(request.POST or None, user=user)

    if request.method == 'POST' and form.is_valid():
        form.save()
        _send_password_changed_email(user)
        logger.info('Password reset completed for user_id=%s', user.pk)
        messages.success(  # noqa: F405
            request, 'Your password has been changed. Please sign in.'
        )
        return redirect('accounts:login')  # noqa: F405

    return render(request, 'accounts/auth/password_reset_confirm.html', {  # noqa: F405
        'form': form,
        'valid': True,
    })


def _user_from_uid(uidb64):
    """Decode the link's user id. Returns None on any malformed input."""
    User = get_user_model()
    try:
        pk = force_str(urlsafe_base64_decode(uidb64))
    except (TypeError, ValueError, OverflowError, UnicodeDecodeError):
        return None
    return User.objects.filter(pk=pk).select_related('tenant').first()


def _send_password_changed_email(user):
    """Tell the account holder their password changed — the takeover tripwire.

    Sub-module 0.2 generalises this into the shared Credential Change Notice; it is
    deliberately local until then rather than a premature abstraction.
    """
    try:
        send_mail(
            CHANGED_EMAIL_SUBJECT,
            CHANGED_EMAIL_BODY.format(
                name=user.display_name,
                business=user.tenant.name if user.tenant else 'your business',
            ),
            settings.DEFAULT_FROM_EMAIL,  # noqa: F405
            [user.email],
            fail_silently=True,
        )
    except Exception:
        logger.exception('Password-changed notice failed for user_id=%s', user.pk)
