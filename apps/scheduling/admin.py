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

    def delete_queryset(self, request, queryset):
        """Delete one contact at a time so the erasure cascade actually runs.

        The changelist's "Delete selected" action calls `queryset.delete()`,
        which Django executes in bulk WITHOUT instantiating rows — so
        `Contact.delete()` never runs and its scrub of the caller identity
        copied onto linked `CallbackRequest` rows is silently skipped. The FK
        still nulls (it is `SET_NULL`), which is the trap: the bulk delete
        LOOKS like it worked, and leaves `caller_name` / `caller_phone` standing
        on rows no longer attached to anything that could ever be erased again.

        Single-object admin delete is fine — `ModelAdmin.delete_model` calls
        `obj.delete()`. It is only the bulk action that needs this.

        Iterating costs one query per contact instead of one for the batch. On a
        back-office erasure of a handful of people that is the right trade: the
        whole point of the action is that the data is gone.
        """
        for contact in queryset:
            contact.delete()


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
