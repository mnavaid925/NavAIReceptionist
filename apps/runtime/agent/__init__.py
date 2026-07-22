"""The agent package — session state, prompt rendering and the turn loop (3.2).

The conversation brain of the live call, kept apart from the transport (the media
consumer) and the providers (STT / TTS / LLM adapters). Re-exports every public
name so callers write ``from apps.runtime.agent import run_turn`` regardless of
which module it lives in. Absolute imports only, per the backend-package rule.

3.3 adds ``tools.py`` (the declarations) and ``dispatcher.py`` (``apply_tool_call``)
alongside these; 3.2 ships the state, the prompt/variable rendering and the turn
loop with an empty tool list.
"""
from apps.runtime.agent.prompt import (
    RUNTIME_VAR_KEYS,
    build_open_intervals,
    build_variables,
    location_is_open_now,
    render_greeting,
    render_system_prompt,
    render_template,
)
from apps.runtime.agent.state import CallState
from apps.runtime.agent.turn import (
    FALLBACK_LINE,
    MAX_HISTORY_TURNS,
    ProviderBundle,
    TurnResult,
    run_turn,
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
    'ProviderBundle',
    'TurnResult',
    'run_turn',
    'FALLBACK_LINE',
    'MAX_HISTORY_TURNS',
]
