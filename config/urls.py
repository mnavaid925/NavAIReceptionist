"""Root URLconf.

Each module's app is included under its own prefix as it is built. Module 0
(`accounts`) owns the site root, because the dashboard and the login page are the
application's entry points.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    # Module 1 is mounted under a prefix; accounts owns the site root, so it must
    # be included LAST or its catch-all dashboard route would shadow everything.
    path('manage/', include('apps.tenants.urls')),
    path('agent/', include('apps.agents.urls')),
    path('', include('apps.accounts.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
