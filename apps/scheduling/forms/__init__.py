"""Form package for Module 4 — Calendar & Bookings.

Re-exports every form this app owns. Adding a form without adding it here means
`from apps.scheduling.forms import X` raises ImportError at view-import time.

Sub-module folders, in build order:

* `ContactDirectory/`   — 4.1  ContactForm
* `ServicesResources/`  — 4.2  ServiceForm, ResourceForm
"""
from apps.scheduling.forms.ContactDirectory.Contacts import ContactForm
from apps.scheduling.forms.ServicesResources.Resources import ResourceForm
from apps.scheduling.forms.ServicesResources.Services import ServiceForm

__all__ = ['ContactForm', 'ServiceForm', 'ResourceForm']
