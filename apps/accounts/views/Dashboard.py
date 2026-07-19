"""The dashboard — where a successful sign-in lands.

Deliberately thin. Its job in sub-module 0.1 is to be the observable proof that
customer-scoped login works and that the tenant and active location resolved
correctly. The real operational widgets (live calls, today's bookings, call
outcomes) arrive with the modules that own that data — a dashboard cannot show
call volume before `calls.CallSession` exists.
"""
from apps.accounts.models import UserLocation
from apps.accounts.views._common import *  # noqa: F401,F403

__all__ = ['dashboard_view']


@login_required  # noqa: F405
def dashboard_view(request):
    """Landing page for an authenticated user."""
    assigned = request.user.assigned_locations()

    stats = {
        'locations': assigned.count(),
        'assignments': UserLocation.objects.filter(tenant=request.tenant).count()
        if request.tenant else 0,
        'tier': request.user.get_tier_display(),
    }

    return render(request, 'accounts/dashboard.html', {  # noqa: F405
        'stats': stats,
        'assigned_locations': assigned,
    })
