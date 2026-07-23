"""The tool declarations — sub-module 3.3.

**Plain, provider-agnostic dicts** (``voice-agent-runtime`` §8): ``name``,
``description``, ``parameters`` (JSON Schema). This module **imports no SDK**, so
the declaration list can be asserted in tests without one, and the provider
adapter is what converts these into whichever tool format its vendor wants.

**Twelve tools, no more.** If a tool is not in this file it does not exist — no
insurance tool, no clinical note, nothing vertical-specific.

**No declaration carries an identity parameter.** ``tenant_id``, ``location_id``,
``contact_id`` and ``session_id`` are never tool parameters (Invariant 3); the
dispatcher reads them from server-held session state. A tool that asked the model
for them would be asking a stranger on the phone who they are and believing the
answer. The identified contact is likewise implicit: ``book_appointment`` books
for whoever the call has already identified, which is why it takes no contact
argument.

**Argument conventions** (fixed by the skill, so the model learns one set):
``date_from``/``date_to`` are ``MM/DD/YYYY``; ``time_from``/``time_to`` are
24-hour ``HH:MM``; ``weekdays`` is an array of lowercase three-letter day keys.

**Slot tokens are opaque.** ``get_open_slots`` returns a ``slot_token`` per slot
and the booking tools take that token back unchanged — the model is never asked to
echo a start time, a provider or a room. That is what stops a caller talking the
agent into 3am or into someone else's room: the only bookable slots are ones the
server minted and signed.
"""

__all__ = ['TOOL_DECLARATIONS', 'TOOL_NAMES', 'TRANSFER_TOOLS', 'active_tools']

