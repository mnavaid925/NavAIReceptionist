"""Fixtures for `apps.agents`'s suite — domain records only.

Tenant/location/user/client fixtures come from the ROOT `conftest.py`; this file
adds agents-specific domain records on top of them, per the project's testing
convention (an app-level `conftest.py` only adds domain records):

* `manager_user` / `manager_client` — a tenant A MANAGER-tier user, proving the
  other half of `MANAGEMENT_TIERS = ('owner', 'manager')` alongside the root
  fixtures' `admin_user`/`client_a` (owner) and `member_user`/`member_client`
  (staff, the tier that must be BLOCKED).
* `make_agent_setting` — a factory, deliberately self-contained rather than
  imported from `apps.runtime.tests.conftest.make_agent_setting` (that suite is
  owned by another module and the project convention keeps each app's fixtures
  independent so the two can evolve without coupling).
* `raw_auth_token_column` — reads the `twilio_auth_token` column with a raw SQL
  SELECT, bypassing `EncryptedCharField.from_db_value`. This is the only way to
  prove the STORED bytes are ciphertext rather than the model's already-decrypted
  Python-level view of them.
"""
import pytest
from django.db import connection
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User, UserLocation
from apps.agents.models import AgentSetting

from conftest import DEMO_PASSWORD

__all__ = ['DEMO_PASSWORD', 'raw_auth_token_column']


@pytest.fixture
def manager_user(tenant_a, location_a1):
    """A tenant A MANAGER-tier user, assigned to location A1."""
    user = User.objects.create_user(
        tenant=tenant_a, email='manager@acme-test.example', password=DEMO_PASSWORD,
        tier=User.TIER_MANAGER, first_name='Max', last_name='Manager',
    )
    UserLocation.objects.create(tenant=tenant_a, user=user, location=location_a1)
    return user


@pytest.fixture
def manager_client(manager_user, location_a1):
    """`manager_user`, logged in, with location A1 active (via the real
    switcher, exactly like the root fixtures' `client_a`)."""
    client = Client()
    client.force_login(manager_user)
    response = client.post(
        reverse('accounts:switch_location'), {'location': location_a1.pk}, follow=True,
    )
    assert response.status_code == 200
    return client


@pytest.fixture
def make_agent_setting(db):
    """Factory: `make_agent_setting(tenant, location, **overrides) -> AgentSetting`.

    Deliberately minimal defaults (no Twilio credentials, no inbound number) so a
    test opts INTO the configured state it needs rather than fighting defaults it
    does not — `readiness_issues()`/`is_ready` tests in particular want to start
    from "nothing set".
    """
    def _make(tenant, location, **overrides):
        defaults = {
            'enabled': True,
            'voice_provider': AgentSetting.VOICE_LIVE,
        }
        defaults.update(overrides)
        return AgentSetting.objects.create(tenant=tenant, location=location, **defaults)
    return _make


def raw_auth_token_column(setting):
    """The RAW `twilio_auth_token` column value for `setting`, straight from
    SQL — never through `EncryptedCharField`'s transparent decrypt."""
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT twilio_auth_token FROM agents_agentsetting WHERE id = %s',
            [setting.pk],
        )
        row = cursor.fetchone()
    return row[0] if row else None
