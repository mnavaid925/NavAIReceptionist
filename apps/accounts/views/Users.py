"""The user directory (sub-module 0.3) and the signed-in user's own profile.

Every queryset here carries `tenant=request.tenant`, and every management view is
wrapped in `tier_required('owner', 'manager')`. Both are needed: the tenant filter
stops one business reading another's staff, the tier gate stops a staff-tier user
inside the right business from promoting themselves.

`accounts.User` is tenant-scoped but NOT location-scoped — a person belongs to the
business and may be assigned to several of its sites — so `location=` deliberately
does not appear in these filters. Which sites they may reach is `UserLocation`, and
that is sub-module 0.4 and Module 1.3.
"""
import logging

from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.accounts.forms import OwnProfileForm, UserAdminForm
from apps.accounts.models import User
from apps.accounts.views._common import *  # noqa: F401,F403
from apps.accounts.views._helpers import tier_required

logger = logging.getLogger(__name__)

__all__ = [
    'user_list_view',
    'user_create_view',
    'user_detail_view',
    'user_edit_view',
    'user_delete_view',
    'profile_view',
]

MANAGEMENT_TIERS = (User.TIER_OWNER, User.TIER_MANAGER)

INVITE_SUBJECT = 'You have been added to NavAIReceptionist'
INVITE_BODY = """Hello {name},

{inviter} has created a NavAIReceptionist account for you at {business}.

Choose your password to finish setting it up:

{url}

You will sign in with Customer ID {customer_id} and either your email address
({email}){username_note}.

The link can be used once and expires shortly. If it has expired by the time you
open it, use the "Forgot your password?" link on the sign-in page.
"""


def _tenant_users(request):
    """The base queryset. Tenant-scoped, always."""
    return User.objects.filter(tenant=request.tenant)


# --------------------------------------------------------------------------- #
# Directory
# --------------------------------------------------------------------------- #

