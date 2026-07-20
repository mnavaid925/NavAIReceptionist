"""Model tests for `scheduling.CallbackRequest` (sub-module 4.5).

Also covers the contact-erasure cascade `_scrub_linked_callback_requests()` —
`Contact.anonymize()`, `Contact.delete()` and `ContactAdmin.delete_queryset` all
route through it, and it is the callback queue's only defence against orphaned
caller PII once a contact is gone.
"""
from django.test import RequestFactory

import pytest

from apps.scheduling.admin import ContactAdmin
from apps.scheduling.models import CallbackRequest, Contact

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# Defaults and choices
# --------------------------------------------------------------------------- #

def test_default_status_is_pending(tenant_a, location_a1):
    obj = CallbackRequest.objects.create(tenant=tenant_a, location=location_a1)
    assert obj.status == CallbackRequest.STATUS_PENDING


def test_default_source_is_ai_phone(tenant_a, location_a1):
    obj = CallbackRequest.objects.create(tenant=tenant_a, location=location_a1)
    assert obj.source == CallbackRequest.SOURCE_AI_PHONE


def test_contact_is_nullable(tenant_a, location_a1):
    obj = CallbackRequest.objects.create(tenant=tenant_a, location=location_a1)
    assert obj.contact_id is None


def test_ordering_is_newest_created_first(tenant_a, location_a1, make_callback):
    from datetime import timedelta

    from django.utils import timezone as dj_timezone

    older = make_callback(tenant_a, location_a1, caller_name='Older')
    newer = make_callback(tenant_a, location_a1, caller_name='Newer')
    # `auto_now_add` stamps both from the real clock, which on Windows can tie
    # at its ~15ms resolution when two rows are created back to back in the same
    # test — back-date one explicitly so the ordering assertion is deterministic
    # rather than a hidden race on host clock granularity.
    CallbackRequest.objects.filter(pk=older.pk).update(
        created_at=dj_timezone.now() - timedelta(hours=1),
    )

    assert list(CallbackRequest.objects.filter(tenant=tenant_a)) == [newer, older]


def test_str_renders_display_caller_and_status(tenant_a, location_a1):
    obj = CallbackRequest.objects.create(
        tenant=tenant_a, location=location_a1, caller_name='Dana',
        status=CallbackRequest.STATUS_CONTACTED,
    )
    assert str(obj) == 'Dana — Contacted'


# --------------------------------------------------------------------------- #
# contact SET_NULL — the operational-queue-item distinction from Appointment
# --------------------------------------------------------------------------- #

def test_contact_delete_sets_null_rather_than_cascading(tenant_a, location_a1, contact_a):
    obj = CallbackRequest.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
    )
    contact_a.delete()
    obj.refresh_from_db()
    assert obj.contact_id is None
    assert CallbackRequest.objects.filter(pk=obj.pk).exists()


# --------------------------------------------------------------------------- #
# display_caller — contact -> caller_name -> placeholder
# --------------------------------------------------------------------------- #

def test_display_caller_uses_contact_display_name_when_linked(tenant_a, location_a1, contact_a):
    obj = CallbackRequest.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a, caller_name='Ignored',
    )
    assert obj.display_caller == contact_a.display_name


def test_display_caller_falls_back_to_caller_name_when_unlinked(tenant_a, location_a1):
    obj = CallbackRequest.objects.create(
        tenant=tenant_a, location=location_a1, caller_name='Dana Caller',
    )
    assert obj.display_caller == 'Dana Caller'


def test_display_caller_falls_back_to_placeholder_when_nothing_is_known(tenant_a, location_a1):
    obj = CallbackRequest.objects.create(tenant=tenant_a, location=location_a1)
    assert obj.display_caller == 'Unidentified caller'


# --------------------------------------------------------------------------- #
# dialable_phone — the exact edge cases the spec calls out
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('caller_phone, expected', [
    ('', ''),
    ('+1 312 555 0142', '+1 312 555 0142'),
    ('312 555 0142 x204', ''),
    ('ask for Dana', ''),
])
def test_dialable_phone_edge_cases(tenant_a, location_a1, caller_phone, expected):
    obj = CallbackRequest.objects.create(
        tenant=tenant_a, location=location_a1, caller_phone=caller_phone,
    )
    assert obj.dialable_phone == expected


def test_dialable_phone_strips_whitespace_before_checking(tenant_a, location_a1):
    obj = CallbackRequest.objects.create(
        tenant=tenant_a, location=location_a1, caller_phone='  +13125550142  ',
    )
    assert obj.dialable_phone == '+13125550142'


