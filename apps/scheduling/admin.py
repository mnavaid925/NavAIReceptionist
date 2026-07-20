from django.contrib import admin

from apps.scheduling.models import (Appointment, CallbackRequest, Contact,
                                    Resource, Service)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'tenant', 'phone_e164', 'email', 'source',
                    'anonymized_at', 'created_at')
    list_filter = ('source', 'tenant')
    search_fields = ('first_name', 'last_name', 'phone_e164', 'email')
    list_select_related = ('tenant',)
    ordering = ('tenant__name', 'last_name', 'first_name')
    # `source` records how the row came into existence. Editable in the admin
    # (unlike the product form) because fixing a mis-stamped import is a genuine
    # back-office need, but never editable by a tenant user.
    # `anonymized_at` is readonly on purpose: clearing it in the admin would not
    # bring the erased details back, it would only make an erased row look
    # un-erased. The record of when erasure happened must not be editable.
    readonly_fields = ('created_at', 'updated_at', 'anonymized_at')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'location_label', 'duration_minutes',
                    'buffer_minutes', 'requires_resource', 'is_active',
                    'display_order')
    list_filter = ('is_active', 'requires_resource', 'tenant', 'location')
    search_fields = ('name', 'description')
    list_select_related = ('tenant', 'location')
    ordering = ('tenant__name', 'display_order', 'name')


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'resource_number', 'tenant', 'location', 'is_active',
                    'display_order')
    list_filter = ('is_active', 'tenant', 'location')
    search_fields = ('name', 'resource_number', 'description')
    list_select_related = ('tenant', 'location')
    ordering = ('tenant__name', 'location__name', 'display_order', 'name')


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('start_at', 'contact', 'service', 'provider', 'resource',
                    'location', 'status', 'source')
    list_filter = ('status', 'source', 'tenant', 'location')
    search_fields = ('contact__first_name', 'contact__last_name',
                     'contact__phone_e164', 'reason')
    list_select_related = ('tenant', 'location', 'contact', 'service',
                           'resource', 'provider')
    date_hierarchy = 'start_at'
    ordering = ('-start_at',)
    # `end_at` is derived from the service duration and `source` is provenance;
    # both are server-owned. Editable here only because the admin is a break-glass
    # tool, but the cancellation stamps stay readonly so a cancellation cannot be
    # backdated into looking like something it was not.
    readonly_fields = ('created_at', 'updated_at', 'cancelled_at')


@admin.register(CallbackRequest)
class CallbackRequestAdmin(admin.ModelAdmin):
    # `caller_name` / `caller_phone` sit next to `contact` rather than behind it:
    # the unidentified caller is the routine case on an inbound call, so a row
    # with a blank `contact` is normal and the free text is the only identity
    # there is. Showing one without the other would make half the queue unusable.
    list_display = ('status', 'location', 'tenant', 'contact', 'caller_name',
                    'caller_phone', 'source', 'created_at')
    list_filter = ('status', 'source', 'tenant', 'location')
    search_fields = ('caller_name', 'caller_phone', 'reason',
                     'contact__first_name', 'contact__last_name')
    list_select_related = ('tenant', 'location', 'contact')
    ordering = ('-created_at',)
    # `status` stays editable — it is an operational queue position, not a
    # historical fact, and the product form already permits any of the three.
    # `source` is server-stamped provenance and never a product form field, but
    # is editable here for the same break-glass reason as Contact.source.
    readonly_fields = ('created_at', 'updated_at')
