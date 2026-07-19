"""Form tests for `AppointmentForm` / `AppointmentCancelForm` (sub-module 4.3).

Regression coverage for review finding 1 (the status guard) at the FORM layer —
the view-level guard lives in `test_booking_views.py`.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone as dj_timezone

from apps.accounts.models import User
from apps.scheduling.forms import AppointmentCancelForm, AppointmentForm
from apps.scheduling.models import Appointment

pytestmark = pytest.mark.django_db


def _fake_request(tenant=None, user=None, location=None):
    return SimpleNamespace(tenant=tenant, user=user, location=location)


def _future_str(minutes_ahead=2 * 24 * 60):
    """A `%Y-%m-%dT%H:%M` string N minutes from now, UTC-basis.

    Direct form construction (no `Client`, no `ActiveLocationMiddleware`) never
    activates a location's timezone, so the form's `from_current_timezone` reads
    `settings.TIME_ZONE` (UTC in tests) as the active zone — this matches that.
    """
    return (dj_timezone.now() + timedelta(minutes=minutes_ahead)).strftime('%Y-%m-%dT%H:%M')


def _appointment_data(**overrides):
    """Baseline valid POST data.

    `status` carries a model-level `default` but not `blank=True`, so — like
    `duration_minutes`/`display_order` on the catalogue forms — it is a
    REQUIRED form field regardless of the default, and must be present in every
    POST used in a validity assertion.
    """
    data = {
        'start_at': _future_str(),
        'status': Appointment.STATUS_SCHEDULED,
        'reason': '',
        'notes': '',
    }
    data.update(overrides)
    return data


# --------------------------------------------------------------------------- #
# Required fields / basic validity
# --------------------------------------------------------------------------- #

def test_contact_and_start_at_are_required(tenant_a, location_a1):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = AppointmentForm({'reason': ''}, request=request)
    assert not form.is_valid()
    assert 'contact' in form.errors
    assert 'start_at' in form.errors


def test_provider_and_resource_are_not_required(tenant_a, location_a1, contact_a, service_all_a):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = AppointmentForm(
        _appointment_data(contact=str(contact_a.pk), service=str(service_all_a.pk)),
        request=request,
    )
    assert form.is_valid(), form.errors


def test_invalid_start_at_string_fails_validation(tenant_a, location_a1, contact_a):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = AppointmentForm(
        _appointment_data(contact=str(contact_a.pk), start_at='not-a-date'),
        request=request,
    )
    assert not form.is_valid()
    assert 'start_at' in form.errors


# --------------------------------------------------------------------------- #
# System / provider-supplied fields are NOT rendered
# --------------------------------------------------------------------------- #

def test_tenant_and_location_are_not_form_fields(tenant_a, location_a1):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = AppointmentForm(request=request)
    assert 'tenant' not in form.fields
    assert 'location' not in form.fields


@pytest.mark.parametrize('field', [
    'end_at', 'source', 'cancelled_at', 'cancellation_reason',
])
def test_server_owned_fields_are_not_form_fields(tenant_a, location_a1, field):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = AppointmentForm(request=request)
    assert field not in form.fields


def test_posting_tenant_and_location_has_no_effect(tenant_a, tenant_b, location_a1, location_b1, contact_a, service_all_a):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = AppointmentForm(
        _appointment_data(
            contact=str(contact_a.pk), service=str(service_all_a.pk),
            tenant=str(tenant_b.pk), location=str(location_b1.pk),
        ),
        request=request,
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.tenant_id == tenant_a.pk
    assert obj.location_id == location_a1.pk


# --------------------------------------------------------------------------- #
# Review finding 1 — the status guard, at the form layer
# --------------------------------------------------------------------------- #

def test_status_choices_do_not_include_cancelled(tenant_a, location_a1):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = AppointmentForm(request=request)
    values = [value for value, _ in form.fields['status'].choices]
    assert Appointment.STATUS_CANCELLED not in values
    assert Appointment.STATUS_SCHEDULED in values
    assert Appointment.STATUS_COMPLETED in values
    assert Appointment.STATUS_NO_SHOW in values


def test_moving_status_off_cancelled_clears_cancellation_stamps(
    tenant_a, location_a1, contact_a, service_all_a,
):
    start = dj_timezone.now() + timedelta(days=2)
    obj = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a, service=service_all_a,
        start_at=start, end_at=start + timedelta(minutes=30),
        status=Appointment.STATUS_CANCELLED,
        cancelled_at=dj_timezone.now(), cancellation_reason='Changed their mind',
    )
    request = _fake_request(tenant=tenant_a, location=location_a1)

    form = AppointmentForm(
        _appointment_data(
            contact=str(contact_a.pk), service=str(service_all_a.pk),
            status=Appointment.STATUS_SCHEDULED,
            start_at=start.strftime('%Y-%m-%dT%H:%M'),
        ),
        instance=obj, request=request,
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.cancelled_at is None
    assert saved.cancellation_reason == ''


def test_keeping_status_untouched_leaves_no_cancellation_stamps_to_clear(
    tenant_a, location_a1, contact_a, service_all_a,
):
    """Sanity check: a normal scheduled -> confirmed edit never had stamps to
    begin with, and the clearing logic is a no-op rather than an error.
    """
    start = dj_timezone.now() + timedelta(days=2)
    obj = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a, service=service_all_a,
        start_at=start, end_at=start + timedelta(minutes=30),
        status=Appointment.STATUS_SCHEDULED,
    )
    request = _fake_request(tenant=tenant_a, location=location_a1)

    form = AppointmentForm(
        _appointment_data(
            contact=str(contact_a.pk), service=str(service_all_a.pk),
            status=Appointment.STATUS_CONFIRMED,
            start_at=start.strftime('%Y-%m-%dT%H:%M'),
        ),
        instance=obj, request=request,
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.status == Appointment.STATUS_CONFIRMED
    assert saved.cancelled_at is None


# --------------------------------------------------------------------------- #
# clean() — resource-required and the unlocked overlap pre-check
# --------------------------------------------------------------------------- #

def test_service_requiring_a_resource_without_one_is_rejected(
    tenant_a, location_a1, contact_a, make_service,
):
    service = make_service(tenant_a, name='Needs Room', requires_resource=True)
    request = _fake_request(tenant=tenant_a, location=location_a1)

    form = AppointmentForm(
        _appointment_data(contact=str(contact_a.pk), service=str(service.pk)),
        request=request,
    )
    assert not form.is_valid()
    assert 'resource' in form.errors


def test_clean_rejects_an_overlapping_time_for_the_same_resource(
    tenant_a, location_a1, contact_a, service_all_a, resource_a1,
):
    start = dj_timezone.now() + timedelta(days=2)
    Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        service=service_all_a, resource=resource_a1,
        start_at=start, end_at=start + timedelta(minutes=30),
    )
    request = _fake_request(tenant=tenant_a, location=location_a1)

    form = AppointmentForm(
        _appointment_data(
            contact=str(contact_a.pk), service=str(service_all_a.pk),
            resource=str(resource_a1.pk),
            start_at=start.strftime('%Y-%m-%dT%H:%M'),
        ),
        request=request,
    )
    assert not form.is_valid()
    assert 'already taken' in form.non_field_errors()[0]


def test_clean_excludes_self_on_edit_so_a_booking_can_be_resaved(
    tenant_a, location_a1, contact_a, service_all_a, resource_a1,
):
    start = dj_timezone.now() + timedelta(days=2)
    obj = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        service=service_all_a, resource=resource_a1,
        start_at=start, end_at=start + timedelta(minutes=30),
    )
    request = _fake_request(tenant=tenant_a, location=location_a1)

    form = AppointmentForm(
        _appointment_data(
            contact=str(contact_a.pk), service=str(service_all_a.pk),
            resource=str(resource_a1.pk), reason='Updated reason',
            start_at=start.strftime('%Y-%m-%dT%H:%M'),
        ),
        instance=obj, request=request,
    )
    assert form.is_valid(), form.errors


def test_clean_start_at_rejects_the_past_on_a_new_booking(tenant_a, location_a1, contact_a, service_all_a):
    past = dj_timezone.now() - timedelta(days=1)
    request = _fake_request(tenant=tenant_a, location=location_a1)

    form = AppointmentForm(
        _appointment_data(
            contact=str(contact_a.pk), service=str(service_all_a.pk),
            start_at=past.strftime('%Y-%m-%dT%H:%M'),
        ),
        request=request,
    )
    assert not form.is_valid()
    assert 'start_at' in form.errors


def test_clean_start_at_allows_the_past_when_editing(tenant_a, location_a1, contact_a, service_all_a):
    past = dj_timezone.now() - timedelta(days=1)
    obj = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a, service=service_all_a,
        start_at=past, end_at=past + timedelta(minutes=30),
        status=Appointment.STATUS_COMPLETED,
    )
    request = _fake_request(tenant=tenant_a, location=location_a1)

    form = AppointmentForm(
        _appointment_data(
            contact=str(contact_a.pk), service=str(service_all_a.pk),
            status=Appointment.STATUS_COMPLETED,
            start_at=past.strftime('%Y-%m-%dT%H:%M'),
        ),
        instance=obj, request=request,
    )
    assert form.is_valid(), form.errors


# --------------------------------------------------------------------------- #
# FK querysets — tenant/location scoping
# --------------------------------------------------------------------------- #

def test_contact_queryset_is_tenant_scoped_and_excludes_anonymized(
    tenant_a, location_a1, contact_a, contact_b, make_contact,
):
    erased = make_contact(tenant_a, first_name='Erased', anonymized_at=dj_timezone.now())
    request = _fake_request(tenant=tenant_a, location=location_a1)

    form = AppointmentForm(request=request)
    pks = set(form.fields['contact'].queryset.values_list('pk', flat=True))
    assert contact_a.pk in pks
    assert contact_b.pk not in pks
    assert erased.pk not in pks


def test_service_queryset_is_additive_own_location_plus_all_locations(
    tenant_a, location_a1, service_a1, service_a2, service_all_a, service_b,
):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = AppointmentForm(request=request)
    pks = set(form.fields['service'].queryset.values_list('pk', flat=True))
    assert service_a1.pk in pks
    assert service_all_a.pk in pks
    assert service_a2.pk not in pks
    assert service_b.pk not in pks


def test_resource_queryset_is_scoped_to_the_active_location(
    tenant_a, location_a1, resource_a1, resource_a2, resource_b,
):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = AppointmentForm(request=request)
    pks = set(form.fields['resource'].queryset.values_list('pk', flat=True))
    assert resource_a1.pk in pks
    assert resource_a2.pk not in pks
    assert resource_b.pk not in pks


def test_provider_queryset_is_scoped_to_the_active_location(
    tenant_a, location_a1, location_a2, provider_a1, make_provider,
):
    other_location_provider = make_provider(tenant_a, location_a2, email='p2@acme-test.example')
    request = _fake_request(tenant=tenant_a, location=location_a1)

    form = AppointmentForm(request=request)
    pks = set(form.fields['provider'].queryset.values_list('pk', flat=True))
    assert provider_a1.pk in pks
    assert other_location_provider.pk not in pks


# --------------------------------------------------------------------------- #
# Review finding 5 — a suspended provider is unbookable through this form too
# --------------------------------------------------------------------------- #

def test_provider_queryset_excludes_a_suspended_provider(
    tenant_a, location_a1, provider_a1, make_provider,
):
    suspended = make_provider(
        tenant_a, location_a1, email='suspended@acme-test.example',
        status=User.STATUS_SUSPENDED,
    )
    request = _fake_request(tenant=tenant_a, location=location_a1)

    form = AppointmentForm(request=request)
    pks = set(form.fields['provider'].queryset.values_list('pk', flat=True))
    assert provider_a1.pk in pks
    assert suspended.pk not in pks


# --------------------------------------------------------------------------- #
# AppointmentCancelForm
# --------------------------------------------------------------------------- #

def test_cancel_form_reason_is_optional():
    form = AppointmentCancelForm({})
    assert form.is_valid()
    assert form.cleaned_data['reason'] == ''


def test_cancel_form_accepts_a_reason():
    form = AppointmentCancelForm({'reason': 'Caller rang to cancel'})
    assert form.is_valid()
    assert form.cleaned_data['reason'] == 'Caller rang to cancel'
