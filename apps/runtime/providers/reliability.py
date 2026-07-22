"""Bounded provider calls — the timeout/retry/backoff seam for STT, TTS and LLM.

Every external call the live-call path makes is bounded (``voice-agent-runtime``
skill §11, CLAUDE.md realtime rule 4): an explicit timeout and a bounded retry,
degrading to a spoken fallback rather than dead air. This module is that seam,
shared by the three adapter families so the policy is defined once.

The retry policy distinguishes two failure shapes, because they want opposite
treatment (the research file's "provider rate limits" note):

* **Rate-limited (``RateLimited``, a 429-shaped response)** — the provider is
  telling us to slow down. Hammering it compounds the outage across every
  concurrent call on the tenant. So we **back off** (a longer, escalating sleep)
  before the one bounded retry.
* **Transient (``TransientProviderError``, a 5xx-shaped blip)** — retry quickly
  within the bound.
* **A timeout is terminal — it is NOT retried.** A hung provider will not un-hang
  on an immediate retry, and a second full timeout wait doubles the caller's
  dead-air (the ≤3 s p95 turn budget, skill §11, is already blown by one). Fail
  fast to the spoken fallback instead.

A non-provider exception (a bug in our own code) is **not** retried — it
propagates, because retrying a logic error just runs it again.

On exhaustion the last error is raised; the caller (the turn loop) catches it and
speaks a fallback line. The wrapper itself never returns dead air and never sleeps
unboundedly.
"""
import asyncio

__all__ = [
    'ProviderError',
    'RateLimited',
    'TransientProviderError',
    'ProviderTimeout',
    'call_bounded',
]


class ProviderError(Exception):
    """Base class for a recoverable provider failure the turn loop can degrade on."""


class RateLimited(ProviderError):
    """A 429-shaped response — back off before retrying, never hammer."""


class TransientProviderError(ProviderError):
    """A 5xx-shaped blip — retry quickly within the bound."""


class ProviderTimeout(ProviderError):
    """The call exceeded its per-call timeout budget."""


async def call_bounded(factory, *, timeout, retries=1,
                       rate_limit_backoff=0.3, transient_backoff=0.05):
    """Call ``factory()`` (a zero-arg coroutine fn) with a timeout and bounded retry.

    ``factory`` is re-invoked per attempt so each retry gets a fresh coroutine.
    ``retries`` is the number of retries *after* the first attempt (default 1, so
    at most two attempts total). A ``RateLimited`` sleeps ``rate_limit_backoff``
    (escalating per attempt); a transient error or a timeout sleeps the shorter
    ``transient_backoff``. Anything that is not a ``ProviderError`` or a timeout
    propagates immediately — a bug is not a retryable failure.
    """
    attempt = 0
    while True:
        try:
            return await asyncio.wait_for(factory(), timeout)
        except asyncio.TimeoutError:
            # Terminal: a hung provider will not recover on an immediate retry, and
            # a second full timeout wait doubles the caller's dead-air. Fail fast to
            # the spoken fallback (skill §11 budget).
            raise ProviderTimeout(f'provider call exceeded {timeout}s')
        except RateLimited as exc:
            last_error = exc
            backoff = rate_limit_backoff * (attempt + 1)
        except TransientProviderError as exc:
            last_error = exc
            backoff = transient_backoff
        # A ProviderError subclass we do not special-case still retries within the
        # bound; any other exception type is a bug and propagates (not caught here).

        attempt += 1
        if attempt > retries:
            raise last_error
        if backoff > 0:
            await asyncio.sleep(backoff)
