"""Authentication views — login, logout, forgot password, reset password.

The governing rule here is **uniform failure**. A wrong customer id, an unknown
email, a wrong password, a deactivated business and a suspended account all render
byte-identical responses. Anything that distinguishes them — a different message, a
different field error, a redirect, even a materially different response time — is
an account-enumeration channel, and the throttling elsewhere in this sub-module
cannot compensate for it.
"""
import logging

from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.accounts import throttling
from apps.accounts.forms import (
    ChangeEmailRequestForm,
    ChangePasswordForm,
    LoginForm,
    PasswordResetRequestForm,
    SetNewPasswordForm,
)
from apps.accounts.views._common import *  # noqa: F401,F403
from apps.accounts.views._helpers import (
    activate_sole_location,
    get_client_ip,
    safe_redirect_target,
    send_credential_change_notice,
)

logger = logging.getLogger(__name__)

__all__ = [
    'login_view',
    'logout_view',
    'password_reset_request_view',
    'password_reset_confirm_view',
    'change_password_view',
    'change_email_request_view',
    'email_change_confirm_view',
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

# The password-changed and email-changed notices now live in views/_helpers.py as
# `send_credential_change_notice`, shared by the reset flow here and by both 0.2
# credential flows — one wording, one call path, no drift between them.


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
                return redirect(safe_redirect_target(request))  # noqa: F405
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
        send_credential_change_notice(user, 'password')
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


# --------------------------------------------------------------------------- #
# 0.2 — Credential management
# --------------------------------------------------------------------------- #

EMAIL_CHANGE_SALT = 'accounts.email-change'

EMAIL_CHANGE_SUBJECT = 'Confirm your new NavAIReceptionist email address'
EMAIL_CHANGE_BODY = """Hello {name},

You asked to change the sign-in address on your NavAIReceptionist account at
{business} to this one.

Open this link to confirm the change:

{url}

The link can be used once and expires shortly. Until you open it, nothing has
changed and your existing address still signs you in. If you did not request this,
ignore this email.
"""


@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def change_password_view(request):
    """Change your own password, gated on the current one."""
    form = ChangePasswordForm(request.POST or None, user=request.user)
    keys = throttling.build_keys(
        'change_password', request.user.pk, get_client_ip(request)
    )

    if request.method == 'POST':
        if throttling.is_throttled(keys):
            form.add_error(None, THROTTLED_ERROR)
        elif form.is_valid():
            form.save()
            throttling.clear(keys)
            # Keeps THIS session signed in. Django rotates the session auth hash on
            # a password change, so without this the user is bounced to the login
            # page immediately after succeeding — and every other session for this
            # account is invalidated, which is the behaviour we want.
            update_session_auth_hash(request, request.user)
            send_credential_change_notice(request.user, 'password')
            logger.info('Password changed for user_id=%s', request.user.pk)
            messages.success(  # noqa: F405
                request,
                'Your password has been changed. Any other sessions have been '
                'signed out.',
            )
            return redirect('accounts:change_password')  # noqa: F405
        else:
            throttling.register_failure(keys)

    return render(request, 'accounts/credentials/change_password.html', {  # noqa: F405
        'form': form,
    })


@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def change_email_request_view(request):
    """Request a new sign-in address.

    Writes NOTHING. The address changes only when the confirmation link sent to the
    new address is opened, so a typo cannot lock anyone out and nobody can repoint
    an account at an address they do not control.
    """
    form = ChangeEmailRequestForm(request.POST or None, user=request.user)
    keys = throttling.build_keys(
        'change_email', request.user.pk, get_client_ip(request)
    )
    sent_to = None

    if request.method == 'POST':
        if throttling.is_throttled(keys):
            form.add_error(None, THROTTLED_ERROR)
        elif form.is_valid():
            new_email = form.cleaned_data['new_email']
            _send_email_change_link(request, request.user, new_email)
            throttling.register_failure(keys)
            sent_to = new_email
            logger.info('Email change requested for user_id=%s', request.user.pk)
        else:
            throttling.register_failure(keys)

    return render(request, 'accounts/credentials/change_email.html', {  # noqa: F405
        'form': form,
        'sent_to': sent_to,
    })


def _send_email_change_link(request, user, new_email):
    """Email a signed, short-TTL confirmation link to the NEW address.

    The pending change lives entirely inside the signed token — there is no pending
    -email table, which keeps the model count where the ERD fixes it. Embedding the
    CURRENT email makes the token self-invalidating: once the change lands, the
    stored email no longer matches and any copy of the link stops verifying, so it
    is single-use without any server-side state to expire.
    """
    token = signing.dumps(
        {'uid': user.pk, 'new_email': new_email, 'current_email': user.email},
        salt=EMAIL_CHANGE_SALT,
    )
    url = request.build_absolute_uri(
        reverse('accounts:email_change_confirm', kwargs={'token': token})  # noqa: F405
    )
    try:
        send_mail(
            EMAIL_CHANGE_SUBJECT,
            EMAIL_CHANGE_BODY.format(
                name=user.display_name,
                business=user.tenant.name if user.tenant_id else 'your business',
                url=url,
            ),
            settings.DEFAULT_FROM_EMAIL,  # noqa: F405
            [new_email],
            fail_silently=False,
        )
    except Exception:
        logger.exception('Email-change link failed for user_id=%s', user.pk)


@login_required  # noqa: F405
@require_http_methods(['GET'])  # noqa: F405
def email_change_confirm_view(request, token):
    """Apply a confirmed email change.

    Requires a signed-in session as well as the token: a link leaked from an inbox
    is not, on its own, enough to repoint an account.
    """
    from apps.accounts.models import User

    try:
        payload = signing.loads(
            token,
            salt=EMAIL_CHANGE_SALT,
            max_age=settings.EMAIL_CHANGE_TOKEN_MAX_AGE,  # noqa: F405
        )
    except signing.BadSignature:
        # Covers tampering, a wrong salt, and expiry.
        return render(request, 'accounts/credentials/email_change_confirm.html', {  # noqa: F405
            'valid': False,
        })

    user = request.user
    old_email = payload.get('current_email')
    new_email = payload.get('new_email')

    # The token must belong to the signed-in user, and must still describe the
    # account's CURRENT address — that second check is what makes it single-use.
    if payload.get('uid') != user.pk or old_email != user.email:
        return render(request, 'accounts/credentials/email_change_confirm.html', {  # noqa: F405
            'valid': False,
        })

    # Re-check uniqueness at APPLY time, not just at request time. Between the two
    # someone else in this business may have taken the address, and the DB
    # constraint would surface as an IntegrityError 500 rather than a message.
    taken = User.objects.filter(
        tenant=user.tenant, email__iexact=new_email
    ).exclude(pk=user.pk).exists()
    if taken:
        return render(request, 'accounts/credentials/email_change_confirm.html', {  # noqa: F405
            'valid': False,
            'taken': True,
        })

    user.email = new_email
    user.save(update_fields=['email', 'updated_at'])

    # The tripwire goes to the OLD address. Sending only to the new one would tell
    # an attacker who just took the account and nobody else.
    send_credential_change_notice(
        user, 'email', to_email=old_email, detail=f' to {new_email}'
    )
    logger.info('Email changed for user_id=%s', user.pk)

    messages.success(request, 'Your sign-in email address has been updated.')  # noqa: F405
    return render(request, 'accounts/credentials/email_change_confirm.html', {  # noqa: F405
        'valid': True,
        'new_email': new_email,
    })
