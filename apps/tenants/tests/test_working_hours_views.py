"""View tests for sub-module 1.4 — Provider Working Hours.

`provider_hours_view` edits `accounts.User.provider_hours` (a JSON dict keyed by
location id) through `IntervalFormSet`, delegating every rule to
`apps.tenants.services`. `provider_hours_report_view` reads across every
(provider, assigned location) pair. Both must degrade gracefully — never 500 —
on a malformed stored JSON blob, since it can be written by a migration, a
fixture or an older version of the editor.
"""
import pytest
from django.test import Client
from django.urls import reverse

from apps.tenants.services import get_provider_intervals

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'tenants:{name}', args=args)


def _formset_data(rows):
    data = {
        'intervals-TOTAL_FORMS': str(len(rows)),
        'intervals-INITIAL_FORMS': '0',
        'intervals-MIN_NUM_FORMS': '0',
        'intervals-MAX_NUM_FORMS': '12',
    }
    for index, row in enumerate(rows):
        data[f'intervals-{index}-start_time'] = row.get('start_time', '')
        data[f'intervals-{index}-end_time'] = row.get('end_time', '')
        data[f'intervals-{index}-days'] = row.get('days', [])
    return data


# --------------------------------------------------------------------------- #
# provider_hours_view — auth / who may edit
# --------------------------------------------------------------------------- #

def test_hours_anonymous_redirects_to_login(client, member_user, location_a1):
    response = client.get(_url('provider_hours', member_user.pk, location_a1.pk))
    assert response.status_code == 302


def test_hours_get_renders_for_self(member_client, member_user, location_a1):
    """A staff-tier user may edit their OWN hours, no management tier needed."""
    response = member_client.get(_url('provider_hours', member_user.pk, location_a1.pk))
    assert response.status_code == 200
    assert 'tenants/hours/form.html' in [t.name for t in response.templates]
    assert response.context['is_self'] is True