# --------------------------------------------------------------------------- #
# is_resolved — closed alone, not contacted
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('status, expected', [
    (CallbackRequest.STATUS_PENDING, False),
    (CallbackRequest.STATUS_CONTACTED, False),
    (CallbackRequest.STATUS_CLOSED, True),
])
def test_is_resolved_keys_on_closed_only(tenant_a, location_a1, status, expected):
    obj = CallbackRequest.objects.create(tenant=tenant_a, location=location_a1, status=status)
    assert obj.is_resolved is expected


# --------------------------------------------------------------------------- #
# The contact-erasure cascade — anonymize() / delete() / admin bulk delete
# --------------------------------------------------------------------------- #

def test_anonymize_scrubs_caller_identity_but_keeps_reason_and_notes(
    tenant_a, location_a1, contact_a,
):
    callback = CallbackRequest.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        caller_name='Priya Raman', caller_phone='+13125550142',
        reason='Wants to move Tuesday to Thursday', notes='Left a voicemail',
    )

    contact_a.anonymize()
    callback.refresh_from_db()

    assert callback.caller_name == ''
    assert callback.caller_phone == ''
    assert callback.reason == 'Wants to move Tuesday to Thursday'
    assert callback.notes == 'Left a voicemail'
    # The FK itself nulls independently (SET_NULL fires on the hard-delete path
    # only; anonymize() never deletes the contact row), so it is untouched here.
    assert callback.contact_id == contact_a.pk


def test_anonymize_scrub_is_tenant_scoped(tenant_a, tenant_b, location_a1, location_b1, make_contact):
    """The cascade must never reach across tenants even by accident — it keys
    on `contact=self` AND `tenant_id=self.tenant_id` explicitly.
    """
    contact = make_contact(tenant_a, first_name='Priya')
    other_tenant_callback = CallbackRequest.objects.create(
        tenant=tenant_b, location=location_b1, caller_name='Unrelated',
    )

    contact.anonymize()

    other_tenant_callback.refresh_from_db()
    assert other_tenant_callback.caller_name == 'Unrelated'


def test_anonymize_is_idempotent_for_the_cascade(tenant_a, location_a1, contact_a):
    callback = CallbackRequest.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        caller_name='Priya Raman', caller_phone='+13125550142', notes='First pass',
    )

    contact_a.anonymize()
    contact_a.anonymize()  # second call must be a safe no-op

    callback.refresh_from_db()
    assert callback.caller_name == ''
    assert callback.caller_phone == ''
    assert callback.notes == 'First pass'


def test_hard_delete_scrubs_caller_identity_but_keeps_reason_and_notes(
    tenant_a, location_a1, contact_a,
):
    callback = CallbackRequest.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        caller_name='Priya Raman', caller_phone='+13125550142',
        reason='Wants to move Tuesday to Thursday', notes='Left a voicemail',
    )

    contact_a.delete()
    callback.refresh_from_db()

    assert callback.caller_name == ''
    assert callback.caller_phone == ''
    assert callback.reason == 'Wants to move Tuesday to Thursday'
    assert callback.notes == 'Left a voicemail'
    # SET_NULL fires for real here — the contact row is actually gone.
    assert callback.contact_id is None
    assert not Contact.objects.filter(pk=contact_a.pk).exists()


def test_admin_bulk_delete_queryset_also_runs_the_scrub(tenant_a, location_a1, contact_a):
    """`ContactAdmin.delete_queryset` iterates and calls `.delete()` per row so
    the changelist's "Delete selected" action does not silently skip the
    cascade the way a bulk `queryset.delete()` would.
    """
    callback = CallbackRequest.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        caller_name='Priya Raman', caller_phone='+13125550142', notes='Kept note',
    )

    request = RequestFactory().get('/admin/scheduling/contact/')
    ContactAdmin(Contact, admin_site=None).delete_queryset(
        request, Contact.objects.filter(pk=contact_a.pk),
    )

    callback.refresh_from_db()
    assert callback.caller_name == ''
    assert callback.caller_phone == ''
    assert callback.notes == 'Kept note'
    assert not Contact.objects.filter(pk=contact_a.pk).exists()


def test_plain_queryset_bulk_delete_would_orphan_the_identity_without_the_admin_override(
    tenant_a, location_a1, contact_a,
):
    """Documents WHY the admin override exists: Django's queryset `.delete()`
    deletes in bulk without instantiating rows, so `Contact.delete()` (and its
    scrub) never runs. The FK still nulls (`SET_NULL`), which is the trap.
    """
    callback = CallbackRequest.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        caller_name='Priya Raman', caller_phone='+13125550142',
    )

    Contact.objects.filter(pk=contact_a.pk).delete()

    callback.refresh_from_db()
    assert callback.contact_id is None
    # The bulk path is exactly what does NOT get scrubbed — proving the need
    # for `ContactAdmin.delete_queryset`'s row-by-row override above.
    assert callback.caller_name == 'Priya Raman'
