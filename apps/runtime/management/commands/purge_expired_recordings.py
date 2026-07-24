"""``manage.py purge_expired_recordings`` — the retention surface (3.5).

CLAUDE.md's recording rule ends with *"the retention window is enforced by a
scheduled job"*. This is that job. A consent basis without an expiry is only half
a policy: recordings are caller PII, and a store that only ever grows is the
liability the retention window exists to bound.

**Why a management command and not a task queue:** this stack has no Celery/beat
(``grep -i celery config/settings.py`` finds nothing), and adding a broker to run
one nightly sweep would be a large dependency for a small job. A command driven by
OS cron / Windows Task Scheduler is the honest shape here, and it is the same
shape every other one-shot job in this repo takes.

    venv\\Scripts\\python.exe manage.py purge_expired_recordings --dry-run
    venv\\Scripts\\python.exe manage.py purge_expired_recordings
    venv\\Scripts\\python.exe manage.py purge_expired_recordings --tenant acme

**Idempotent by construction.** A purged row's ``recording_blob`` is ``''``, and
the driving queryset excludes exactly that — so a second run skips everything the
first one cleared. No double-delete, no second metadata stamp.

**Per-row retention, not a global one.** The window is read from the row's own
``metadata['retention_days']``, stamped at teardown from the setting in force at
the time of the call — the same "the policy that applies is the policy at the time
of the call" rule the consent basis follows. Lowering the setting therefore does
not retroactively expire older recordings, which is the correct behaviour for a
compliance window someone may have committed to.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.calls.models import CallSession
from apps.calls.storage import recording_storage

#: Streamed in chunks — a busy tenant's call table is the fastest-growing one in
#: the product, and this job must not load it all into memory to sweep it.
_CHUNK_SIZE = 200


class Command(BaseCommand):
    help = ('Delete call recordings past their per-row retention window and clear '
            'their recording_blob. Idempotent; safe to run on a schedule.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            help='Limit to one tenant, by slug or customer_id. Omit for all.')
        parser.add_argument(
            '--location',
            help='Limit to one location, by slug. Omit for all.')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be purged and write nothing.')

    def handle(self, *args, **options):
        dry_run = bool(options.get('dry_run'))
        # `.exclude(recording_blob='')` IS the idempotency guard — a row purged by
        # an earlier run can never be selected again.
        queryset = CallSession.objects.exclude(recording_blob='').only(
            'pk', 'provider_call_sid', 'recording_blob', 'metadata', 'started_at',
            'created_at')

        tenant_hint = options.get('tenant')
        if tenant_hint:
            queryset = queryset.filter(
                Q(tenant__slug=tenant_hint) | Q(tenant__customer_id=tenant_hint))
        location_hint = options.get('location')
        if location_hint:
            queryset = queryset.filter(location__slug=location_hint)

        now = timezone.now()
        purged = skipped = failed = 0

        for session in queryset.iterator(chunk_size=_CHUNK_SIZE):
            expires_at = self._expires_at(session)
            if expires_at is None or expires_at > now:
                skipped += 1
                continue
            if dry_run:
                purged += 1
                self.stdout.write(
                    f'  would purge {session.provider_call_sid} '
                    f'(expired {expires_at:%Y-%m-%d %H:%M})')
                continue
            if self._purge(session):
                purged += 1
            else:
                failed += 1

        verb = 'would be purged' if dry_run else 'purged'
        self.stdout.write(self.style.SUCCESS(
            f'Recordings: {purged} {verb}, {skipped} still within retention.'))
        if failed:
            self.stdout.write(self.style.WARNING(
                f'  {failed} row(s) could not be cleared — see the errors above.'))

    def _expires_at(self, session):
        """When this row's recording expires, or None if it never should.

        ``retention_days`` of 0 means an unrecorded call (nothing to purge), and a
        malformed value is treated the same way: refusing to guess is safer than
        inventing a window and deleting a recording early. Rows without a
        ``started_at`` fall back to ``created_at`` — a session row always has one,
        so a call that died before its first media frame still ages out.
        """
        metadata = session.metadata if isinstance(session.metadata, dict) else {}
        try:
            days = int(metadata.get('retention_days') or 0)
        except (TypeError, ValueError):
            return None
        if days <= 0:
            return None
        started = session.started_at or session.created_at
        return started + timedelta(days=days) if started else None

    def _purge(self, session):
        """Delete the file and clear the row. Returns whether the row was cleared.

        The file delete comes FIRST: what must not happen is clearing the row
        while the file survives, because this job walks ROWS — an orphaned
        recording nothing points at is the one outcome it could never come back
        for. A row whose delete fails is therefore left intact so the next run
        retries it, and reported rather than silently counted as purged.
        """
        try:
            # `FileSystemStorage.delete` already treats a missing file as success,
            # so a hand-deleted file or a seeded path with nothing behind it needs
            # no special case here — it has already satisfied "the bytes are gone".
            recording_storage.delete(session.recording_blob)
        except Exception as exc:  # noqa: BLE001 — one bad row must not stop the sweep
            # Type only: a storage error's text carries the path, which embeds the
            # tenant, the location and the call SID.
            self.stderr.write(
                f'  could not delete the file for session #{session.pk} '
                f'({type(exc).__name__}) — leaving the row intact')
            return False

        metadata = dict(session.metadata if isinstance(session.metadata, dict) else {})
        metadata['recording_purged_at'] = timezone.now().isoformat()
        session.recording_blob = ''
        session.metadata = metadata
        session.save(update_fields=['recording_blob', 'metadata', 'updated_at'])
        return True
