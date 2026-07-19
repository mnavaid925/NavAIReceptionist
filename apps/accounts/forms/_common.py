"""Shared form toolkit — the CROSS-APP base classes every other app's forms inherit.

`TenantModelForm` and `TenantLocationModelForm` live here, in the foundation app,
because every domain module's forms subclass them. Entity modules pull the toolkit
with `from apps.accounts.forms._common import *`.

Two rules these bases exist to make unbreakable:

* **`tenant` and `location` are never form fields.** They are stamped from
  `request.tenant` / `request.location` in `save()`. A form that renders `location`
  as a `<select>` is a cross-location IDOR — it lets a user assign a record to a
  site they were never assigned to.
* **Every FK choice queryset is narrowed to the active tenant, and to the active
  location when the related model is location-scoped.** Otherwise the dropdown
  itself becomes the leak, even when the view's own queryset is scoped correctly.
"""
from django import forms  # noqa: F401  (re-exported for entity modules)
from django.core.exceptions import ValidationError  # noqa: F401

__all__ = [
    'forms',
    'ValidationError',
    'TenantModelForm',
    'TenantLocationModelForm',
    'ALLOWED_AUDIO_EXTENSIONS',
    'MAX_RECORDING_BYTES',
    'style_widgets',
]

# Upload guards for the recording surfaces in Modules 3 and 5.
ALLOWED_AUDIO_EXTENSIONS = ('.wav', '.mp3', '.ogg', '.m4a')
MAX_RECORDING_BYTES = 25 * 1024 * 1024

# Widget classes come from the design system, applied here ONCE so no template
# ever hand-styles an input.
_TEXTUAL_WIDGETS = (
    forms.TextInput, forms.EmailInput, forms.URLInput, forms.NumberInput,
    forms.PasswordInput, forms.DateInput, forms.DateTimeInput, forms.TimeInput,
)


def style_widgets(form):
    """Apply the theme's form classes to every widget on `form`."""
    for field in form.fields.values():
        widget = field.widget
        existing = widget.attrs.get('class', '')
        if isinstance(widget, forms.Textarea):
            css = 'form-textarea'
        elif isinstance(widget, (forms.Select, forms.SelectMultiple, forms.NullBooleanSelect)):
            css = 'form-select'
        elif isinstance(widget, (forms.CheckboxInput, forms.RadioSelect,
                                 forms.CheckboxSelectMultiple)):
            css = ''
        elif isinstance(widget, _TEXTUAL_WIDGETS) or isinstance(widget, forms.FileInput):
            css = 'form-input'
        else:
            css = 'form-input'
        if css and css not in existing:
            widget.attrs['class'] = f'{existing} {css}'.strip()
    return form


class TenantModelForm(forms.ModelForm):
    """Base for every tenant-scoped model form.

    Usage::

        form = SomeForm(request.POST or None, instance=obj, request=request)

    `tenant` is stamped in `save()`; it is never rendered and never accepted from
    the client.
    """

    #: FK field names whose querysets should be narrowed to the active tenant.
    tenant_scoped_fields = ()

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        self.tenant = getattr(request, 'tenant', None) if request else kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)

        # `tenant` must never reach the rendered form, whatever Meta.fields says.
        self.fields.pop('tenant', None)

        self._narrow_tenant_fields()
        style_widgets(self)

    def _narrow_tenant_fields(self):
        for name in self.tenant_scoped_fields:
            field = self.fields.get(name)
            if field is not None and hasattr(field, 'queryset'):
                field.queryset = (
                    field.queryset.filter(tenant=self.tenant)
                    if self.tenant is not None
                    else field.queryset.none()
                )

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.tenant is not None:
            instance.tenant = self.tenant
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class TenantLocationModelForm(TenantModelForm):
    """Base for every model scoped to a tenant AND a location.

    `location` is stamped from `request.location` — it is not a field, not a
    hidden input, and not read from POST data.
    """

    #: FK field names whose querysets should be narrowed to the active location.
    location_scoped_fields = ()

    def __init__(self, *args, request=None, **kwargs):
        self.location = getattr(request, 'location', None) if request else kwargs.pop('location', None)
        super().__init__(*args, request=request, **kwargs)

        self.fields.pop('location', None)
        self._narrow_location_fields()
        style_widgets(self)

    def _narrow_location_fields(self):
        for name in self.location_scoped_fields:
            field = self.fields.get(name)
            if field is not None and hasattr(field, 'queryset'):
                field.queryset = (
                    field.queryset.filter(location=self.location)
                    if self.location is not None
                    else field.queryset.none()
                )

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.location is not None:
            instance.location = self.location
        if commit:
            instance.save()
            self.save_m2m()
        return instance
