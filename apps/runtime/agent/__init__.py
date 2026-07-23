"""The agent package — session state, prompt rendering and the turn loop (3.2).

The conversation brain of the live call, kept apart from the transport (the media
consumer) and the providers (STT / TTS / LLM adapters). Re-exports every public
name so callers write ``from apps.runtime.agent import run_turn`` regardless of
which module it lives in. Absolute imports only, per the backend-package rule.

3.2 shipped the state, the prompt/variable rendering and the turn loop. 3.3 added
``tools.py`` (the 12 declarations + per-call ``active_tools``), ``envelope.py``
(the one ``{ok, data, error}`` result shape and its closed code set) and
``dispatcher.py`` (``apply_tool_call`` — identity from server state only).
"""
from apps.runtime.agent.dispatcher import IDENTITY_KEYS, TOOL_HANDLERS, apply_tool_call
from apps.runtime.agent.envelope import ERROR_CODES, err, ok
from apps.runtime.agent.prompt import (
    RUNTIME_VAR_KEYS,
    build_open_intervals,
    build_variables,
    format_local_date,
    format_local_time,
    location_is_open_now,
    render_greeting,
    render_system_prompt,
    render_template,
)
from apps.runtime.agent.state import CallState
from apps.runtime.agent.tools import (
    TOOL_DECLARATIONS,
    TOOL_NAMES,
    TRANSFER_TOOLS,
    active_tools,
)
from apps.runtime.agent.turn import (
    FALLBACK_LINE,
    MAX_HISTORY_TURNS,
    ProviderBundle,
    TurnResult,
    run_turn,
    tts_only_cost,
)

__all__ = [
    'CallState',
    'RUNTIME_VAR_KEYS',
    'render_template',
    'build_open_intervals',
    'location_is_open_now',
    'build_variables',
    'render_greeting',
    'render_system_prompt',
    'format_local_date',
    'format_local_time',
    # -- 3.3 tools & dispatcher ------------------------------------------- #
    'TOOL_DECLARATIONS',
    'TOOL_NAMES',
    'TRANSFER_TOOLS',
    'active_tools',
    'ERROR_CODES',
    'ok',
    'err',
    'apply_tool_call',
    'TOOL_HANDLERS',
    'IDENTITY_KEYS',
    'ProviderBundle',
    'TurnResult',
    'run_turn',
    'tts_only_cost',
    'FALLBACK_LINE',
    'MAX_HISTORY_TURNS',
]
