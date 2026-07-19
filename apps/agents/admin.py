"""Admin for Module 2.

The auth token is `readonly` and rendered through a MASK, never as a value.
Django's admin renders a plain CharField as an editable text box whose `value=`
attribute carries the current contents — for this field that would put a live
Twilio credential into the page source of every admin change form.
"""
from django.contrib import admin

from apps.agents.models import AgentSetting


@admin.register(AgentSetting)
class AgentSettingAdmin(admin.ModelAdmin):
    list_display = ('location', 'tenant', 'enabled', 'inbound_phone_number',
                    'transfer_enabled', 'token_state')
    list_filter = ('enabled', 'transfer_enabled', 'voice_provider', 'tenant')
    search_fields = ('location__name', 'inbound_phone_number', 'twilio_account_sid')
    list_select_related = ('tenant', 'location')
    autocomplete_fields = ('location',)
    readonly_fields = ('token_state', 'created_at', 'updated_at')

    fieldsets = (
        (None, {'fields': ('tenant', 'location', 'enabled', 'voice_provider')}),
        ('Agent', {'fields': ('greeting', 'prompt_text', 'variables')}),
        ('Twilio', {
            'fields': ('inbound_phone_number', 'twilio_account_sid', 'token_state'),
            'description': 'The auth token is encrypted at rest and never shown. '
                           'Set or replace it from the product UI, not here.',
        }),
        ('Transfer', {'fields': ('transfer_enabled', 'transfer_phone_number',
                                 'transfer_secondary_number', 'transfer_timezone',
                                 'transfer_working_hours', 'transfer_keywords')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

    @admin.display(description='Auth token')
    def token_state(self, obj):
        """Whether a token exists — masked, never the value."""
        return obj.masked_auth_token or 'Not set'