@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)
def user_list_view(request):
    """List the business's users, with search and tier/status filters."""
    queryset = _tenant_users(request)

    # Every filter is parsed defensively: a junk value degrades to "no filter",
    # never a 500.
    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(
            Q(email__icontains=search)  # noqa: F405
            | Q(username__icontains=search)  # noqa: F405
            | Q(full_name__icontains=search)  # noqa: F405
            | Q(first_name__icontains=search)  # noqa: F405
            | Q(last_name__icontains=search)  # noqa: F405
            | Q(primary_phone__icontains=search)  # noqa: F405
        )

    tier = request.GET.get('tier', '').strip()
    if tier in dict(User.TIER_CHOICES):
        queryset = queryset.filter(tier=tier)

    status = request.GET.get('status', '').strip()
    if status in dict(User.STATUS_CHOICES):
        queryset = queryset.filter(status=status)

    provider = request.GET.get('provider', '').strip()
    if provider in {'yes', 'no'}:
        queryset = queryset.filter(is_provider=(provider == 'yes'))

    queryset = queryset.select_related('tenant').order_by('full_name', 'email')

    # Filters are applied BEFORE pagination, or page 2 shows the unfiltered list.
    page_obj, elided_page_range = paginate(request, queryset)  # noqa: F405

    return render(request, 'accounts/user/list.html', {  # noqa: F405
        'users': page_obj.object_list,
        'page_obj': page_obj,
        'elided_page_range': elided_page_range,
        'tier_choices': User.TIER_CHOICES,
        'status_choices': User.STATUS_CHOICES,
        'total_count': queryset.count(),
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)
def user_detail_view(request, pk):
    """Read-only detail for one user."""
    obj = get_object_or_404(_tenant_users(request), pk=pk)  # noqa: F405
    return render(request, 'accounts/user/detail.html', {  # noqa: F405
        'obj': obj,
        'assigned_locations': obj.assigned_locations(),
        'is_invited': obj.last_login is None and not obj.has_usable_password(),
        'is_self': obj.pk == request.user.pk,
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)
@require_http_methods(['GET', 'POST'])  # noqa: F405
def user_create_view(request):
    """Add a user and email them an invitation to set their own password."""
    form = UserAdminForm(request.POST or None, request=request)

    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.tenant = request.tenant
        # No admin-chosen password. The account cannot be signed into until the
        # invitee sets one, so a password never has to be relayed out of band.
        obj.set_unusable_password()
        obj.save()
        _send_invite(request, obj)
        messages.success(  # noqa: F405
            request, f'{obj.display_name} has been added and invited by email.'
        )
        return redirect('accounts:user_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'accounts/user/form.html', {  # noqa: F405
        'form': form,
        'is_edit': False,
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)
@require_http_methods(['GET', 'POST'])  # noqa: F405
def user_edit_view(request, pk):
    """Edit one user."""
    obj = get_object_or_404(_tenant_users(request), pk=pk)  # noqa: F405
    form = UserAdminForm(request.POST or None, instance=obj, request=request)

    if request.method == 'POST' and form.is_valid():
        # Guard against an owner demoting themselves out of the only owner seat and
        # locking the business out of its own user management.
        if obj.pk == request.user.pk and form.cleaned_data['tier'] != obj.tier:
            if _is_last_owner(request, obj):
                messages.error(  # noqa: F405
                    request,
                    'You are the only owner. Promote another user to owner before '
                    'changing your own role.',
                )
                return redirect('accounts:user_edit', pk=obj.pk)  # noqa: F405
        form.save()
        messages.success(request, f'{obj.display_name} has been updated.')  # noqa: F405
        return redirect('accounts:user_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'accounts/user/form.html', {  # noqa: F405
        'form': form,
        'obj': obj,
        'is_edit': True,
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)
@require_POST  # noqa: F405
def user_delete_view(request, pk):
    """Deactivate a user. This never deletes the row.

    `scheduling.Appointment.provider` points at these rows, so deleting one would
    either cascade away real appointment history or leave it pointing at nothing.
    Deactivation keeps the history readable and reversible while stopping the
    person signing in — `User.is_active` reads `status == 'active'`, and
    `CustomerScopedBackend` refuses anything else.
    """
    obj = get_object_or_404(_tenant_users(request), pk=pk)  # noqa: F405

    if obj.pk == request.user.pk:
        messages.error(request, 'You cannot deactivate your own account.')  # noqa: F405
        return redirect('accounts:user_detail', pk=obj.pk)  # noqa: F405

    if _is_last_owner(request, obj):
        messages.error(  # noqa: F405
            request,
            'That is the only active owner. Promote another user to owner first.',
        )
        return redirect('accounts:user_detail', pk=obj.pk)  # noqa: F405

    obj.status = User.STATUS_INACTIVE
    obj.save(update_fields=['status', 'updated_at'])
    logger.info('User deactivated user_id=%s by user_id=%s', obj.pk, request.user.pk)
    messages.success(  # noqa: F405
        request,
        f'{obj.display_name} has been deactivated and can no longer sign in. '
        'Their history is unchanged.',
    )
    return redirect('accounts:user_list')  # noqa: F405


def _is_last_owner(request, obj):
    """True when `obj` is the business's only remaining active owner."""
    if obj.tier != User.TIER_OWNER or obj.status != User.STATUS_ACTIVE:
        return False
    others = _tenant_users(request).filter(
        tier=User.TIER_OWNER, status=User.STATUS_ACTIVE
    ).exclude(pk=obj.pk)
    return not others.exists()


def _send_invite(request, user):
    """Email a set-your-password link, reusing the existing reset route.

    No second token scheme and no extra url: `default_token_generator` already
    produces a single-use, short-TTL token, and it is invalidated the moment the
    password is set because the token hashes the current password.
    """
    token = default_token_generator.make_token(user)
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    url = request.build_absolute_uri(
        reverse('accounts:password_reset_confirm',  # noqa: F405
                kwargs={'uidb64': uidb64, 'token': token})
    )
    username_note = f' or your username ({user.username})' if user.username else ''
    try:
        send_mail(
            INVITE_SUBJECT,
            INVITE_BODY.format(
                name=user.display_name,
                inviter=request.user.display_name,
                business=user.tenant.name,
                customer_id=user.tenant.customer_id,
                email=user.email,
                username_note=username_note,
                url=url,
            ),
            settings.DEFAULT_FROM_EMAIL,  # noqa: F405
            [user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception('Invitation email failed for user_id=%s', user.pk)


# --------------------------------------------------------------------------- #
# Own profile
# --------------------------------------------------------------------------- #

@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def profile_view(request):
    """Edit your own name and phone.

    Open to every signed-in user, which is exactly why `OwnProfileForm` carries no
    privileged field. The instance is always `request.user` — never a pk from the
    URL — so there is nothing here to point at somebody else's row.
    """
    form = OwnProfileForm(request.POST or None, instance=request.user, request=request)

    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Your profile has been updated.')  # noqa: F405
        return redirect('accounts:profile')  # noqa: F405

    return render(request, 'accounts/profile.html', {  # noqa: F405
        'form': form,
        'assigned_locations': request.user.assigned_locations(),
    })
