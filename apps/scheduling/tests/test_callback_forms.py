"""Form tests for `CallbackRequestForm` / `CallbackResolveForm` (sub-module 4.5)."""
from types import SimpleNamespace

import pytest
from django.utils import timezone as dj_timezone

from apps.scheduling.forms import CallbackRequestForm, CallbackResolveForm
from apps.scheduling.models import CallbackRequest

pytestmark = pytest.mark.django_db


def _fake_request(tenant=None, user=None, location=None):
    return SimpleNamespace(tenant=tenant, user=user, location=location)


# --------------------------------------------------------------------------- #
# System / provider-supplied fields are NOT rendered
# --------------------------------------------------------------------------- #

def test_tenant_and_location_are_not_form_fields(tenant_a, location_a1):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(request=request)
    assert 'tenant' not in form.fields
    assert 'location' not in form.fields


def test_source_is_not_a_form_field(tenant_a, location_a1):
    """`source` is the provenance record, server-stamped — never editable."""
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(request=request)
    assert 'source' not in form.fields


# --------------------------------------------------------------------------- #
# clean() — at least one identifying field
# --------------------------------------------------------------------------- #

def test_empty_callback_with_no_contact_name_or_phone_is_rejected(tenant_a, location_a1):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(
        {'caller_name': '', 'caller_phone': '', 'reason': '', 'status': CallbackRequest.STATUS_PENDING, 'notes': ''},
        request=request,
    )
    assert not form.is_valid()
    assert form.non_field_errors()


def test_caller_name_alone_is_sufficient(tenant_a, location_a1):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(
        {'caller_name': 'Dana', 'caller_phone': '', 'reason': '', 'status': CallbackRequest.STATUS_PENDING, 'notes': ''},
        request=request,
    )
    assert form.is_valid(), form.errors


def test_caller_phone_alone_is_sufficient(tenant_a, location_a1):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(
        {'caller_name': '', 'caller_phone': '3125550142', 'reason': '', 'status': CallbackRequest.STATUS_PENDING, 'notes': ''},
        request=request,
    )
    assert form.is_valid(), form.errors


def test_contact_alone_is_sufficient(tenant_a, location_a1, contact_a):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(
        {
            'contact': str(contact_a.pk), 'caller_name': '', 'caller_phone': '',
            'reason': '', 'status': CallbackRequest.STATUS_PENDING, 'notes': '',
        },
        request=request,
    )
    assert form.is_valid(), form.errors


# --------------------------------------------------------------------------- #
# clean_caller_phone — normalise ONLY pure dialling characters, never raise
# --------------------------------------------------------------------------- #