def test_hours_blocks_editing_someone_elses_hours_as_staff(member_client, admin_user, location_a1):
    response = member_client.get(_url('provider_hours', admin_user.pk, location_a1.pk), follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('only edit your own' in m for m in messages_seen)


def test_hours_owner_can_edit_anyones_hours(client_a, member_user, location_a1):
    response = client_a.get(_url('provider_hours', member_user.pk, location_a1.pk))
    assert response.status_code == 200
    assert response.context['is_self'] is False


def test_hours_manager_can_edit_anyones_hours(manager_client, member_user, location_a1):
    response = manager_client.get(_url('provider_hours', member_user.pk, location_a1.pk))
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# provider_hours_view — cross-tenant IDOR
# --------------------------------------------------------------------------- #

def test_hours_cross_tenant_provider_pk_is_404(client_a, admin_b, location_a1):
    response = client_a.get(_url('provider_hours', admin_b.pk, location_a1.pk))
    assert response.status_code == 404


def test_hours_cross_tenant_location_pk_is_404(client_a, admin_user, location_b1):
    response = client_a.get(_url('provider_hours', admin_user.pk, location_b1.pk))
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# provider_hours_view — cross-LOCATION guard (same tenant, wrong assignment)
# --------------------------------------------------------------------------- #

def test_hours_unassigned_location_is_refused(client_a, provider_a1, location_a2):
    """`provider_a1` is assigned ONLY to A1 (own fixture) — A2 must be refused."""
    response = client_a.get(_url('provider_hours', provider_a1.pk, location_a2.pk), follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('not assigned to' in m for m in messages_seen)


def test_hours_unassigned_location_does_not_render_the_form(client_a, provider_a1, location_a2):
    response = client_a.get(_url('provider_hours', provider_a1.pk, location_a2.pk))
    assert response.status_code == 302
    assert response.url == reverse('tenants:staff_locations')


# --------------------------------------------------------------------------- #
# provider_hours_view — POST: save / clear / validate
# --------------------------------------------------------------------------- #

def test_hours_post_saves_intervals(client_a, provider_a1, location_a1):
    response = client_a.post(
        _url('provider_hours', provider_a1.pk, location_a1.pk),
        _formset_data([{'start_time': '09:00', 'end_time': '17:00', 'days': ['mon', 'tue']}]),
    )
    assert response.status_code == 302
    provider_a1.refresh_from_db()
    intervals = get_provider_intervals(provider_a1, location_a1)
    assert len(intervals) == 1
    assert intervals[0]['days'] == ['mon', 'tue']


def test_hours_post_rejects_end_before_start(client_a, provider_a1, location_a1):
    """A form-level `IntervalForm.clean()` error — the formset itself is
    invalid, so the view falls through to re-rendering rather than redirecting.
    """
    response = client_a.post(
        _url('provider_hours', provider_a1.pk, location_a1.pk),
        _formset_data([{'start_time': '17:00', 'end_time': '09:00', 'days': ['mon']}]),
    )
    assert response.status_code == 200
    formset = response.context['formset']
    assert not formset.is_valid()
    assert 'after the start time' in ' '.join(formset.forms[0].errors.get('end_time', []))
    provider_a1.refresh_from_db()
    assert get_provider_intervals(provider_a1, location_a1) == []


def test_hours_post_rejects_overlapping_intervals_same_day(client_a, provider_a1, location_a1):
    response = client_a.post(
        _url('provider_hours', provider_a1.pk, location_a1.pk),
        _formset_data([
            {'start_time': '09:00', 'end_time': '13:00', 'days': ['mon']},
            {'start_time': '12:00', 'end_time': '17:00', 'days': ['mon']},
        ]),
        follow=True,
    )
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('overlap' in m for m in messages_seen)
    provider_a1.refresh_from_db()
    assert get_provider_intervals(provider_a1, location_a1) == []


def test_hours_post_blank_row_is_skipped_not_an_error(client_a, provider_a1, location_a1):
    response = client_a.post(
        _url('provider_hours', provider_a1.pk, location_a1.pk),
        _formset_data([{'start_time': '', 'end_time': '', 'days': []}]),
    )
    assert response.status_code == 302


def test_hours_post_action_clear_stores_empty_list(client_a, provider_a1, location_a1):
    from apps.tenants.services import has_configured_hours, set_provider_hours

    set_provider_hours(provider_a1, location_a1.pk, [
        {'start_time': __import__('datetime').time(9, 0), 'end_time': __import__('datetime').time(17, 0), 'days': ['mon']},
    ])
    data = _formset_data([])
    data['action'] = 'clear'
    response = client_a.post(_url('provider_hours', provider_a1.pk, location_a1.pk), data)
    assert response.status_code == 302
    provider_a1.refresh_from_db()
    assert get_provider_intervals(provider_a1, location_a1) == []
    assert has_configured_hours(provider_a1, location_a1.pk) is True


def test_hours_post_csrf_enforced(admin_user, provider_a1, location_a1):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(
        _url('provider_hours', provider_a1.pk, location_a1.pk),
        _formset_data([{'start_time': '09:00', 'end_time': '17:00', 'days': ['mon']}]),
    )
    assert response.status_code == 403
    provider_a1.refresh_from_db()
    assert get_provider_intervals(provider_a1, location_a1) == []


# --------------------------------------------------------------------------- #
# provider_hours_view — malformed stored JSON must not 500
# --------------------------------------------------------------------------- #

def test_hours_get_survives_malformed_stored_json(client_a, provider_a1, location_a1):
    provider_a1.provider_hours = {str(location_a1.pk): 'not-a-list-of-intervals'}
    provider_a1.save(update_fields=['provider_hours'])

    response = client_a.get(_url('provider_hours', provider_a1.pk, location_a1.pk))
    assert response.status_code == 200


def test_hours_get_survives_entirely_non_dict_stored_json(client_a, provider_a1, location_a1):
    provider_a1.provider_hours = ['totally', 'wrong', 'shape']
    provider_a1.save(update_fields=['provider_hours'])

    response = client_a.get(_url('provider_hours', provider_a1.pk, location_a1.pk))
    assert response.status_code == 200


def test_hours_get_survives_malformed_entry_inside_a_valid_list(client_a, provider_a1, location_a1):
    provider_a1.provider_hours = {str(location_a1.pk): [{'start_time': None, 'end_time': 'garbage', 'days': 'mon'}]}
    provider_a1.save(update_fields=['provider_hours'])

    response = client_a.get(_url('provider_hours', provider_a1.pk, location_a1.pk))
    assert response.status_code == 200
    assert response.context['summary'] is not None


# --------------------------------------------------------------------------- #
# provider_hours_report_view
# --------------------------------------------------------------------------- #

def test_report_anonymous_redirects_to_login(client):
    response = client.get(_url('provider_hours_report'))
    assert response.status_code == 302


def test_report_blocks_staff_tier(member_client):
    response = member_client.get(_url('provider_hours_report'))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')


def test_report_open_to_owner(client_a):
    response = client_a.get(_url('provider_hours_report'))
    assert response.status_code == 200
    assert 'tenants/hours/report.html' in [t.name for t in response.templates]


def test_report_open_to_manager(manager_client):
    response = manager_client.get(_url('provider_hours_report'))
    assert response.status_code == 200


def test_report_rows_cover_every_assigned_location_for_a_provider(client_a, tenant_a, location_a1, location_a2, make_user):
    """A provider assigned to TWO locations must produce TWO rows — the same
    person legitimately works different days at different sites."""
    from apps.accounts.models import User

    two_site_provider = make_user(
        tenant_a, locations=[location_a1, location_a2], is_provider=True,
        email='twosite@acme-test.example',
    )
    response = client_a.get(_url('provider_hours_report'))
    rows = response.context['rows']
    providers_locations = {(r['provider'].pk, r['location'].pk) for r in rows}
    assert (two_site_provider.pk, location_a1.pk) in providers_locations
    assert (two_site_provider.pk, location_a2.pk) in providers_locations


def test_report_excludes_non_providers(client_a, admin_user):
    response = client_a.get(_url('provider_hours_report'))
    provider_pks = {r['provider'].pk for r in response.context['rows']}
    assert admin_user.pk not in provider_pks


def test_report_is_tenant_scoped(client_a, tenant_b, location_b1, make_user):
    from apps.accounts.models import UserLocation

    other_tenant_provider = make_user(tenant_b, is_provider=True, email='foreign-provider@globex-test.example')
    UserLocation.objects.create(tenant=tenant_b, user=other_tenant_provider, location=location_b1)

    response = client_a.get(_url('provider_hours_report'))
    provider_pks = {r['provider'].pk for r in response.context['rows']}
    assert other_tenant_provider.pk not in provider_pks


def test_report_survives_malformed_stored_json(client_a, provider_a1, location_a1):
    provider_a1.provider_hours = {'garbage': True, str(location_a1.pk): 12345}
    provider_a1.save(update_fields=['provider_hours'])

    response = client_a.get(_url('provider_hours_report'))
    assert response.status_code == 200
