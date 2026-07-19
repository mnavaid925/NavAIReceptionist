"""Form tests for `ServiceForm` and `ResourceForm` (sub-module 4.2)."""
from types import SimpleNamespace

import pytest

from apps.scheduling.forms import ResourceForm, ServiceForm

pytestmark = pytest.mark.django_db


def _fake_request(tenant=None, user=None, location=None):
    """A minimal duck-typed stand-in for `HttpRequest`.

    `TenantModelForm`/`TenantLocationModelForm` only ever read `.tenant`,
    `.user` and `.location` off whatever is passed as `request=`, so a
    `SimpleNamespace` is enough — no need for `RequestFactory` here.
    """
    return SimpleNamespace(tenant=tenant, user=user, location=location)


def _service_data(**overrides):
    """Baseline valid POST data for `ServiceForm`.

    `buffer_minutes` and `display_order` carry a model-level `default`, but
    Django's `ModelForm` only treats a field as not-required when the MODEL
    field is `blank=True` — a `default` alone does not imply that. Both are
    therefore required form fields and must be present in every POST used in
    a validity assertion.
    """
    data = {
        'name': 'Consult',
        'duration_minutes': '30',
        'buffer_minutes': '0',
        'display_order': '0',
    }
    data.update(overrides)
    return data


def _resource_data(**overrides):
    """Baseline valid POST data for `ResourceForm` — same `display_order` trap."""
    data = {'name': 'Room 1', 'display_order': '0'}
    data.update(overrides)
    return data


# --------------------------------------------------------------------------- #
# ServiceForm — mass-assignment guard
# --------------------------------------------------------------------------- #

def test_tenant_is_not_a_service_form_field(tenant_a):
    form = ServiceForm(tenant=tenant_a)
    assert 'tenant' not in form.fields


def test_location_is_deliberately_a_service_form_field(tenant_a):
    """The ONE deliberate exception in the project — see the form's module
    docstring: choosing the location IS the product decision here.
    """
    form = ServiceForm(tenant=tenant_a)
    assert 'location' in form.fields
    assert form.fields['location'].required is False
    assert form.fields['location'].empty_label == 'All locations'


