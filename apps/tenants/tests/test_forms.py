"""Form tests for `apps/tenants/forms/`.

`BusinessSettingsForm`: `customer_id`/`slug`/`is_active` are deliberately absent
(see the form's own docstring — a typo in `customer_id` would lock every user of
that business out with no way back in). `LocationForm`: `tenant` is never a
field — `TenantModelForm` pops it and stamps it from `request.tenant` — and the
slug/timezone `clean_*` methods turn what would be an `IntegrityError` /
`ZoneInfoNotFoundError` into a field error.
"""
import pytest
from django.test import RequestFactory

from apps.tenants.forms import BusinessSettingsForm, LocationForm
from apps.tenants.models import Location

pytestmark = pytest.mark.django_db


def _request_for(tenant, user=None):
    request = RequestFactory().get('/')
    request.tenant = tenant
    request.user = user
    return request


# --------------------------------------------------------------------------- #
# BusinessSettingsForm
# --------------------------------------------------------------------------- #

def test_business_settings_form_fields_exclude_customer_id_slug_and_is_active():
    form = BusinessSettingsForm(instance=None)
    assert set(form.fields) == {'name', 'timezone'}
    for locked in ('customer_id', 'slug', 'is_active'):
        assert locked not in form.fields


def test_business_settings_form_requires_a_name(tenant_a):
    form = BusinessSettingsForm({'name': '', 'timezone': 'UTC'}, instance=tenant_a)
    assert not form.is_valid()
    assert 'name' in form.errors


def test_business_settings_form_strips_whitespace_only_name(tenant_a):
    form = BusinessSettingsForm({'name': '   ', 'timezone': 'UTC'}, instance=tenant_a)
    assert not form.is_valid()
    assert 'name' in form.errors


def test_business_settings_form_saves_only_editable_fields(tenant_a):
    original_customer_id = tenant_a.customer_id
    original_slug = tenant_a.slug
    form = BusinessSettingsForm({'name': 'Renamed Biz', 'timezone': 'America/New_York'}, instance=tenant_a)
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.name == 'Renamed Biz'
    assert obj.timezone == 'America/New_York'
    assert obj.customer_id == original_customer_id
    assert obj.slug == original_slug


def test_business_settings_form_swallows_a_request_kwarg(tenant_a):
    """The view passes `request=` uniformly across Module 1's forms; this form
    has no `tenant` FK to stamp, so it must just discard the kwarg, not error."""
    form = BusinessSettingsForm(instance=tenant_a, request=_request_for(tenant_a))
    assert 'request' not in form.fields
    assert set(form.fields) == {'name', 'timezone'}


def test_business_settings_form_timezone_choices_include_the_current_value(tenant_a):
    tenant_a.timezone = 'Antarctica/Troll'
    form = BusinessSettingsForm(instance=tenant_a)
    values = [choice[0] for choice in form.fields['timezone'].choices]
    assert 'Antarctica/Troll' in values


# --------------------------------------------------------------------------- #
# LocationForm — tenant stamping
# --------------------------------------------------------------------------- #

def test_location_form_has_no_tenant_field(tenant_a):
    form = LocationForm(request=_request_for(tenant_a))
    assert 'tenant' not in form.fields


def test_location_form_save_stamps_the_request_tenant_never_posted_data(tenant_a, tenant_b):
    form = LocationForm({
        'name': 'Stamped Site', 'slug': 'stamped-site', 'timezone': 'UTC', 'country': 'US',
        'tenant': tenant_b.pk,
    }, request=_request_for(tenant_a))
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.tenant_id == tenant_a.pk


def test_location_form_requires_a_name(tenant_a):
    form = LocationForm({'slug': 'no-name', 'timezone': 'UTC'}, request=_request_for(tenant_a))
    assert not form.is_valid()
    assert 'name' in form.errors


# --------------------------------------------------------------------------- #
# LocationForm.clean_slug
# --------------------------------------------------------------------------- #

def test_location_form_generates_slug_from_name_when_blank(tenant_a):
    form = LocationForm({
        'name': 'Auto Slug Here', 'slug': '', 'timezone': 'UTC', 'country': 'US',
    }, request=_request_for(tenant_a))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['slug'] == 'auto-slug-here'


def test_location_form_rejects_duplicate_slug_within_the_same_tenant(tenant_a, location_a1):
    form = LocationForm({
        'name': 'Dup', 'slug': location_a1.slug, 'timezone': 'UTC', 'country': 'US',
    }, request=_request_for(tenant_a))
    assert not form.is_valid()
    assert 'slug' in form.errors


def test_location_form_editing_excludes_self_from_the_duplicate_check(tenant_a, location_a1):
    form = LocationForm({
        'name': location_a1.name, 'slug': location_a1.slug, 'timezone': 'UTC', 'country': 'US',
    }, instance=location_a1, request=_request_for(tenant_a))
    assert form.is_valid(), form.errors


def test_location_form_allows_same_slug_across_different_tenants(tenant_a, tenant_b):
    Location.objects.create(tenant=tenant_b, name='B Site', slug='shared-form-slug')
    form = LocationForm({
        'name': 'A Site', 'slug': 'shared-form-slug', 'timezone': 'UTC', 'country': 'US',
    }, request=_request_for(tenant_a))
    assert form.is_valid(), form.errors


def test_location_form_blank_name_and_blank_slug_is_an_error(tenant_a):
    form = LocationForm({'name': '', 'slug': '', 'timezone': 'UTC'}, request=_request_for(tenant_a))
    assert not form.is_valid()
    assert 'name' in form.errors


# --------------------------------------------------------------------------- #
# LocationForm.clean_timezone
# --------------------------------------------------------------------------- #

def test_location_form_rejects_unrecognised_timezone(tenant_a):
    form = LocationForm({
        'name': 'Bad TZ', 'slug': 'bad-tz-form', 'timezone': 'Not/ARealZone', 'country': 'US',
    }, request=_request_for(tenant_a))
    assert not form.is_valid()
    assert 'timezone' in form.errors


def test_location_form_accepts_a_valid_timezone(tenant_a):
    form = LocationForm({
        'name': 'Good TZ', 'slug': 'good-tz-form', 'timezone': 'Asia/Tokyo', 'country': 'US',
    }, request=_request_for(tenant_a))
    assert form.is_valid(), form.errors


def test_location_form_defaults_timezone_choice_to_the_tenants_own(tenant_a):
    tenant_a.timezone = 'Europe/Berlin'
    form = LocationForm(request=_request_for(tenant_a))
    values = [choice[0] for choice in form.fields['timezone'].choices]
    assert 'Europe/Berlin' in values
