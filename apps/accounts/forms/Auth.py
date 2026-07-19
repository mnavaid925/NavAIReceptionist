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

__all__ = [
    'LoginForm',
    'PasswordResetRequestForm',
    'SetNewPasswordForm',
    'ChangePasswordForm',
    'ChangeEmailRequestForm',
]


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


class ChangePasswordForm(SetNewPasswordForm):
    """Change your own password from inside an authenticated session.

    Extends the reset form with a current-password gate. That gate is the whole
    point: without it, anyone who walks up to an unlocked browser — or who has
    hijacked a session — can lock the real owner out of their own account.
    """

    current_password = forms.CharField(  # noqa: F405
        label='Current password',
        strip=False,
        widget=forms.PasswordInput(attrs={  # noqa: F405
            'autofocus': True,
            'autocomplete': 'current-password',
        }),
    )

    field_order = ['current_password', 'new_password1', 'new_password2']

    def clean_current_password(self):
        current = self.cleaned_data['current_password']
        if not self.user.check_password(current):
            raise ValidationError('That is not your current password.')  # noqa: F405
        return current

    def clean(self):
        cleaned = super().clean()
        current = cleaned.get('current_password')
        new = cleaned.get('new_password1')
        if current and new and current == new:
            self.add_error(
                'new_password1', 'The new password must differ from the current one.'
            )
        return cleaned


class ChangeEmailRequestForm(forms.Form):  # noqa: F405
    """Request a change of sign-in address.

    Nothing is written here. A confirmation link goes to the NEW address and the
    change only lands once that link is opened, so a typo cannot lock a user out of
    their own account and an attacker cannot repoint an address they do not control.

    The current password is required for the same reason as on the password form.
    """

    new_email = forms.EmailField(  # noqa: F405
        label='New email address',
        max_length=254,
        widget=forms.EmailInput(attrs={  # noqa: F405
            'autofocus': True,
            'autocomplete': 'email',
        }),
    )
    current_password = forms.CharField(  # noqa: F405
        label='Current password',
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}),  # noqa: F405
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        style_widgets(self)  # noqa: F405

    def clean_current_password(self):
        current = self.cleaned_data['current_password']
        if not self.user.check_password(current):
            raise ValidationError('That is not your current password.')  # noqa: F405
        return current

    def clean_new_email(self):
        from apps.accounts.models import User

        new_email = self.cleaned_data['new_email'].strip()

        if new_email.lower() == (self.user.email or '').lower():
            raise ValidationError(  # noqa: F405
                'That is already the address on this account.'
            )

        # `(tenant, email)` is unique, so check within THIS tenant only — the same
        # address legitimately exists in other businesses. This is re-checked again
        # at confirmation time, because the window between request and confirm is
        # long enough for another user to take the address.
        clash = User.objects.filter(
            tenant=self.user.tenant, email__iexact=new_email
        ).exclude(pk=self.user.pk)
        if clash.exists():
            raise ValidationError(  # noqa: F405
                'Another user in this business already uses that address.'
            )

        return new_email
