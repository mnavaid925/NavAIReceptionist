"""Model package for Module 4 — Calendar & Bookings.

Re-exports every model this app owns so `from apps.scheduling.models import X`
works regardless of which sub-module folder X actually lives in. Adding a model
without adding it here is a bug: Django's app registry finds it (it walks the
package), but every import site in the project fails with an ImportError.

Sub-module folders, in build order:

* `ContactDirectory/`  — 4.1  Contact
"""
from apps.scheduling.models.ContactDirectory.Contacts import Contact

__all__ = ['Contact']
