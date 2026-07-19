"""Model tests for `scheduling.Contact` (sub-module 4.1)."""
import datetime

import pytest
from django.utils import timezone

from apps.scheduling.models import Contact

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# save() — phone normalisation on write
# --------------------------------------------------------------------------- #

def test_save_normalizes_phone_on_create(tenant_a):
    contact = Contact.objects.create(tenant=tenant_a, phone_e164='(312) 555-0142')
    assert contact.phone_e164 == '+13125550142'


def test_save_normalizes_phone_on_update(tenant_a):
    contact = Contact.objects.create(
        tenant=tenant_a, first_name='Jo', phone_e164='+13125550142',
    )
    contact.phone_e164 = '312-555-0199'
    contact.save()
    contact.refresh_from_db()
    assert contact.phone_e164 == '+13125550199'


def test_save_normalizes_junk_phone_to_blank(tenant_a):
    contact = Contact.objects.create(tenant=tenant_a, first_name='Jo', phone_e164='abc')
    assert contact.phone_e164 == ''


# --------------------------------------------------------------------------- #
# display_name — fallback chain
# --------------------------------------------------------------------------- #

def test_display_name_uses_full_name_when_present(tenant_a):
    contact = Contact.objects.create(tenant=tenant_a, first_name='Ada', last_name='Lovelace')
    assert contact.display_name == 'Ada Lovelace'


def test_display_name_falls_back_to_phone_when_no_name(tenant_a):
    contact = Contact.objects.create(tenant=tenant_a, phone_e164='+13125550142')
    assert contact.display_name == '+13125550142'


def test_display_name_falls_back_to_unknown_caller(tenant_a):
    contact = Contact.objects.create(tenant=tenant_a)
    assert contact.display_name == 'Unknown caller'


def test_display_name_is_erased_contact_once_anonymized(tenant_a):
    contact = Contact.objects.create(
        tenant=tenant_a, first_name='Ada', last_name='Lovelace', phone_e164='+13125550142',
    )
    contact.anonymize()
    # Erased takes priority even though the fields are now blank — display_name
    # must not fall through to "Unknown caller" for a contact who WAS known.
    assert contact.display_name == 'Erased contact'


def test_str_delegates_to_display_name(tenant_a):
    contact = Contact.objects.create(tenant=tenant_a, first_name='Ada', last_name='Lovelace')
    assert str(contact) == contact.display_name == 'Ada Lovelace'


# --------------------------------------------------------------------------- #
# has_name / is_anonymized
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('first_name, last_name, expected', [
    ('Ada', '', True),
    ('', 'Lovelace', True),
    ('Ada', 'Lovelace', True),
    ('', '', False),
])
def test_has_name(tenant_a, first_name, last_name, expected):
    contact = Contact.objects.create(
        tenant=tenant_a, first_name=first_name, last_name=last_name,
        phone_e164='+13125550142',
    )
    assert contact.has_name is expected


def test_is_anonymized_false_by_default(tenant_a):
    contact = Contact.objects.create(tenant=tenant_a, first_name='Ada')
    assert contact.is_anonymized is False


def test_is_anonymized_true_after_anonymize(tenant_a):
    contact = Contact.objects.create(tenant=tenant_a, first_name='Ada')
    contact.anonymize()
    assert contact.is_anonymized is True


# --------------------------------------------------------------------------- #
# anonymize()
# --------------------------------------------------------------------------- #

def test_anonymize_blanks_identifying_fields_and_stamps_timestamp(tenant_a):
    contact = Contact.objects.create(
        tenant=tenant_a, first_name='Ada', last_name='Lovelace',
        phone_e164='+13125550142', email='ada@example.test',
        date_of_birth=datetime.date(1990, 1, 1), notes='VIP client',
    )
    before = timezone.now()

    contact.anonymize()
    contact.refresh_from_db()

    assert contact.first_name == ''
    assert contact.last_name == ''
    assert contact.phone_e164 == ''
    assert contact.email == ''
    assert contact.date_of_birth is None
    assert contact.notes == ''
    assert contact.anonymized_at is not None
    assert contact.anonymized_at >= before
    # The row survives with its PRIMARY KEY intact — Appointment.contact is
    # PROTECT, so the row must still be there for history to hang off it.
    assert Contact.objects.filter(pk=contact.pk).exists()


def test_anonymize_twice_preserves_original_timestamp(tenant_a):
    contact = Contact.objects.create(tenant=tenant_a, first_name='Ada')

    contact.anonymize()
    first_timestamp = contact.anonymized_at
    assert first_timestamp is not None

    # A second call must be a no-op — the guard in anonymize() returns early
    # once anonymized_at is already set, so the ORIGINAL timestamp survives.
    contact.anonymize()
    assert contact.anonymized_at == first_timestamp

    contact.refresh_from_db()
    assert contact.anonymized_at == first_timestamp


def test_anonymize_returns_the_instance(tenant_a):
    contact = Contact.objects.create(tenant=tenant_a, first_name='Ada')
    assert contact.anonymize() is contact


# --------------------------------------------------------------------------- #
# phone_e164 is NOT unique
# --------------------------------------------------------------------------- #

def test_phone_e164_not_unique_within_a_tenant(tenant_a):
    first = Contact.objects.create(tenant=tenant_a, first_name='Dana', phone_e164='+13125550101')
    second = Contact.objects.create(tenant=tenant_a, first_name='Marcus', phone_e164='+13125550101')

    assert first.pk != second.pk
    assert Contact.objects.filter(tenant=tenant_a, phone_e164='+13125550101').count() == 2
