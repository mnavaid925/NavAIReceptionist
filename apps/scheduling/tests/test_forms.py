"""Form tests for `scheduling.forms.ContactForm` (sub-module 4.1)."""
import datetime

import pytest
from django.utils import timezone

from apps.scheduling.forms import ContactForm
from apps.scheduling.models import Contact

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# Required-ish validation
# --------------------------------------------------------------------------- #

def test_rejects_wholly_empty_submission(tenant_a):
    form = ContactForm({}, tenant=tenant_a)

    assert not form.is_valid()
    assert (
        'Enter at least a name, a phone number or an email address.'
        in form.non_field_errors()
    )


def test_accepts_email_only_submission(tenant_a):
    """Neither name nor phone is individually required — any ONE of the four is."""
    form = ContactForm({'email': 'unnamed@example.test'}, tenant=tenant_a)
    assert form.is_valid(), form.errors


def test_rejects_future_date_of_birth(tenant_a):
    future = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
    form = ContactForm({'first_name': 'Ada', 'date_of_birth': future}, tenant=tenant_a)

    assert not form.is_valid()
    assert 'That date is in the future.' in form.errors['date_of_birth']


def test_accepts_todays_date_of_birth(tenant_a):
    today = timezone.localdate().isoformat()
    form = ContactForm({'first_name': 'Ada', 'date_of_birth': today}, tenant=tenant_a)
    assert form.is_valid(), form.errors


def test_rejects_unparseable_phone(tenant_a):
    form = ContactForm({'first_name': 'Ada', 'phone_e164': 'not-a-number'}, tenant=tenant_a)

    assert not form.is_valid()
    assert any(
        'does not look like a phone number' in message
        for message in form.errors['phone_e164']
    )


def test_normalizes_a_valid_phone_before_validation_passes(tenant_a):
    form = ContactForm({'first_name': 'Ada', 'phone_e164': '(312) 555-0142'}, tenant=tenant_a)
    assert form.is_valid(), form.errors
    assert form.cleaned_data['phone_e164'] == '+13125550142'


# --------------------------------------------------------------------------- #
# Mass-assignment guard: tenant / source / anonymized_at are NOT form fields
# --------------------------------------------------------------------------- #

def test_tenant_source_and_anonymized_at_are_not_form_fields(tenant_a):
    form = ContactForm(tenant=tenant_a)
    for name in ('tenant', 'source', 'anonymized_at'):
        assert name not in form.fields


def test_posting_tenant_source_and_anonymized_at_has_no_effect(tenant_a, tenant_b):
    data = {
        'first_name': 'Ada',
        'tenant': str(tenant_b.pk),
        'source': Contact.SOURCE_AI_PHONE,
        'anonymized_at': timezone.now().isoformat(),
    }
    form = ContactForm(data, tenant=tenant_a)

    assert form.is_valid(), form.errors
    obj = form.save()

    # Stamped from the REQUEST's tenant, never from POST data.
    assert obj.tenant_id == tenant_a.pk
    # `source` was never touched by the form — it keeps the model default.
    assert obj.source == Contact.SOURCE_MANUAL
    assert obj.anonymized_at is None


# --------------------------------------------------------------------------- #
# existing_with_same_phone
# --------------------------------------------------------------------------- #

def test_existing_with_same_phone_populates_for_same_tenant_duplicate(tenant_a):
    existing = Contact.objects.create(tenant=tenant_a, first_name='Dana', phone_e164='+13125550101')

    form = ContactForm({'first_name': 'Marcus', 'phone_e164': '312-555-0101'}, tenant=tenant_a)

    assert form.is_valid(), form.errors
    assert existing in form.existing_with_same_phone


def test_existing_with_same_phone_ignores_cross_tenant_duplicate(tenant_a, tenant_b):
    Contact.objects.create(tenant=tenant_b, first_name='Helena', phone_e164='+13125550101')

    form = ContactForm({'first_name': 'Marcus', 'phone_e164': '312-555-0101'}, tenant=tenant_a)

    assert form.is_valid(), form.errors
    assert form.existing_with_same_phone == []


def test_existing_with_same_phone_excludes_self_on_edit(tenant_a):
    contact = Contact.objects.create(tenant=tenant_a, first_name='Dana', phone_e164='+13125550101')

    form = ContactForm(
        {'first_name': 'Dana', 'phone_e164': '+13125550101'},
        instance=contact, tenant=tenant_a,
    )

    assert form.is_valid(), form.errors
    assert form.existing_with_same_phone == []
