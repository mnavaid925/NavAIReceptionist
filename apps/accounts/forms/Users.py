"""Forms for the user directory (sub-module 0.3).

TWO forms over ONE table, and the split is the security control, not an
organisational nicety:

* `UserAdminForm` exposes `tier`, `status` and `is_provider`. It is reachable only
  from the tier-gated management views — but that gate is `MANAGEMENT_TIERS`,
  which includes `manager`, so the form itself restricts WHO may grant or revoke
  the `owner` tier. A gate that lets managers in cannot also be the thing that
  stops managers minting owners.
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

        # The tier this row ALREADY has, captured before validation can move it.
        # `_post_clean()` writes the submitted tier onto `self.instance` during
        # `is_valid()`, so reading `instance.tier` from `clean_tier` would echo the
        # submission rather than the stored value — the same trap that silently
        # disabled the view's last-owner guard.
        self._original_tier = self.instance.tier if self.instance.pk else None

        # OWNER IS OWNER-GRANTABLE ONLY. This view is gated on MANAGEMENT_TIERS,
        # which includes `manager` — so without this a manager could open their own
        # edit page and select "Owner" from an unrestricted dropdown. `tier` is
        # this product's privilege boundary; who may hand it out is part of that
        # boundary. Dropping the choice is the UX half (a ChoiceField also
        # validates against its choices, so this alone rejects a tampered POST);
        # `clean_tier` below is the authoritative half, so re-widening these
        # choices later cannot silently re-open the hole.
        if not self._actor_is_owner():
            self.fields['tier'].choices = [
                choice for choice in self.fields['tier'].choices
                if choice[0] != User.TIER_OWNER
            ]

    def _actor_is_owner(self):
        """Whether the signed-in user performing this edit is an owner."""
        actor = getattr(self.request, 'user', None) if self.request else None
        return getattr(actor, 'tier', None) == User.TIER_OWNER

    def clean_tier(self):
        """Only an owner may grant the owner tier, or alter an existing owner's.

        Two directions, one boundary. Granting is the escalation: a manager minting
        an owner seat for themselves. Revoking is the same boundary from the other
        side — a manager stripping the owners would leave the business with nobody
        able to reach owner-only surfaces, and combined with the last-owner guard
        (which only covers a user demoting THEMSELVES) it is the path that could
        empty the owner seat entirely.
        """
        tier = self.cleaned_data.get('tier')
        if self._actor_is_owner():
            return tier
        if tier == User.TIER_OWNER:
            raise ValidationError(  # noqa: F405
                'Only an owner can grant the owner role.'
            )
        if self._original_tier == User.TIER_OWNER:
            raise ValidationError(  # noqa: F405
                "Only an owner can change another owner's role."
            )
        return tier

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
