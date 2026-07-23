"""``agent/tools.py`` — the 12 tool declarations and per-call ``active_tools``.

Plain-dict declarations with no SDK import (sub-module 3.3): asserted here by
name and shape alone. The dispatcher-parity assertion (``TOOL_NAMES ==
set(TOOL_HANDLERS)``) lives here too — it is the contract the two modules'
docstrings each promise the other, so a test that breaks either file breaks
here first, before a call ever reaches ``apply_tool_call``.
"""
import pytest

from apps.agents.models import AgentSetting
from apps.runtime.agent.dispatcher import TOOL_HANDLERS
from apps.runtime.agent.tools import (
    TOOL_DECLARATIONS,
    TOOL_NAMES,
    TRANSFER_TOOLS,
    active_tools,
)

pytestmark = pytest.mark.django_db

#: Invariant 3: identity is server state, never a tool argument.
_IDENTITY_PARAMS = {'tenant_id', 'location_id', 'contact_id', 'session_id'}


# --------------------------------------------------------------------------- #
# Declarations — shape and dispatch parity
# --------------------------------------------------------------------------- #

def test_exactly_twelve_tools_are_declared():
    assert len(TOOL_DECLARATIONS) == 12


def test_declaration_names_are_unique():
    names = [tool['name'] for tool in TOOL_DECLARATIONS]
    assert len(names) == len(set(names))


def test_tool_names_matches_the_dispatch_table_exactly():
    """The parity the dispatcher's own docstring promises: a declared-but-
    undispatched tool fails silently mid-call, a dispatched-but-undeclared one
    is dead code the model can never reach."""
    assert TOOL_NAMES == set(TOOL_HANDLERS)


def test_no_declaration_exposes_an_identity_parameter():
    for tool in TOOL_DECLARATIONS:
        props = set(tool['parameters'].get('properties', {}))
        assert not (props & _IDENTITY_PARAMS), f"{tool['name']} exposes identity args"


def test_every_declaration_has_the_required_json_schema_shape():
    for tool in TOOL_DECLARATIONS:
        assert isinstance(tool['name'], str) and tool['name']
        assert isinstance(tool['description'], str) and tool['description']
        params = tool['parameters']
        assert params['type'] == 'object'
        assert isinstance(params['properties'], dict)
        assert isinstance(params['required'], list)
        # Every 'required' name must actually be a declared property.
        assert set(params['required']) <= set(params['properties'])


def test_transfer_tools_map_to_the_agentsetting_destination_fields():
    assert TRANSFER_TOOLS == {
        'transfer_call': 'transfer_phone_number',
        'transfer_call_spanish': 'transfer_secondary_number',
    }


# --------------------------------------------------------------------------- #
# active_tools() — per-call gating on the location's transfer configuration
# --------------------------------------------------------------------------- #

def _setting(tenant, location, **kw):
    defaults = dict(enabled=True, inbound_phone_number='+13125550140',
                    twilio_account_sid='AC' + '1' * 32,
                    twilio_auth_token='test-auth-token-0001',
                    greeting='Hi.', prompt_text='You are the receptionist.',
                    voice_provider=AgentSetting.VOICE_LIVE)
    defaults.update(kw)
    return AgentSetting.objects.create(tenant=tenant, location=location, **defaults)


def test_active_tools_omits_both_transfer_tools_when_transfer_disabled(
    tenant_a, location_a1,
):
    setting = _setting(tenant_a, location_a1, transfer_enabled=False,
                       transfer_phone_number='+13125550101',
                       transfer_secondary_number='+13125550102')
    names = {t['name'] for t in active_tools(setting)}
    assert 'transfer_call' not in names
    assert 'transfer_call_spanish' not in names
    # every non-transfer tool is still offered
    assert names == TOOL_NAMES - {'transfer_call', 'transfer_call_spanish'}


def test_active_tools_omits_transfer_call_when_enabled_but_destination_blank(
    tenant_a, location_a1,
):
    setting = _setting(tenant_a, location_a1, transfer_enabled=True,
                       transfer_phone_number='')
    assert 'transfer_call' not in {t['name'] for t in active_tools(setting)}


def test_active_tools_includes_transfer_call_once_its_destination_is_set(
    tenant_a, location_a1,
):
    setting = _setting(tenant_a, location_a1, transfer_enabled=True,
                       transfer_phone_number='+13125550101')
    assert 'transfer_call' in {t['name'] for t in active_tools(setting)}


def test_active_tools_omits_spanish_when_only_the_primary_destination_is_set(
    tenant_a, location_a1,
):
    """The presence of a destination gates PER tool — a configured primary line
    must not also switch on the Spanish line."""
    setting = _setting(tenant_a, location_a1, transfer_enabled=True,
                       transfer_phone_number='+13125550101',
                       transfer_secondary_number='')
    names = {t['name'] for t in active_tools(setting)}
    assert 'transfer_call' in names
    assert 'transfer_call_spanish' not in names


def test_active_tools_includes_spanish_once_its_own_destination_is_set(
    tenant_a, location_a1,
):
    setting = _setting(tenant_a, location_a1, transfer_enabled=True,
                       transfer_phone_number='+13125550101',
                       transfer_secondary_number='+13125550102')
    names = {t['name'] for t in active_tools(setting)}
    assert 'transfer_call' in names
    assert 'transfer_call_spanish' in names


def test_active_tools_fails_closed_on_a_missing_agent_setting():
    names = {t['name'] for t in active_tools(None)}
    assert names == TOOL_NAMES - {'transfer_call', 'transfer_call_spanish'}