def test_caller_phone_pure_digits_is_normalized(tenant_a, location_a1):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(
        {
            'caller_name': 'Dana', 'caller_phone': '(312) 555-0142',
            'reason': '', 'status': CallbackRequest.STATUS_PENDING, 'notes': '',
        },
        request=request,
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data['caller_phone'] == '+13125550142'


def test_caller_phone_with_extension_is_kept_verbatim(tenant_a, location_a1):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(
        {
            'caller_name': 'Dana', 'caller_phone': '312 555 0142 x204',
            'reason': '', 'status': CallbackRequest.STATUS_PENDING, 'notes': '',
        },
        request=request,
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data['caller_phone'] == '312 555 0142 x204'


def test_caller_phone_free_text_is_kept_verbatim_and_never_raises(tenant_a, location_a1):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(
        {
            'caller_name': '', 'caller_phone': 'ask for Dana',
            'reason': '', 'status': CallbackRequest.STATUS_PENDING, 'notes': '',
        },
        request=request,
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data['caller_phone'] == 'ask for Dana'


def test_caller_phone_blank_is_fine(tenant_a, location_a1):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(
        {
            'caller_name': 'Dana', 'caller_phone': '',
            'reason': '', 'status': CallbackRequest.STATUS_PENDING, 'notes': '',
        },
        request=request,
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data['caller_phone'] == ''


# --------------------------------------------------------------------------- #
# contact queryset — tenant-scoped (not location-scoped) and excludes anonymized
# --------------------------------------------------------------------------- #

def test_contact_queryset_is_tenant_scoped_not_location_scoped(
    tenant_a, location_a1, location_a2, contact_a,
):
    """Invariant 1 / the docstring: a caller who normally visits another site
    can still ask THIS site to ring them back, so `contact` is narrowed to the
    tenant only — NOT the active location.
    """
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(request=request)
    pks = set(form.fields['contact'].queryset.values_list('pk', flat=True))
    assert contact_a.pk in pks


def test_contact_queryset_excludes_another_tenant(tenant_a, location_a1, contact_a, contact_b):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(request=request)
    pks = set(form.fields['contact'].queryset.values_list('pk', flat=True))
    assert contact_a.pk in pks
    assert contact_b.pk not in pks


def test_contact_queryset_excludes_an_anonymized_contact(
    tenant_a, location_a1, contact_a, make_contact,
):
    erased = make_contact(tenant_a, first_name='Erased', anonymized_at=dj_timezone.now())
    request = _fake_request(tenant=tenant_a, location=location_a1)

    form = CallbackRequestForm(request=request)
    pks = set(form.fields['contact'].queryset.values_list('pk', flat=True))
    assert contact_a.pk in pks
    assert erased.pk not in pks


def test_contact_is_not_required(tenant_a, location_a1):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(request=request)
    assert form.fields['contact'].required is False
    assert form.fields['contact'].empty_label == 'Unidentified caller'


# --------------------------------------------------------------------------- #
# Posting tenant/location/source has no effect
# --------------------------------------------------------------------------- #

def test_posting_tenant_and_location_has_no_effect(
    tenant_a, tenant_b, location_a1, location_b1,
):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(
        {
            'caller_name': 'Dana', 'caller_phone': '', 'reason': '',
            'status': CallbackRequest.STATUS_PENDING, 'notes': '',
            'tenant': str(tenant_b.pk), 'location': str(location_b1.pk),
        },
        request=request,
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.tenant_id == tenant_a.pk
    assert obj.location_id == location_a1.pk


def test_posting_source_has_no_effect(tenant_a, location_a1):
    request = _fake_request(tenant=tenant_a, location=location_a1)
    form = CallbackRequestForm(
        {
            'caller_name': 'Dana', 'caller_phone': '', 'reason': '',
            'status': CallbackRequest.STATUS_PENDING, 'notes': '',
            'source': CallbackRequest.SOURCE_AI_PHONE,
        },
        request=request,
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    # The view stamps `source` itself (SOURCE_MANUAL on create); the form alone
    # leaves the model default (`ai_phone`) untouched either way, since `source`
    # is not one of its fields at all.
    assert 'source' not in form.fields
    assert obj.source == CallbackRequest.SOURCE_AI_PHONE


# --------------------------------------------------------------------------- #
# CallbackResolveForm — only moves a callback FORWARD
# --------------------------------------------------------------------------- #

def test_resolve_form_choices_are_contacted_and_closed_only(tenant_a, location_a1):
    obj = CallbackRequest.objects.create(tenant=tenant_a, location=location_a1, caller_name='Dana')
    form = CallbackResolveForm(instance=obj)
    values = [value for value, _ in form.fields['status'].choices]
    assert values == [CallbackRequest.STATUS_CONTACTED, CallbackRequest.STATUS_CLOSED]
    assert CallbackRequest.STATUS_PENDING not in values


def test_resolve_form_refuses_pending(tenant_a, location_a1):
    obj = CallbackRequest.objects.create(tenant=tenant_a, location=location_a1, caller_name='Dana')
    form = CallbackResolveForm(
        {'status': CallbackRequest.STATUS_PENDING, 'notes': ''}, instance=obj,
    )
    assert not form.is_valid()
    assert 'status' in form.errors


def test_resolve_form_accepts_contacted(tenant_a, location_a1):
    obj = CallbackRequest.objects.create(tenant=tenant_a, location=location_a1, caller_name='Dana')
    form = CallbackResolveForm(
        {'status': CallbackRequest.STATUS_CONTACTED, 'notes': 'Left a voicemail'}, instance=obj,
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.status == CallbackRequest.STATUS_CONTACTED
    assert saved.notes == 'Left a voicemail'


def test_resolve_form_accepts_closed(tenant_a, location_a1):
    obj = CallbackRequest.objects.create(tenant=tenant_a, location=location_a1, caller_name='Dana')
    form = CallbackResolveForm(
        {'status': CallbackRequest.STATUS_CLOSED, 'notes': 'Rang back, all set'}, instance=obj,
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.status == CallbackRequest.STATUS_CLOSED
