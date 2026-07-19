"""Form package for Module 1 — Business & Locations.

Foundation apps are FLAT: entity files sit at the package root.

Every form MUST be re-exported here — that is what keeps
`from apps.tenants.forms import LocationForm` working. Adding a form without
adding it below is a bug that surfaces as an ImportError at runtime.
"""
from apps.tenants.forms.Business import COMMON_TIMEZONES, BusinessSettingsForm
from apps.tenants.forms.Location import COUNTRY_CHOICES, LocationForm
from apps.tenants.forms.WorkingHours import (
    IntervalForm,
    IntervalFormSet,
    build_interval_initial,
)

__all__ = [
    # 1.1 — Business Settings.
    'BusinessSettingsForm',
    'COMMON_TIMEZONES',
    # 1.2 — Location Directory.
    'LocationForm',
    'COUNTRY_CHOICES',
    # 1.4 — Provider Working Hours.
    'IntervalForm',
    'IntervalFormSet',
    'build_interval_initial',
]
