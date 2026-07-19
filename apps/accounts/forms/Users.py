"""Forms for the user directory (sub-module 0.3).

TWO forms over ONE table, and the split is the security control, not an
organisational nicety:

* `UserAdminForm` exposes `tier`, `status` and `is_provider`. It is reachable only
  from the tier-gated management views.
* `OwnProfileForm` exposes name and phone ONLY. Every signed-in user reaches it,
  so any privileged field listed there would be a self-service promotion to owner.

A `ModelForm` renders and saves exactly what `Meta.fields` names, so keeping the
privileged fields out of the profile form is what makes tampering with a POST body
inert — the field simply is not bound.
"""
from apps.accounts.forms._common import *  # noqa: F401,F403
from apps.accounts.models import User

__all__ = ['UserAdminForm', 'OwnProfileForm']


class UserAdminForm(TenantModelForm):  # noqa: F405
    """Create or edit a user. Owner/manager only."""

    class Meta:
        model = User
        fields = (
            'email',
            'username',
            'first_name',
            'last_name',
            'full_name',
            'primary_phone',
            'tier',
            'status',
            'is_provider',
        )
        help_texts = {
            'username': 'Optional. An alternative to the email address at sign-in.',
            'full_name': 'Leave blank to derive it from the first and last name.',
            'is_provider': 'A provider is bookable on the calendar — there is no '
                           'separate provider record.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # `password` is never on this form. New users are invited and set their own
        # password through the reset flow; an admin-typed password would have to be
        # transmitted to the user out of band, which is worse than the invite.
        self.fields['email'].required = True

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        # `(tenant, email)` is unique. Validating here turns a database
        # IntegrityError 500 into a field error the user can act on.
        clash = User.objects.filter(tenant=self.tenant, email__iexact=email)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError(  # noqa: F405
                'Another user in this business already uses that address.'
            )
        return email

    def clean_username(self):
        # Must normalise to None, never '': the unique index over
        # (tenant, username) treats NULLs as distinct but '' as a colliding value,
        # so a blank string would let only one user per business have no username.
        username = (self.cleaned_data.get('username') or '').strip() or None
        if username is None:
            return None
        clash = User.objects.filter(tenant=self.tenant, username__iexact=username)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError(  # noqa: F405
                'Another user in this business already uses that username.'
            )
        return username


class OwnProfileForm(TenantModelForm):  # noqa: F405
    """Edit your own profile.

    Deliberately excludes `email` (that is 0.2's confirmed change flow), and
    `tier` / `status` / `is_provider` (those are privileged). Adding any of them
    here is a privilege escalation, not a convenience.
    """

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'full_name', 'primary_phone')
        help_texts = {
            'full_name': 'Leave blank to derive it from the first and last name.',
        }
