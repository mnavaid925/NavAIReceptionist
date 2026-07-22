"""Channels consumers for Module 3 — the fifth backend layer (3.2).

Same ``<SubModule>/<Entity>.py`` shape as ``models``/``forms``/``views``/``urls``,
with the same re-export rule: ``routing.py`` imports ``MediaStreamConsumer`` from
this package, so a consumer that is not re-exported here fails at route-import
time, not at connect time (Backend Package Structure rule 3).
"""
from apps.runtime.consumers.MediaStreamTurnLoop.MediaStream import MediaStreamConsumer

__all__ = ['MediaStreamConsumer']
