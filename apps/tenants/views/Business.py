"""Business settings (sub-module 1.1).

There is exactly ONE `tenants.Tenant` row per business and `request.tenant` IS
it, so this sub-module has no list page and no pk in any URL. A pk here would be
an invitation to request someone else's business.
"""
import logging

from apps.tenants.forms import BusinessSettingsForm
from apps.tenants.models import Location
from apps.tenants.views._common import *  # noqa: F401,F403

logger = logging.getLogger(__name__)

__all__ = ['business_settings_view', 'business_settings_edit_view']


@login_required  # noqa: F405
def business_settings_view(request):
    """Read-only overview of the business record.

    Open to any signed-in user: knowing your own Customer ID matters, because it
    is the first field on the sign-in form and nobody can get back in without it.
    """
    tenant = request.tenant
    locations = Location.objects.filter(tenant=tenant) if tenant else Location.objects.none()

    return render(request, 'tenants/business/detail.html', {  # noqa: F405
        'tenant': tenant,
        'location_count': locations.count(),
        'active_location_count': locations.filter(is_active=True).count(),
        'can_edit': request.user.tier == 'owner',
    })


@login_required  # noqa: F405
@tier_required('owner')  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def business_settings_edit_view(request):
    """Edit the business record. Owner-only.

    Owner rather than manager because these values are spoken to callers — the
    business name lands in confirmations, and the timezone is the default every
    new site inherits.
    """
    tenant = request.tenant
    if tenant is None:
        # The platform superuser has no tenant; there is nothing here to edit.
        messages.error(request, 'No business is associated with this account.')  # noqa: F405
        return redirect('accounts:dashboard')  # noqa: F405

    form = BusinessSettingsForm(request.POST or None, instance=tenant)

    if request.method == 'POST' and form.is_valid():
        form.save()
        logger.info('Business settings updated for tenant_id=%s by user_id=%s',
                    tenant.pk, request.user.pk)
        messages.success(request, 'Business settings saved.')  # noqa: F405
        return redirect('tenants:business_settings')  # noqa: F405

    return render(request, 'tenants/business/form.html', {  # noqa: F405
        'form': form,
        'tenant': tenant,
    })
