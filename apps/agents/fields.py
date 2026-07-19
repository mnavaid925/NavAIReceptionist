"""Encryption at rest for provider credentials.

`agents.AgentSetting.twilio_auth_token` is a live credential: a Twilio account SID
plus its auth token is full control of that account — placing calls, buying
numbers, reading logs, spending money. It is stored encrypted, and the
surrounding rules matter as much as the cipher:

* **Write-only in forms.** The field is never bound to its current value, so it
  cannot be echoed into an HTML `value=` attribute, cached by a browser, or logged
  by an intermediary. A blank submit means "leave it alone", not "erase it".
* **Never logged, never in `messages.*`.** A message body is serialised into the
  session store and survives long after the page.
* **Never returned by a view.** The UI shows a set / not-set indicator only.

The reference implementation this product is derived from stored this token in
plaintext and called encryption "a later hardening". We do not copy that.

MEASURED SIZE. Fernet is authenticated encryption over base64, so ciphertext is
much larger than plaintext: a 32-character Twilio token becomes ~140 characters.
`NavAIReceptionist-ERD.md` specifies `Char(128)` for the plaintext intent, which
cannot hold the ciphertext — the column is 512 to leave headroom, and the ERD
records the deviation.
"""
import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

logger = logging.getLogger(__name__)

__all__ = ['EncryptedCharField', 'encrypt_value', 'decrypt_value', 'mask_secret']

#: Marks a stored value as ciphertext. Lets `get_prep_value` stay idempotent and
#: lets a read distinguish "encrypted" from "written before encryption existed".
PREFIX = 'fernet:'


def _cipher():
    """The Fernet instance, or a loud failure.

    Raises rather than degrading: silently storing a credential in plaintext
    because a key was missing is precisely the outcome this module exists to
    prevent.
    """
    from cryptography.fernet import Fernet

    key = (getattr(settings, 'ENCRYPTION_KEY', '') or '').strip()
    if not key:
        raise ImproperlyConfigured(
            'ENCRYPTION_KEY is not set. Provider credentials cannot be stored '
            'without it. Generate one with: python -c "from cryptography.fernet '
            'import Fernet; print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        raise ImproperlyConfigured(
            'ENCRYPTION_KEY is not a valid Fernet key (needs 32 url-safe '
            f'base64-encoded bytes): {exc}'
        ) from exc


def encrypt_value(raw):
    """Encrypt a secret for storage. An empty value stays empty."""
    if raw is None or raw == '':
        return ''
    if isinstance(raw, str) and raw.startswith(PREFIX):
        return raw  # already ciphertext — do not double-encrypt
    token = _cipher().encrypt(str(raw).encode('utf-8')).decode('ascii')
    return f'{PREFIX}{token}'


def decrypt_value(stored):
    """Decrypt a stored secret.

    Returns '' when the value cannot be read — which happens for real after
    ENCRYPTION_KEY is rotated, since existing rows do not re-encrypt themselves.
    Degrading here is deliberate: an unreadable token must surface as "not
    configured" on a settings page the owner can fix, not as a 500 that takes
    the whole location detail page down with it.
    """
    if not stored:
        return ''
    if not str(stored).startswith(PREFIX):
        # Written before this field was encrypted, or hand-edited in the DB.
        # Return it so nothing breaks, but say so — it needs re-saving.
        logger.warning('Found an unencrypted credential value; re-save to encrypt it.')
        return str(stored)

    from cryptography.fernet import InvalidToken

    try:
        return _cipher().decrypt(str(stored)[len(PREFIX):].encode('ascii')).decode('utf-8')
    except (InvalidToken, ImproperlyConfigured, ValueError):
        # Never log the value or the exception detail — both can leak material.
        logger.error(
            'A stored credential could not be decrypted. ENCRYPTION_KEY may have '
            'been rotated; the credential must be re-entered.'
        )
        return ''


def mask_secret(raw, keep=4):
    """A safe-to-render hint that a secret exists, e.g. `••••••••3f2a`.

    Shows only the LAST few characters. Never the first, which for many provider
    keys encode the account and key type.
    """
    if not raw:
        return ''
    text = str(raw)
    if len(text) <= keep:
        return '•' * 8
    return '•' * 8 + text[-keep:]


class EncryptedCharField(models.CharField):
    """A CharField whose value is encrypted at rest.

    Reads and writes transparently in Python; the database only ever sees
    ciphertext. Deliberately NOT searchable — an encrypted column cannot be
    filtered on, and needing to would mean this data is being used for something
    it should not be.
    """

    description = 'A string encrypted at rest with Fernet'

    def __init__(self, *args, **kwargs):
        # Ciphertext is far longer than plaintext; see the module docstring.
        kwargs.setdefault('max_length', 512)
        super().__init__(*args, **kwargs)

    # NOTE: `deconstruct` is deliberately NOT overridden to hide `max_length`.
    # Stripping it would keep migrations tidy but unpin the column width — a later
    # change to the default above would then alter the schema silently, because
    # the deconstructed output would not change and no migration would be
    # generated. The width belongs in the migration.

    def from_db_value(self, value, expression, connection):
        return decrypt_value(value)

    def to_python(self, value):
        if value is None:
            return ''
        if isinstance(value, str) and value.startswith(PREFIX):
            return decrypt_value(value)
        return value

    def get_prep_value(self, value):
        return encrypt_value(super().get_prep_value(value))
