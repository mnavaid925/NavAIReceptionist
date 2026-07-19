from django.contrib import admin

from apps.scheduling.models import Contact, Resource, Service


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
