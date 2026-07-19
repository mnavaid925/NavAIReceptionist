"""Admin registrations for Module 0.

The admin is a staff-only convenience surface, not the product UI. The product's
own user management is sub-module 0.3.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm

from apps.accounts.models import User, UserLocation


class UserLocationInline(admin.TabularInline):
    model = UserLocation
    extra = 0
    autocomplete_fields = ('location',)
    fields = ('tenant', 'location')


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Subclasses Django's UserAdmin so passwords are handled correctly.

    WARNING — do NOT replace this with a plain `admin.ModelAdmin`. `password` is a
    CharField holding a hash; a plain ModelAdmin renders it as an ordinary text box,
    and anything typed into it is saved verbatim as the new "hash". That silently
    destroys the account's ability to log in, with no error at any point.
    `DjangoUserAdmin` renders the read-only hash plus a separate set-password form,
    which is the only safe arrangement.
    """

    change_password_form = AdminPasswordChangeForm

    list_display = ('email', 'username', 'tenant', 'tier', 'status', 'is_provider', 'is_staff')
    list_filter = ('tier', 'status', 'is_provider', 'is_staff', 'tenant')
    search_fields = ('email', 'username', 'full_name', 'primary_phone')
    ordering = ('email',)
    list_select_related = ('tenant',)
    inlines = (UserLocationInline,)

    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        ('Business', {'fields': ('tenant', 'tier', 'status')}),
        ('Profile', {'fields': ('first_name', 'last_name', 'full_name', 'primary_phone')}),
        ('Scheduling', {'fields': ('is_provider', 'provider_hours')}),
        ('Session', {'fields': ('inactivity_timeout', 'last_login')}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('tenant', 'email', 'username', 'tier', 'status',
                       'usable_password', 'password1', 'password2'),
        }),
    )
    readonly_fields = ('last_login',)
    filter_horizontal = ('groups', 'user_permissions')


@admin.register(UserLocation)
class UserLocationAdmin(admin.ModelAdmin):
    list_display = ('user', 'location', 'tenant', 'created_at')
    list_filter = ('tenant', 'location')
    search_fields = ('user__email', 'user__full_name', 'location__name')
    list_select_related = ('user', 'location', 'tenant')
    autocomplete_fields = ('user', 'location')
