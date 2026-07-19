"""View helpers shared by MORE THAN ONE sub-module of Module 4.

Helpers used by a single entity stay in that entity's own view module.
"""
import logging

from django.db import IntegrityError

logger = logging.getLogger(__name__)

__all__ = ['save_or_report_conflict']


def save_or_report_conflict(form, message):
    """`form.save()`, converting a unique-constraint collision into a form error.

    Returns the saved instance, or `None` if the insert lost a race.

    Several forms in this module hand-enforce a uniqueness rule that Django
    cannot check itself, because part of the constraint's field tuple is excluded
    from the form and stamped from the request instead (`Resource`'s
    `(location, name)` is the canonical case — `location` is never rendered, so
    Django skips the constraint entirely).

    A hand-rolled `.exists()` check is check-then-act: two concurrent submissions,
    or one impatient double-click, can both pass validation and the second insert
    then raises a raw `IntegrityError` — a 500 on exactly the path the manual
    check was written to keep friendly. The `.exists()` check still earns its
    place (it produces a good message in the overwhelmingly common single-writer
    case); this closes the narrow window behind it.

    Deliberately catches `IntegrityError` broadly rather than parsing the driver's
    message for a constraint name: those strings differ between MySQL, MariaDB and
    SQLite, and a parser that silently stops matching would turn this guard back
    into the 500 it exists to prevent.
    """
    try:
        return form.save()
    except IntegrityError:
        logger.info(
            'Save lost a uniqueness race form=%s', type(form).__name__
        )
        form.add_error(None, message)
        return None
