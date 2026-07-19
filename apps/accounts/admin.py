"""Admin registrations for Module 0.

The admin is a staff-only convenience surface, not the product UI. The product's
own user management is sub-module 0.3.
"""
from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm
from django.contrib.auth.password_validation import validate_password

from apps.accounts.models import User, UserLocation


class AdminUserCreationForm(forms.ModelForm):
    """Create a user from the admin.

    Django's stock `UserCreationForm` is not usable here: it is built around a
    `username` login field, while this project's `USERNAME_FIELD` is `email` and a
    user is only meaningful alongside its tenant. Declaring the form explicitly is
    clearer than bending the stock one, and it keeps the password hashed — the one
    thing that must not go wrong on this page.
    """

    password1 = forms.CharField(label='Password', strip=False,
                                widget=forms.PasswordInput)
    password2 = forms.CharField(label='Confirm password', strip=False,
                                widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ('tenant', 'email', 'username', 'tier', 'status')

    def clean_password2(self):
        first = self.cleaned_data.get('password1')
        second = self.cleaned_data.get('password2')
        if first and second and first != second:
            raise forms.ValidationError('The two passwords do not match.')
        validate_password(second, self.instance)
        return second

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user


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

    add_form = AdminUserCreationForm
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
                       'password1', 'password2'),
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
