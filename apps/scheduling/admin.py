from django.contrib import admin

from apps.scheduling.models import Contact


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
