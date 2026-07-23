"""LLM adapter — sub-module 3.2.

Narrow async interface (``voice-agent-runtime`` skill §12): ``generate(history,
system, tools) -> (text, tool_calls, usage)``. The public method is bounded
(timeout + retry); the concrete backend implements ``_generate``.

**The interface shape never changed when tools landed.** 3.2 shipped it passing
``tools=[]`` and always getting ``[]`` back; 3.3 populates ``tools`` from
``agent.tools.active_tools(...)`` and reads real ``tool_calls`` off the return —
same signature, same tuple. A ``tool_call`` is ``{'name': str, 'args': dict}``, and
the turn loop hands each one to ``agent.dispatcher.apply_tool_call``.

``usage`` is the per-turn token/audio accounting the turn loop folds into
``CallSession.usage`` (skill §13) — the LLM is the only adapter that returns cost
metadata; STT/TTS cost is derived by the turn loop from audio-seconds/characters.

The fake is a real implementation: a deterministic scripted reply, no tool calls,
a usage dict sized to the exchange. Tell-able to fail or stall for the
bounded-call tests.
"""
import abc
import asyncio

from django.conf import settings

from apps.runtime.providers.base import is_live, require_live
from apps.runtime.providers.reliability import call_bounded

__all__ = ['LlmBackend', 'FakeLlmBackend', 'LiveLlmBackend', 'get_llm_backend',
           'set_fake_script', 'clear_fake_script']

#: What the fake replies when no script is supplied — a plausible receptionist
#: line so a heartbeat call sounds like a call, never referencing a tool (skill §8).
_FAKE_DEFAULT_REPLY = 'Sure, I can help you with that. What day works best for you?'


class LlmBackend(abc.ABC):
    """Bounded LLM interface. Concrete backends implement ``_generate``."""

    async def generate(self, history, system, tools):
        """Generate one assistant turn, bounded by ``PROVIDER_TIMEOUT_SECONDS``."""
        return await call_bounded(
            lambda: self._generate(history, system, tools),
            timeout=settings.PROVIDER_TIMEOUT_SECONDS,
        )

    @abc.abstractmethod
    async def _generate(self, history, system, tools):
        """The raw provider call — return ``(text, tool_calls, usage)``."""
        raise NotImplementedError


class FakeLlmBackend(LlmBackend):
    """Deterministic LLM for non-live modes — scripted replies and tool calls.

    ``replies`` is an optional script consumed one per turn; once exhausted it
    falls back to the default line. ``tool_calls`` is a parallel list-of-lists
    scripting which tool calls each round emits (3.3), so the real turn loop and
    the real dispatcher can be driven end to end with no SDK. ``errors`` / ``delay``
    inject failures for the bounded-call tests, and ``self.calls`` records each call.
    """

    #: Rough cost model for the fake so ``CallSession.usage`` carries a plausible,
    #: deterministic breakdown without a real tokenizer.
    _MODEL = 'fake-llm'
    _INPUT_TOKENS_PER_CHAR = 0.25
    _OUTPUT_TOKENS_PER_CHAR = 0.25

    def __init__(self, replies=None, errors=None, delay=0.0, tool_calls=None):
        self._replies = list(replies or [])
        self._errors = list(errors or [])
        self._delay = delay
        # A list-of-lists consumed one entry per _generate() call, in parallel with
        # `replies`: each entry is the tool calls that round should emit, e.g.
        # `[[{'name': 'get_open_slots', 'args': {...}}], []]`. This is what lets the
        # REAL turn loop and the REAL dispatcher be exercised end to end with no SDK
        # and no live model — the fake is a scriptable implementation of the
        # contract, not a mock of it.
        self._tool_calls = list(tool_calls or [])
        self.calls = []

    async def _generate(self, history, system, tools):
        self.calls.append({'history_len': len(history or []), 'tools': len(tools or [])})
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._errors:
            error = self._errors.pop(0)
            if error is not None:
                raise error
        scripted_calls = self._tool_calls.pop(0) if self._tool_calls else []
        if callable(scripted_calls):
            # A callable entry is handed the history so a script can depend on an
            # EARLIER tool's result — the only way to book a slot_token that did
            # not exist when the script was written. The tool results are in
            # history as tool-role turns, so this is reading the same thing a real
            # model would read.
            scripted_calls = scripted_calls(history) or []
        text = self._replies.pop(0) if self._replies else _FAKE_DEFAULT_REPLY
        input_chars = len(system or '') + sum(
            len(turn.get('text', '')) for turn in (history or []) if isinstance(turn, dict)
        )
        usage = {
            'model': self._MODEL,
            'input_tokens': int(input_chars * self._INPUT_TOKENS_PER_CHAR),
            'output_tokens': int(len(text) * self._OUTPUT_TOKENS_PER_CHAR),
        }
        # (text, tool_calls, usage) — `scripted_calls` is [] unless a test or
        # `simulate_call` scripted this round, which keeps the default fake a
        # plain conversational responder.
        return text, scripted_calls, usage


class LiveLlmBackend(LlmBackend):
    """The live LLM backend — refuses to exist outside live mode (see STT)."""

    def __init__(self):
        require_live('the live LLM backend')
        raise NotImplementedError(
            'Live LLM is not implemented in 3.2 — interface, bounded-call policy '
            'and fake ship now; the vendor integration lands with credentials. '
            'Run with PROVIDER_MODE=fake.'
        )

    async def _generate(self, history, system, tools):  # pragma: no cover - never constructed
        raise NotImplementedError


#: Scripting for fakes built by :func:`get_llm_backend` — the ONLY way to drive a
#: scripted conversation through code that constructs its own backend (the media
#: consumer does, in `_authorize_and_start`). Affects the FAKE path only; live mode
#: never reads it. Set it, run, and clear it in a `finally` — see
#: `manage.py simulate_call --script booking` and the dispatcher tests.
_FAKE_SCRIPT = {}


def set_fake_script(replies=None, tool_calls=None):
    """Script the next fake backend(s) `get_llm_backend()` builds. Diagnostic only."""
    _FAKE_SCRIPT['replies'] = replies
    _FAKE_SCRIPT['tool_calls'] = tool_calls


def clear_fake_script():
    """Drop any scripting, so the next fake is a plain conversational responder."""
    _FAKE_SCRIPT.clear()


def get_llm_backend(voice_provider=None):
    """Resolve the LLM backend for the active ``PROVIDER_MODE``.

    Non-live → the fake (carrying any script set via :func:`set_fake_script`).
    Live → the live backend, which refuses to initialize without a real
    integration. ``voice_provider`` is accepted for interface symmetry; the fake
    does not branch on it (the cost-breakdown *shape* by provider is the turn
    loop's concern, not the adapter's).
    """
    if is_live():
        return LiveLlmBackend()
    return FakeLlmBackend(replies=_FAKE_SCRIPT.get('replies'),
                          tool_calls=_FAKE_SCRIPT.get('tool_calls'))