TOOL_DECLARATIONS = [
    {
        'name': 'get_contact_appointments',
        'description': (
            "Look up the caller by phone to find out whether they are already on "
            "file and fetch their appointments. Call this FIRST for any "
            "appointment intent. Defaults to the number this call came from, so "
            "normally you can call it with no arguments."
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'phone': {
                    'type': 'string',
                    'description': "Only if the caller gives a DIFFERENT number "
                                   "than the one they are calling from.",
                },
            },
            'required': [],
        },
    },
    {
        'name': 'search_contact',
        'description': (
            "Find an existing person by name and date of birth. Use this when the "
            "phone lookup found nobody, or found more than one possible match."
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'first': {'type': 'string', 'description': 'Given name.'},
                'last': {'type': 'string', 'description': 'Family name.'},
                'date_of_birth': {'type': 'string',
                                  'description': 'Date of birth, MM/DD/YYYY.'},
            },
            'required': ['first', 'last', 'date_of_birth'],
        },
    },
    {
        'name': 'create_contact',
        'description': (
            "Create a record for a caller who is not yet on file. Only call this "
            "after looking them up and not finding them."
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'first_name': {'type': 'string'},
                'last_name': {'type': 'string'},
                'date_of_birth': {'type': 'string',
                                  'description': 'Date of birth, MM/DD/YYYY.'},
                'phone': {'type': 'string',
                          'description': 'Best contact number, if given.'},
            },
            'required': ['first_name', 'last_name'],
        },
    },
    {
        'name': 'get_open_slots',
        'description': (
            "Return open appointment times, soonest first. Read a few of them out "
            "to the caller in plain language. Pass each result's slot_token "
            "UNCHANGED to book_appointment or reschedule_appointment — never make "
            "up a time or repeat one back as text."
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'service_id': {'type': 'integer',
                               'description': 'Which service the caller wants.'},
                'date_from': {'type': 'string', 'description': 'MM/DD/YYYY.'},
                'date_to': {'type': 'string', 'description': 'MM/DD/YYYY.'},
                'weekdays': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': "Restrict to these days, e.g. ['mon','tue'].",
                },
                'time_from': {'type': 'string',
                              'description': 'Earliest time of day, 24-hour HH:MM.'},
                'time_to': {'type': 'string',
                            'description': 'Latest time of day, 24-hour HH:MM.'},
                'duration_minutes': {'type': 'integer'},
                'provider_ids': {'type': 'array', 'items': {'type': 'integer'},
                                 'description': 'Restrict to these providers.'},
                'resource_ids': {'type': 'array', 'items': {'type': 'integer'},
                                 'description': 'Restrict to these rooms/resources.'},
                'page': {'type': 'integer'},
                'page_size': {'type': 'integer'},
            },
            'required': ['service_id'],
        },
    },
    {
        'name': 'book_appointment',
        'description': (
            "Book one of the times you were just offered, for the person this call "
            "has already identified. Do not say the booking is done until this "
            "returns successfully."
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'slot_token': {'type': 'string',
                               'description': 'The slot_token from get_open_slots, '
                                              'copied exactly.'},
                'reason': {'type': 'string',
                           'description': 'Why they are coming in, in a few words.'},
                'notes': {'type': 'string',
                          'description': 'Anything else the team should know.'},
            },
            'required': ['slot_token'],
        },
    },
    {
        'name': 'reschedule_appointment',
        'description': (
            "Move an existing appointment to one of the times you were just "
            "offered. Confirm which appointment with the caller first."
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'appointment_id': {'type': 'integer'},
                'slot_token': {'type': 'string',
                               'description': 'The new slot_token, copied exactly.'},
            },
            'required': ['appointment_id', 'slot_token'],
        },
    },
    {
        'name': 'cancel_appointment',
        'description': (
            "Cancel an appointment. Always confirm with the caller which one, and "
            "that they want it cancelled, before calling this."
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'appointment_id': {'type': 'integer'},
                'cancellation_reason': {'type': 'string'},
            },
            'required': ['appointment_id'],
        },
    },
    {
        'name': 'create_callback_request',
        'description': (
            "Log a request for the team to call this person back, for anything you "
            "cannot finish on this call or when the office is closed."
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'caller_name': {'type': 'string'},
                'caller_phone': {'type': 'string'},
                'reason': {'type': 'string',
                           'description': 'What they need, in a sentence.'},
            },
            'required': ['reason'],
        },
    },
    {
        'name': 'get_location_hours',
        'description': (
            "Get this location's opening hours and address so you can read them "
            "out. Use this instead of guessing or working it out yourself."
        ),
        'parameters': {'type': 'object', 'properties': {}, 'required': []},
    },
    {
        'name': 'transfer_call',
        'description': (
            "Hand the call to a person on the team. Say a short handoff line; the "
            "transfer happens right after you finish speaking."
        ),
        'parameters': {'type': 'object', 'properties': {}, 'required': []},
    },
    {
        'name': 'transfer_call_spanish',
        'description': (
            "Hand the call to the Spanish-speaking line. Use this when the caller "
            "asks to speak Spanish."
        ),
        'parameters': {'type': 'object', 'properties': {}, 'required': []},
    },
    {
        'name': 'end_call',
        'description': (
            "End the call once the caller is done, or on a wrong number. Say "
            "goodbye first; the call hangs up after you finish speaking."
        ),
        'parameters': {'type': 'object', 'properties': {}, 'required': []},
    },
]

#: Every declared tool name — the parity check the dispatcher's table is asserted against.
TOOL_NAMES = frozenset(tool['name'] for tool in TOOL_DECLARATIONS)

#: The two transport-mutating handoff tools and the `AgentSetting` destination
#: field each one dials. Enablement is per-location and per-call, so this maps the
#: tool to the field `active_tools` must find non-blank before offering it.
TRANSFER_TOOLS = {
    'transfer_call': 'transfer_phone_number',
    'transfer_call_spanish': 'transfer_secondary_number',
}


def active_tools(agent_setting):
    """The declarations to offer on THIS call, given the location's agent config.

    A function rather than a constant because enablement is per-call: the transfer
    tools are offered only when the location has `transfer_enabled` AND a non-blank
    destination for that specific line. **The presence of a destination, not just
    the flag, is what gates it** — offering a tool whose destination is blank would
    let the agent promise a handoff that cannot happen, which the skill names as
    the thing never to do (§8.3: never promise a capability whose tool is disabled
    for that location).

    A missing/None `agent_setting` yields the non-transfer tools only — fail closed.
    """
    enabled = bool(agent_setting is not None
                   and getattr(agent_setting, 'transfer_enabled', False))
    active = []
    for tool in TOOL_DECLARATIONS:
        destination_field = TRANSFER_TOOLS.get(tool['name'])
        if destination_field is not None:
            if not enabled:
                continue
            if not (getattr(agent_setting, destination_field, '') or '').strip():
                continue
        active.append(tool)
    return active
