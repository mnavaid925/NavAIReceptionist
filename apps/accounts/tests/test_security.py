"""Cross-cutting tests for Module 0: the dashboard (0.1's landing surface), the
`tier_required` decorator in isolation, and the `navigation` context processor
that decorates every rendered page.

Per-sub-module CSRF, cross-tenant IDOR and tier-gate tests already live beside
each view file (`test_auth_views.py`, `test_credentials_views.py`,
`test_location_switcher.py`, `test_user_views.py`) — this file covers what does
not belong to any one of them.
"""
import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.accounts.context_processors import navigation
from apps.accounts.models import User, UserLocation
from apps.accounts.views._helpers import tier_required

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# dashboard_view
# --------------------------------------------------------------------------- #

def test_dashboard_anonymous_redirects_to_login(client):
    response = client.get(reverse('accounts:dashboard'))
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


def test_dashboard_renders_for_a_tenant_admin(client_a):
    response = client_a.get(reverse('accounts:dashboard'))
    assert response.status_code == 200
    assert 'accounts/dashboard.html' in [t.name for t in response.templates]


def test_dashboard_stats_reflect_this_users_own_assignments(client_a, location_a1, location_a2):
    response = client_a.get(reverse('accounts:dashboard'))
    assert response.context['stats']['locations'] == 2


def test_dashboard_assignment_count_is_tenant_scoped(client_a, tenant_b, location_b1):
    """Tenant B's `UserLocation` rows must never inflate tenant A's count."""
    another_b_user = User.objects.create_user(
        tenant=tenant_b, email='second-b@globex-test.example', password='pw12345678',
    )
    UserLocation.objects.create(tenant=tenant_b, user=another_b_user, location=location_b1)
    response = client_a.get(reverse('accounts:dashboard'))
    # Only tenant A's own rows: admin_user@A1 and admin_user@A2 (`client_a`
    # requests no other tenant-A user, so `member_user` is never instantiated).
    assert response.context['stats']['assignments'] == 2


def test_dashboard_for_the_platform_superuser_has_no_tenant_data(db):
    superuser = User.objects.create_superuser(email='root-dash@platform.example', password='pw12345678')
    client = Client()
    client.force_login(superuser)

    response = client.get(reverse('accounts:dashboard'))

    assert response.status_code == 200
    assert response.context['stats']['locations'] == 0
    assert response.context['stats']['assignments'] == 0
    assert response.wsgi_request.tenant is None


def test_dashboard_post_is_not_supported_or_is_a_noop(client_a):
    """No `@require_http_methods` on this view — a POST must still not error or
    mutate anything; it degrades to the same GET-shaped render."""
    response = client_a.post(reverse('accounts:dashboard'), {})
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# tier_required() — in isolation
# --------------------------------------------------------------------------- #

def test_tier_required_redirects_to_login_url_for_anonymous():
    @tier_required(User.TIER_OWNER)
    def view(request):  # pragma: no cover - never reached
        raise AssertionError('view must not run for an unauthenticated request')

    request = RequestFactory().get('/')
    request.user = AnonymousUser()

    response = view(request)
    assert response.status_code == 302


def test_tier_required_blocks_a_disallowed_tier(tenant_a, member_user):
    @tier_required(User.TIER_OWNER, User.TIER_MANAGER)
    def view(request):  # pragma: no cover - never reached
        raise AssertionError('view must not run for a disallowed tier')

    request = RequestFactory().get('/')
    request.user = member_user
    # `messages.error` needs the messages storage installed.
    from django.contrib.messages.storage.fallback import FallbackStorage
    request.session = {}
    request._messages = FallbackStorage(request)

    response = view(request)
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')


def test_tier_required_allows_a_permitted_tier(admin_user):
    calls = {}

    @tier_required(User.TIER_OWNER)
    def view(request):
        calls['ran'] = True
        from django.http import HttpResponse
        return HttpResponse('ok')

    request = RequestFactory().get('/')
    request.user = admin_user

    response = view(request)
    assert calls.get('ran') is True
    assert response.status_code == 200


def test_tier_required_preserves_the_wrapped_views_metadata():
    @tier_required(User.TIER_OWNER)
    def my_named_view(request):  # pragma: no cover
        return None

    assert my_named_view.__name__ == 'my_named_view'


# --------------------------------------------------------------------------- #
# navigation() context processor — must never raise, on any request shape
# --------------------------------------------------------------------------- #

def test_navigation_context_processor_handles_a_request_with_no_user_attribute():
    request = RequestFactory().get('/')
    context = navigation(request)
    assert context['nav_modules'] == []
    assert context['account_tabs'] == []
    assert context['user_locations'] == []


def test_navigation_context_processor_handles_anonymous_user():
    request = RequestFactory().get('/')
    request.user = AnonymousUser()
    context = navigation(request)
    assert context['nav_modules'] == []
    assert context['active_tenant'] is None
    assert context['active_location'] is None


def test_navigation_context_processor_populates_for_an_authenticated_user(admin_user, tenant_a, location_a1):
    request = RequestFactory().get('/')
    request.user = admin_user
    request.tenant = tenant_a
    request.location = location_a1

    context = navigation(request)

    assert context['nav_modules']
    assert context['active_tenant'] == tenant_a
    assert context['active_location'] == location_a1
    assert location_a1 in context['user_locations']


def test_navigation_context_processor_optional_urls_resolve_defensively():
    request = RequestFactory().get('/')
    context = navigation(request)
    # Every key is present and either a resolvable URL or None — never raises.
    assert set(context['nav_urls']) == {
        'switch_location', 'profile', 'change_password', 'change_email', 'logout', 'user_list',
    }
    assert all(context['nav_urls'].values())
