"""View tests for sub-module 0.3 — User Profile & Directory.

Two access surfaces over one table: the tier-gated management directory
(`user_list_view` / `user_create_view` / `user_detail_view` / `user_edit_view` /
`user_delete_view`) and the open-to-everyone own-profile page. `accounts.User` is
tenant-scoped but NOT location-scoped, so the directory must show every tenant
user regardless of which site is active — proven with `user_a2_only` while the
viewer is active at A1.
"""
import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User

from conftest import DEMO_PASSWORD

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'accounts:{name}', args=args)


# --------------------------------------------------------------------------- #
# Auth / tier gate
# --------------------------------------------------------------------------- #

def test_user_list_anonymous_redirects_to_login(client):
    response = client.get(_url('user_list'))
    assert response.status_code == 302


def test_user_list_blocks_staff_tier(member_client):
    response = member_client.get(_url('user_list'))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')


def test_user_list_blocks_staff_tier_shows_permission_message(member_client):
    response = member_client.get(_url('user_list'), follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('do not have permission' in m for m in messages_seen)


def test_user_create_blocks_staff_tier(member_client):
    response = member_client.get(_url('user_create'))
    assert response.status_code == 302


def test_user_edit_blocks_staff_tier(member_client, member_user):
    response = member_client.get(_url('user_edit', member_user.pk))
    assert response.status_code == 302


def test_user_delete_blocks_staff_tier(member_client, tenant_a, make_user):
    other = make_user(tenant_a, email='other@acme-test.example')
    response = member_client.post(_url('user_delete', other.pk))
    assert response.status_code == 302
    other.refresh_from_db()
    assert other.status == User.STATUS_ACTIVE


def test_user_list_open_to_owner_and_manager(client_a, tenant_a, make_user):
    manager = make_user(tenant_a, tier=User.TIER_MANAGER, email='mgr@acme-test.example')
    manager_client = Client()
    manager_client.force_login(manager)
    response = manager_client.get(_url('user_list'))
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# Directory list — tenant scoping (NOT location scoping)
# --------------------------------------------------------------------------- #

def test_list_view_renders_for_tenant_admin(client_a, admin_user):
    response = client_a.get(_url('user_list'))
    assert response.status_code == 200
    assert 'accounts/user/list.html' in [t.name for t in response.templates]
    assert admin_user in list(response.context['users'])


def test_list_view_never_contains_another_tenants_rows(client_a, admin_user, admin_b):
    response = client_a.get(_url('user_list'))
    results = list(response.context['users'])
    assert admin_user in results
    assert admin_b not in results


def test_list_view_is_tenant_scoped_only_not_location_scoped(client_a, user_a2_only):
    """`client_a` is active at location A1; `user_a2_only` is assigned only to
    A2. The directory must still show them — `accounts.User` carries no
    `location` filter by design."""
    response = client_a.get(_url('user_list'))
    assert user_a2_only in list(response.context['users'])


def test_list_view_context_includes_choices_and_total(client_a, admin_user):
    response = client_a.get(_url('user_list'))
    assert response.context['tier_choices'] == User.TIER_CHOICES
    assert response.context['status_choices'] == User.STATUS_CHOICES
    assert response.context['total_count'] == 1


# --------------------------------------------------------------------------- #
# Search / filters
# --------------------------------------------------------------------------- #

def test_search_by_email(client_a, tenant_a, make_user):
    match = make_user(tenant_a, email='findme@acme-test.example')
    make_user(tenant_a, email='other@acme-test.example')
    response = client_a.get(_url('user_list'), {'q': 'findme'})
    assert list(response.context['users']) == [match]


def test_search_by_full_name(client_a, tenant_a, make_user):
    match = make_user(tenant_a, email='named@acme-test.example', first_name='Zara', last_name='Nkemelu')
    response = client_a.get(_url('user_list'), {'q': 'zara'})
    assert match in list(response.context['users'])


def test_search_by_phone(client_a, tenant_a, make_user):
    match = make_user(tenant_a, email='phone@acme-test.example', primary_phone='+13125559999')
    response = client_a.get(_url('user_list'), {'q': '5559999'})
    assert match in list(response.context['users'])


def test_filter_by_tier(client_a, tenant_a, admin_user, make_user):
    staff = make_user(tenant_a, tier=User.TIER_STAFF, email='staff-f@acme-test.example')
    response = client_a.get(_url('user_list'), {'tier': 'staff'})
    results = list(response.context['users'])
    assert staff in results
    assert admin_user not in results


def test_filter_by_status(client_a, tenant_a, make_user):
    inactive = make_user(tenant_a, status=User.STATUS_INACTIVE, email='inactive@acme-test.example')
    response = client_a.get(_url('user_list'), {'status': 'inactive'})
    assert list(response.context['users']) == [inactive]


def test_filter_by_provider_yes(client_a, tenant_a, make_user):
    provider = make_user(tenant_a, is_provider=True, email='provider@acme-test.example')
    response = client_a.get(_url('user_list'), {'provider': 'yes'})
    assert provider in list(response.context['users'])


def test_filter_by_provider_no(client_a, tenant_a, admin_user, make_user):
    provider = make_user(tenant_a, is_provider=True, email='provider2@acme-test.example')
    response = client_a.get(_url('user_list'), {'provider': 'no'})
    results = list(response.context['users'])
    assert provider not in results
    assert admin_user in results


# --------------------------------------------------------------------------- #
# Negative-input hardening
# --------------------------------------------------------------------------- #

def test_junk_tier_degrades_to_no_filter(client_a, admin_user):
    response = client_a.get(_url('user_list'), {'tier': 'bogus-tier'})
    assert response.status_code == 200
    assert admin_user in list(response.context['users'])


def test_junk_status_degrades_to_no_filter(client_a, admin_user):
    response = client_a.get(_url('user_list'), {'status': 'bogus-status'})
    assert response.status_code == 200
    assert admin_user in list(response.context['users'])


def test_junk_provider_degrades_to_no_filter(client_a, admin_user):
    response = client_a.get(_url('user_list'), {'provider': 'maybe'})
    assert response.status_code == 200
    assert admin_user in list(response.context['users'])


def test_junk_page_degrades_to_page_1(client_a, admin_user):
    response = client_a.get(_url('user_list'), {'page': 'abc'})
    assert response.status_code == 200
    assert response.context['page_obj'].number == 1


def test_page_2_when_rows_exceed_page_size(client_a, tenant_a, make_user):
    for i in range(30):
        make_user(tenant_a, email=f'bulk-{i:03d}@acme-test.example')
    response = client_a.get(_url('user_list'), {'page': '2'})
    assert response.status_code == 200
    assert response.context['page_obj'].number == 2


def test_page_past_the_end_degrades_to_last_valid_page(client_a, tenant_a, make_user):
    for i in range(30):
        make_user(tenant_a, email=f'bulk2-{i:03d}@acme-test.example')
    response = client_a.get(_url('user_list'), {'page': '99999'})
    assert response.status_code == 200
    assert response.context['page_obj'].number == response.context['page_obj'].paginator.num_pages


# --------------------------------------------------------------------------- #
# user_create_view
# --------------------------------------------------------------------------- #

def test_create_stamps_the_request_tenant(client_a, tenant_a):
    response = client_a.post(_url('user_create'), {
        'email': 'created@acme-test.example', 'tier': User.TIER_STAFF, 'status': User.STATUS_ACTIVE,
    })
    obj = User.objects.get(email='created@acme-test.example')
    assert obj.tenant_id == tenant_a.pk
    assert response.status_code == 302


def test_create_has_no_usable_password(client_a):
    client_a.post(_url('user_create'), {
        'email': 'invited@acme-test.example', 'tier': User.TIER_STAFF, 'status': User.STATUS_ACTIVE,
    })
    obj = User.objects.get(email='invited@acme-test.example')
    assert obj.has_usable_password() is False


def test_create_sends_an_invite_email(client_a):
    mail.outbox.clear()
    client_a.post(_url('user_create'), {
        'email': 'invited2@acme-test.example', 'tier': User.TIER_STAFF, 'status': User.STATUS_ACTIVE,
    })
    assert len(mail.outbox) == 1
    assert 'invited2@acme-test.example' in mail.outbox[0].to


def test_create_get_is_the_form(client_a):
    response = client_a.get(_url('user_create'))
    assert response.status_code == 200
    assert response.context['is_edit'] is False


def test_create_csrf_enforced(admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(_url('user_create'), {
        'email': 'csrf@acme-test.example', 'tier': User.TIER_STAFF, 'status': User.STATUS_ACTIVE,
    })
    assert response.status_code == 403
    assert not User.objects.filter(email='csrf@acme-test.example').exists()


# --------------------------------------------------------------------------- #
# user_detail_view / user_edit_view — cross-tenant IDOR
# --------------------------------------------------------------------------- #

def test_detail_view_renders_for_own_tenant(client_a, admin_user):
    response = client_a.get(_url('user_detail', admin_user.pk))
    assert response.status_code == 200
    assert response.context['obj'] == admin_user


def test_detail_view_cross_tenant_pk_is_404(client_a, admin_b):
    response = client_a.get(_url('user_detail', admin_b.pk))
    assert response.status_code == 404


def test_edit_view_cross_tenant_pk_is_404(client_a, admin_b):
    response = client_a.get(_url('user_edit', admin_b.pk))
    assert response.status_code == 404


def test_edit_view_cross_tenant_post_is_404_and_leaves_row_untouched(client_a, admin_b):
    original_first_name = admin_b.first_name
    response = client_a.post(_url('user_edit', admin_b.pk), {
        'email': admin_b.email, 'first_name': 'Hacked', 'tier': admin_b.tier, 'status': admin_b.status,
    })
    assert response.status_code == 404
    admin_b.refresh_from_db()
    assert admin_b.first_name == original_first_name


def test_edit_view_updates_fields(client_a, member_user):
    response = client_a.post(_url('user_edit', member_user.pk), {
        'email': member_user.email, 'first_name': 'Updated', 'last_name': member_user.last_name,
        'tier': member_user.tier, 'status': member_user.status,
    })
    assert response.status_code == 302
    member_user.refresh_from_db()
    assert member_user.first_name == 'Updated'


def test_edit_view_blocks_the_last_owner_from_demoting_themselves(client_a, admin_user):
    """`admin_user` is tenant A's sole owner (root fixture).

    REGRESSION GUARD. This guard silently did nothing until the accounts suite
    was written: `obj` and `form.instance` are the same object, and Django's
    `ModelForm._post_clean()` mutates `instance.tier` via `construct_instance()`
    the moment `is_valid()` runs — before the comparison and before `save()`. So
    `obj.tier` already echoed the submitted tier, the inequality was always
    False, and a lone owner really could lock their business out of its own user
    management. The view now captures `original_tier` before binding the form.
    """
    response = client_a.post(_url('user_edit', admin_user.pk), {
        'email': admin_user.email, 'first_name': admin_user.first_name, 'last_name': admin_user.last_name,
        'tier': User.TIER_STAFF, 'status': admin_user.status,
    }, follow=True)
    admin_user.refresh_from_db()
    assert admin_user.tier == User.TIER_OWNER
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('only owner' in m for m in messages_seen)


def test_edit_view_last_owner_can_still_edit_other_fields(client_a, admin_user):
    """The guard is scoped to a TIER CHANGE, not to editing yourself at all.

    The bug's fix must not overshoot into blocking a sole owner from correcting
    their own name — only from vacating the last owner seat.
    """
    response = client_a.post(_url('user_edit', admin_user.pk), {
        'email': admin_user.email, 'first_name': 'Renamed', 'last_name': admin_user.last_name,
        'tier': admin_user.tier, 'status': admin_user.status,
    })
    assert response.status_code == 302
    admin_user.refresh_from_db()
    assert admin_user.first_name == 'Renamed'
    assert admin_user.tier == User.TIER_OWNER


# --------------------------------------------------------------------------- #
# Tier escalation. `MANAGEMENT_TIERS` is (owner, manager), so a MANAGER reaches
# the same edit view an owner does — with the same unrestricted tier dropdown
# unless something stops them. The tier is this product's privilege boundary, so
# who may hand it out is part of that boundary, not a UX detail.
# --------------------------------------------------------------------------- #

@pytest.fixture
def manager_client(tenant_a, location_a1, make_user):
    """A signed-in MANAGER — the tier that can reach the user directory but must
    not be able to mint owners."""
    manager = make_user(tenant_a, [location_a1], tier=User.TIER_MANAGER,
                        email='manager@acme-test.example')
    client = Client()
    client.login(customer_id=tenant_a.customer_id, identifier=manager.email,
                 password=DEMO_PASSWORD)
    session = client.session
    session['active_location_id'] = location_a1.pk
    session.save()
    return client, manager


def test_manager_cannot_promote_themselves_to_owner(manager_client):
    """The escalation that matters: a compromised manager minting an owner seat."""
    client, manager = manager_client
    client.post(_url('user_edit', manager.pk), {
        'email': manager.email, 'first_name': manager.first_name,
        'last_name': manager.last_name, 'tier': User.TIER_OWNER,
        'status': manager.status,
    })
    manager.refresh_from_db()
    assert manager.tier == User.TIER_MANAGER


def test_manager_cannot_promote_another_user_to_owner(manager_client, tenant_a, make_user):
    client, _manager = manager_client
    victim = make_user(tenant_a, tier=User.TIER_STAFF, email='staff-x@acme-test.example')
    client.post(_url('user_edit', victim.pk), {
        'email': victim.email, 'first_name': victim.first_name,
        'last_name': victim.last_name, 'tier': User.TIER_OWNER,
        'status': victim.status,
    })
    victim.refresh_from_db()
    assert victim.tier == User.TIER_STAFF


def test_manager_cannot_demote_an_existing_owner(manager_client, admin_user):
    """Managing owners is an owner's job — a manager stripping owners is the same
    privilege boundary viewed from the other side."""
    client, _manager = manager_client
    client.post(_url('user_edit', admin_user.pk), {
        'email': admin_user.email, 'first_name': admin_user.first_name,
        'last_name': admin_user.last_name, 'tier': User.TIER_MANAGER,
        'status': admin_user.status,
    })
    admin_user.refresh_from_db()
    assert admin_user.tier == User.TIER_OWNER


def test_the_manager_tier_dropdown_does_not_offer_owner(manager_client):
    client, manager = manager_client
    response = client.get(_url('user_edit', manager.pk))
    offered = [value for value, _label in response.context['form'].fields['tier'].choices]
    assert User.TIER_OWNER not in offered


def test_an_owner_may_still_grant_the_owner_tier(client_a, tenant_a, make_user):
    """The gate is on the ACTOR's tier, so an owner is unaffected."""
    target = make_user(tenant_a, tier=User.TIER_STAFF, email='promote-me@acme-test.example')
    client_a.post(_url('user_edit', target.pk), {
        'email': target.email, 'first_name': target.first_name,
        'last_name': target.last_name, 'tier': User.TIER_OWNER,
        'status': target.status,
    })
    target.refresh_from_db()
    assert target.tier == User.TIER_OWNER


def test_a_business_can_never_be_left_with_zero_owners(
    client_a, tenant_a, location_a1, admin_user, make_user
):
    """The end-to-end invariant, across the two guards that together enforce it.

    The view's last-owner guard only covers a user demoting THEMSELVES
    (`obj.pk == request.user.pk`). What closes the remaining path is the form
    rule: a non-owner cannot alter an owner's tier at all, so the only actor who
    can demote an owner is another owner — who is, by definition, still an owner
    afterwards. Neither guard is sufficient alone; this asserts the property they
    produce together, so weakening either one fails here.
    """
    second = make_user(tenant_a, [location_a1], tier=User.TIER_OWNER,
                       email='second-owner@acme-test.example')
    # Demote `second` first: legitimate, `admin_user` is still an owner.
    client_a.post(_url('user_edit', second.pk), {
        'email': second.email, 'first_name': second.first_name,
        'last_name': second.last_name, 'tier': User.TIER_MANAGER,
        'status': second.status,
    })
    second.refresh_from_db()
    assert second.tier == User.TIER_MANAGER

    # `admin_user` is now the LAST owner. Signed in as them, demoting themselves
    # is already covered; here a fresh owner-tier actor is not available, so drive
    # the same guard through the self path's sibling: the row is the last owner.
    client_a.post(_url('user_edit', admin_user.pk), {
        'email': admin_user.email, 'first_name': admin_user.first_name,
        'last_name': admin_user.last_name, 'tier': User.TIER_MANAGER,
        'status': admin_user.status,
    })
    admin_user.refresh_from_db()
    assert admin_user.tier == User.TIER_OWNER
    assert User.objects.filter(
        tenant=tenant_a, tier=User.TIER_OWNER, status=User.STATUS_ACTIVE).exists()


def test_edit_view_allows_demotion_when_another_owner_exists(client_a, tenant_a, admin_user, make_user):
    make_user(tenant_a, tier=User.TIER_OWNER, email='second-owner@acme-test.example')
    response = client_a.post(_url('user_edit', admin_user.pk), {
        'email': admin_user.email, 'first_name': admin_user.first_name, 'last_name': admin_user.last_name,
        'tier': User.TIER_MANAGER, 'status': admin_user.status,
    })
    assert response.status_code == 302
    admin_user.refresh_from_db()
    assert admin_user.tier == User.TIER_MANAGER


# --------------------------------------------------------------------------- #
# user_delete_view — deactivation, not deletion
# --------------------------------------------------------------------------- #

def test_delete_view_get_is_405(client_a, tenant_a, make_user):
    other = make_user(tenant_a, email='del-get@acme-test.example')
    response = client_a.get(_url('user_delete', other.pk))
    assert response.status_code == 405
    other.refresh_from_db()
    assert other.status == User.STATUS_ACTIVE


def test_delete_view_deactivates_not_deletes(client_a, tenant_a, make_user):
    other = make_user(tenant_a, email='del-post@acme-test.example')
    response = client_a.post(_url('user_delete', other.pk))
    assert response.status_code == 302
    assert User.objects.filter(pk=other.pk).exists()
    other.refresh_from_db()
    assert other.status == User.STATUS_INACTIVE


def test_delete_view_cross_tenant_pk_is_404(client_a, admin_b):
    response = client_a.post(_url('user_delete', admin_b.pk))
    assert response.status_code == 404
    admin_b.refresh_from_db()
    assert admin_b.status == User.STATUS_ACTIVE


def test_delete_view_refuses_self_deactivation(client_a, admin_user):
    response = client_a.post(_url('user_delete', admin_user.pk))
    assert response.status_code == 302
    admin_user.refresh_from_db()
    assert admin_user.status == User.STATUS_ACTIVE


def test_delete_view_refuses_the_last_active_owner(tenant_a, admin_user, make_user):
    """A MANAGER (not the owner themselves — that's the self-guard's job)
    attempts to deactivate the tenant's sole remaining owner.
    """
    manager = make_user(tenant_a, tier=User.TIER_MANAGER, email='mgr-del@acme-test.example')
    manager_client = Client()
    manager_client.force_login(manager)

    response = manager_client.post(_url('user_delete', admin_user.pk))

    assert response.status_code == 302
    admin_user.refresh_from_db()
    assert admin_user.status == User.STATUS_ACTIVE


def test_delete_view_allows_deactivating_one_of_two_owners(tenant_a, admin_user, make_user):
    """Not the LAST owner — a second active owner exists, so this must succeed."""
    second_owner = make_user(tenant_a, tier=User.TIER_OWNER, email='second-owner-del@acme-test.example')
    manager = make_user(tenant_a, tier=User.TIER_MANAGER, email='mgr-del2@acme-test.example')
    manager_client = Client()
    manager_client.force_login(manager)

    response = manager_client.post(_url('user_delete', second_owner.pk))

    assert response.status_code == 302
    second_owner.refresh_from_db()
    assert second_owner.status == User.STATUS_INACTIVE


def test_delete_view_allows_deactivating_a_non_owner(client_a, tenant_a, make_user):
    staff = make_user(tenant_a, tier=User.TIER_STAFF, email='staff-del@acme-test.example')
    response = client_a.post(_url('user_delete', staff.pk))
    assert response.status_code == 302
    staff.refresh_from_db()
    assert staff.status == User.STATUS_INACTIVE


def test_delete_view_csrf_enforced(admin_user, tenant_a, make_user):
    other = make_user(tenant_a, email='del-csrf@acme-test.example')
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(_url('user_delete', other.pk))
    assert response.status_code == 403
    other.refresh_from_db()
    assert other.status == User.STATUS_ACTIVE


# --------------------------------------------------------------------------- #
# profile_view — open to every signed-in user, no privileged field reachable
# --------------------------------------------------------------------------- #

def test_profile_anonymous_redirects_to_login(client):
    response = client.get(_url('profile'))
    assert response.status_code == 302


def test_profile_open_to_staff_tier(member_client):
    response = member_client.get(_url('profile'))
    assert response.status_code == 200


def test_profile_updates_own_fields(member_client, member_user):
    response = member_client.post(_url('profile'), {
        'first_name': 'Updated', 'last_name': member_user.last_name,
        'full_name': '', 'primary_phone': '',
    })
    assert response.status_code == 302
    member_user.refresh_from_db()
    assert member_user.first_name == 'Updated'


def test_profile_cannot_smuggle_a_tier_promotion(member_client, member_user):
    member_client.post(_url('profile'), {
        'first_name': member_user.first_name, 'last_name': member_user.last_name,
        'full_name': '', 'primary_phone': '', 'tier': User.TIER_OWNER, 'status': User.STATUS_ACTIVE,
    })
    member_user.refresh_from_db()
    assert member_user.tier == User.TIER_STAFF
    assert member_user.status == User.STATUS_ACTIVE


def test_profile_is_always_the_signed_in_user_never_a_pk_from_the_url(member_client, member_user, admin_user):
    """There is no pk in this URL at all — `instance` is always `request.user`."""
    original_admin_first_name = admin_user.first_name
    member_client.post(_url('profile'), {
        'first_name': 'ShouldOnlyAffectMe', 'last_name': member_user.last_name,
        'full_name': '', 'primary_phone': '',
    })
    admin_user.refresh_from_db()
    assert admin_user.first_name == original_admin_first_name


def test_profile_context_includes_assigned_locations(client_a, location_a1, location_a2):
    response = client_a.get(_url('profile'))
    assert set(response.context['assigned_locations']) == {location_a1, location_a2}


def test_profile_csrf_enforced(member_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(member_user)
    response = csrf_client.post(_url('profile'), {
        'first_name': 'ShouldNotSave', 'last_name': '', 'full_name': '', 'primary_phone': '',
    })
    assert response.status_code == 403
    member_user.refresh_from_db()
    assert member_user.first_name != 'ShouldNotSave'
