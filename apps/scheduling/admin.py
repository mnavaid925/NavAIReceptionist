from django.contrib import admin

from apps.scheduling.models import Contact


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'tenant', 'phone_e164', 'email', 'source',
                    'created_at')
    list_filter = ('source', 'tenant')
    search_fields = ('first_name', 'last_name', 'phone_e164', 'email')
    list_select_related = ('tenant',)
    ordering = ('tenant__name', 'last_name', 'first_name')
    # `source` records how the row came into existence. Editable in the admin
    # (unlike the product form) because fixing a mis-stamped import is a genuine
    # back-office need, but never editable by a tenant user.
    readonly_fields = ('created_at', 'updated_at')
