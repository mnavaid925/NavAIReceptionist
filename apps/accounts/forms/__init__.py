"""Form package for Module 0 — Accounts & Access.

Foundation apps are FLAT: entity files sit at the package root.

Every form MUST be re-exported here — that is what keeps
`from apps.accounts.forms import LoginForm` working. Adding a form without adding
it below is a bug that surfaces as an ImportError at runtime.

`TenantModelForm` / `TenantLocationModelForm` are re-exported because they are the
CROSS-APP base classes every other module's forms inherit.
"""
from apps.accounts.forms._common import (
    ALLOWED_AUDIO_EXTENSIONS,
    MAX_RECORDING_BYTES,
    TenantLocationModelForm,
    TenantModelForm,
    style_widgets,
)
from apps.accounts.forms.Auth import (
    ChangeEmailRequestForm,
    ChangePasswordForm,
    LoginForm,
    PasswordResetRequestForm,
    SetNewPasswordForm,
)
from apps.accounts.forms.Users import OwnProfileForm, UserAdminForm

__all__ = [
    # Cross-app bases and constants.
    'TenantModelForm',
    'TenantLocationModelForm',
    'ALLOWED_AUDIO_EXTENSIONS',
    'MAX_RECORDING_BYTES',
    'style_widgets',
    # 0.1 — Authentication & Session.
    'LoginForm',
    'PasswordResetRequestForm',
    'SetNewPasswordForm',
    # 0.2 — Credential Management.
    'ChangePasswordForm',
    'ChangeEmailRequestForm',
    # 0.3 — User Profile & Directory.
    'UserAdminForm',
    'OwnProfileForm',
]