def test_posting_tenant_has_no_effect(tenant_a, tenant_b):
    form = ServiceForm(
        _service_data(tenant=str(tenant_b.pk)),
        tenant=tenant_a,
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.tenant_id == tenant_a.pk


# --------------------------------------------------------------------------- #
# ServiceForm — THE REGRESSION THAT MATTERED
# --------------------------------------------------------------------------- #

def test_edit_form_keeps_the_pinned_location_in_queryset_for_an_unassigned_editor(
    tenant_a, location_a1, location_a2, member_user, service_a2,
):
    """`member_user` is assigned ONLY to location A1; `service_a2` is pinned to
    A2. Editing it (e.g. fixing a typo in the description) must not silently
    widen the service to all locations because A2 fell out of the rendered
    `<select>` — A2 has to stay a selectable, and therefore SELECTED, choice.
    """
    request = _fake_request(tenant=tenant_a, user=member_user)

    form = ServiceForm(instance=service_a2, request=request)

    queryset_pks = set(form.fields['location'].queryset.values_list('pk', flat=True))
    assert location_a2.pk in queryset_pks
    # The union does not OVERGRANT — a third, unrelated location the editor is
    # not assigned to and that is not the instance's own value stays excluded.
    assert location_a1.pk in queryset_pks  # member_user IS assigned to A1


def test_edit_form_narrows_to_assignments_only_when_instance_has_no_location(
    tenant_a, location_a1, location_a2, member_user, service_all_a,
):
    """The union only kicks in for a PINNED instance. An all-locations service
    (`location_id is None`) has nothing to protect, so the queryset is exactly
    the editor's own assignments.
    """
    request = _fake_request(tenant=tenant_a, user=member_user)

    form = ServiceForm(instance=service_all_a, request=request)

    queryset_pks = set(form.fields['location'].queryset.values_list('pk', flat=True))
    assert queryset_pks == {location_a1.pk}


def test_edit_form_resubmitting_unrelated_field_keeps_the_pinned_location(
    tenant_a, location_a2, member_user, service_a2,
):
    """Round-trip proof: posting the STILL-SELECTED value (what a real browser
    would submit, because A2 renders as a selectable, selected option) saves
    successfully and does not widen the service to all locations.
    """
    request = _fake_request(tenant=tenant_a, user=member_user)

    form = ServiceForm(
        _service_data(
            name=service_a2.name,
            location=str(location_a2.pk),
            duration_minutes=str(service_a2.duration_minutes),
            display_order='5',
        ),
        instance=service_a2,
        request=request,
    )

    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.location_id == location_a2.pk
    assert obj.display_order == 5


def test_create_form_rejects_a_location_pk_outside_the_users_assignments(
    tenant_a, location_a2, member_user,
):
    """A POSTed location pk that is neither the (nonexistent, on create)
    instance value NOR one of the user's assignments is simply not a valid
    choice — `ModelChoiceField` rejects it before `clean()` ever runs.
    """
    request = _fake_request(tenant=tenant_a, user=member_user)

    form = ServiceForm(
        _service_data(name='New Service', location=str(location_a2.pk)),
        request=request,
    )

    assert not form.is_valid()
    assert 'location' in form.errors


# --------------------------------------------------------------------------- #
# ServiceForm — duplicate-name scoping
# --------------------------------------------------------------------------- #

def test_clean_rejects_duplicate_name_in_the_same_scope(tenant_a, location_a1, service_a1):
    form = ServiceForm(
        _service_data(name=service_a1.name, location=str(location_a1.pk)),
        tenant=tenant_a,
    )
    assert not form.is_valid()
    assert 'already offer a service called' in form.non_field_errors()[0]


def test_clean_rejects_duplicate_name_in_the_all_locations_scope(tenant_a, service_all_a):
    form = ServiceForm(
        _service_data(name=service_all_a.name),
        tenant=tenant_a,
    )
    assert not form.is_valid()
    assert 'already offer a service called' in form.non_field_errors()[0]


def test_clean_allows_same_name_at_a_different_location(
    tenant_a, location_a1, location_a2, service_a1,
):
    form = ServiceForm(
        _service_data(name=service_a1.name, location=str(location_a2.pk)),
        tenant=tenant_a,
    )
    assert form.is_valid(), form.errors


def test_clean_allows_same_name_across_all_locations_and_one_location(
    tenant_a, location_a1, service_all_a,
):
    form = ServiceForm(
        _service_data(name=service_all_a.name, location=str(location_a1.pk)),
        tenant=tenant_a,
    )
    assert form.is_valid(), form.errors


def test_clean_excludes_self_on_edit(tenant_a, location_a1, service_a1):
    form = ServiceForm(
        _service_data(name=service_a1.name, location=str(location_a1.pk), duration_minutes='45'),
        instance=service_a1,
        tenant=tenant_a,
    )
    assert form.is_valid(), form.errors


# --------------------------------------------------------------------------- #
# ServiceForm — duration_minutes bounds
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('value', [0, 1441, 5000])
def test_clean_duration_minutes_rejects_out_of_range(tenant_a, value):
    form = ServiceForm(_service_data(name='X', duration_minutes=str(value)), tenant=tenant_a)
    assert not form.is_valid()
    assert 'duration_minutes' in form.errors


@pytest.mark.parametrize('value', [1, 30, 1440])
def test_clean_duration_minutes_accepts_boundary_values(tenant_a, value):
    form = ServiceForm(_service_data(name='X', duration_minutes=str(value)), tenant=tenant_a)
    assert form.is_valid(), form.errors


# --------------------------------------------------------------------------- #
# ResourceForm — tenant/location are stamped, never rendered
# --------------------------------------------------------------------------- #

def test_tenant_and_location_are_not_resource_form_fields(tenant_a, location_a1):
    form = ResourceForm(tenant=tenant_a, location=location_a1)
    assert 'tenant' not in form.fields
    assert 'location' not in form.fields


def test_resource_form_save_stamps_tenant_and_location_from_the_request_not_post(
    tenant_a, tenant_b, location_a1, location_b1,
):
    form = ResourceForm(
        _resource_data(name='Room 9', tenant=str(tenant_b.pk), location=str(location_b1.pk)),
        tenant=tenant_a, location=location_a1,
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.tenant_id == tenant_a.pk
    assert obj.location_id == location_a1.pk


# --------------------------------------------------------------------------- #
# ResourceForm — clean_name enforces (location, name) by hand
# --------------------------------------------------------------------------- #

def test_clean_name_rejects_duplicate_at_the_same_location(tenant_a, location_a1, resource_a1):
    form = ResourceForm(_resource_data(name=resource_a1.name), tenant=tenant_a, location=location_a1)
    assert not form.is_valid()
    assert 'already has a resource called' in form.errors['name'][0]


def test_clean_name_allows_same_name_at_a_different_location(
    tenant_a, location_a1, location_a2, resource_a1,
):
    form = ResourceForm(_resource_data(name=resource_a1.name), tenant=tenant_a, location=location_a2)
    assert form.is_valid(), form.errors


def test_clean_name_excludes_self_on_edit(tenant_a, location_a1, resource_a1):
    form = ResourceForm(
        _resource_data(name=resource_a1.name, display_order='3'),
        instance=resource_a1, tenant=tenant_a, location=location_a1,
    )
    assert form.is_valid(), form.errors


def test_clean_name_requires_a_location(tenant_a):
    form = ResourceForm(_resource_data(name='Room 1'), tenant=tenant_a, location=None)
    assert not form.is_valid()
    assert 'Choose a location' in form.errors['name'][0]


def test_resource_name_is_required(tenant_a, location_a1):
    form = ResourceForm(_resource_data(name=''), tenant=tenant_a, location=location_a1)
    assert not form.is_valid()
    assert 'name' in form.errors
