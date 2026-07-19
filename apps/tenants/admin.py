from django.contrib import admin

from apps.tenants.models import Location, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'customer_id', 'slug', 'timezone', 'is_active', 'created_at')
    list_filter = ('is_active', 'timezone')
    search_fields = ('name', 'slug', 'customer_id')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('name',)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'city', 'state', 'timezone', 'is_active')
    list_filter = ('is_active', 'tenant', 'timezone')
    search_fields = ('name', 'slug', 'city', 'postal_code', 'phone')
    list_select_related = ('tenant',)
    ordering = ('tenant__name', 'name')
