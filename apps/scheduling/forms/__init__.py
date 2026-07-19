"""Form package for Module 4 — Calendar & Bookings.

Re-exports every form this app owns. Adding a form without adding it here means
`from apps.scheduling.forms import X` raises ImportError at view-import time.

Sub-module folders, in build order:

* `ContactDirectory/`  — 4.1  ContactForm
"""
from apps.scheduling.forms.ContactDirectory.Contacts import ContactForm

__all__ = ['ContactForm']
