"""Resource form (sub-module 4.2).

`tenant` AND `location` are both stamped from the request by
`TenantLocationModelForm` — neither is rendered. A resource is a physical thing
at the site you are currently working in, so there is no choice to offer.
"""
from apps.scheduling.forms._common import *  # noqa: F401,F403
from apps.scheduling.models import Resource

__all__ = ['ResourceForm']


class ResourceForm(TenantLocationModelForm):  # noqa: F405
    """Create or edit one resource."""

    class Meta:
        model = Resource
        fields = (
            'name',
            'resource_number',
            'description',
            'is_active',
            'display_order',
        )
        labels = {
            'resource_number': 'Number or code',
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),  # noqa: F405
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].required = True
        style_widgets(self)  # noqa: F405

    def clean_name(self):
        """Enforce the `(location, name)` uniqueness by hand.

        Django validates a model's `UniqueConstraint` in `Model.full_clean` ONLY
        for fields the form actually renders. `location` is excluded here (it is
        stamped from the request), so Django cannot build the constraint's field
        tuple and skips the check entirely — a duplicate name would sail through
        validation and surface as a raw IntegrityError 500 at `save()`.

        This is the same trap on every form in this project that excludes part of
        a unique constraint. Checking here turns the 500 into a field error.
        """
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            return name

        if self.location is None:
            raise ValidationError(  # noqa: F405
                'Choose a location before adding resources to it.'
            )

        clash = Resource.objects.filter(location=self.location, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError(  # noqa: F405
                f'{self.location.name} already has a resource called "{name}".'
            )
        return name
