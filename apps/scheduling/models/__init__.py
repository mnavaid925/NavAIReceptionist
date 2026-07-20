"""Model package for Module 4 — Calendar & Bookings.

Re-exports every model this app owns so `from apps.scheduling.models import X`
works regardless of which sub-module folder X actually lives in. Adding a model
without adding it here is a bug: Django's app registry finds it (it walks the
package), but every import site in the project fails with an ImportError.

Sub-module folders, in build order:

* `ContactDirectory/`   — 4.1  Contact
* `ServicesResources/`  — 4.2  Service, Resource
* `Bookings/`           — 4.3  Appointment
* `CallbackRequests/`   — 4.5  CallbackRequest

Sub-module 4.4 (calendar views) adds no model of its own — it is a reading
surface over `Appointment`, which is why it has no folder here.
"""
from apps.scheduling.models.Bookings.Appointments import Appointment
from apps.scheduling.models.CallbackRequests.CallbackRequests import CallbackRequest
from apps.scheduling.models.ContactDirectory.Contacts import Contact
from apps.scheduling.models.ServicesResources.Resources import Resource
from apps.scheduling.models.ServicesResources.Services import Service

__all__ = ['Contact', 'Service', 'Resource', 'Appointment', 'CallbackRequest']
