"""Authentication forms — login, forgot password, set new password.

All plain `Form` subclasses: none of them has a tenant- or location-scoped FK to
narrow, so none inherits `TenantModelForm`.

These forms deliberately do NOT validate whether an account exists. Every
existence decision lives in the view, which renders one uniform message for all
failure paths — a field-level "no account with that email" here would re-open the
account-enumeration channel the throttling is designed to close.
"""
from django.contrib.auth import password_validation

from apps.accounts.forms._common import *  # noqa: F401,F403

__all__ = ['LoginForm', 'PasswordResetRequestForm', 'SetNewPasswordForm']


class LoginForm(forms.Form):  # noqa: F405
    """Customer id + email-or-username + password."""

    customer_id = forms.CharField(  # noqa: F405
        label='Customer ID',
        max_length=32,
        widget=forms.TextInput(attrs={  # noqa: F405
            'autofocus': True,
            'autocomplete': 'organization',
            'placeholder': 'ACME-1001',
        }),
        help_text='The ID issued to your business.',
    )
    identifier = forms.CharField(  # noqa: F405
        label='Email or username',
        max_length=254,
        widget=forms.TextInput(attrs={'autocomplete': 'username'}),  # noqa: F405
    )
    password = forms.CharField(  # noqa: F405
        label='Password',
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}),  # noqa: F405
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_widgets(self)  # noqa: F405

    def clean_customer_id(self):
        return self.cleaned_data['customer_id'].strip()

    def clean_identifier(self):
        return self.cleaned_data['identifier'].strip()


class PasswordResetRequestForm(forms.Form):  # noqa: F405
    """Ask for a reset link.

    Only the email address is collected. The tenant is NOT asked for again: the
    reset link is keyed on the user's primary key, which is globally unique, so an
    address shared by two businesses simply produces one link per account.
    """

    email = forms.EmailField(  # noqa: F405
        label='Email address',
        max_length=254,
        widget=forms.EmailInput(attrs={  # noqa: F405
            'autofocus': True,
            'autocomplete': 'email',
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_widgets(self)  # noqa: F405

    def clean_email(self):
        return self.cleaned_data['email'].strip()


class SetNewPasswordForm(forms.Form):  # noqa: F405
    """Choose a new password behind a valid reset token."""

    new_password1 = forms.CharField(  # noqa: F405
        label='New password',
        strip=False,
        widget=forms.PasswordInput(attrs={  # noqa: F405
            'autofocus': True,
            'autocomplete': 'new-password',
        }),
    )
    new_password2 = forms.CharField(  # noqa: F405
        label='Confirm new password',
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),  # noqa: F405
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        style_widgets(self)  # noqa: F405

    def clean(self):
        cleaned = super().clean()
        first = cleaned.get('new_password1')
        second = cleaned.get('new_password2')

        if first and second and first != second:
            self.add_error('new_password2', 'The two passwords do not match.')
            return cleaned

        if first:
            # Runs the project's configured AUTH_PASSWORD_VALIDATORS, including the
            # similarity check against this user's own attributes.
            try:
                password_validation.validate_password(first, self.user)
            except ValidationError as exc:  # noqa: F405
                self.add_error('new_password1', exc)

        return cleaned

    def save(self):
        self.user.set_password(self.cleaned_data['new_password1'])
        self.user.save(update_fields=['password'])
        return self.user
