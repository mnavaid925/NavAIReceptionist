"""URLconf for Module 0 — Accounts & Access.

A FLAT module, not a package: a compact `crud()` factory generating the five
standard routes per model beats expanding this into per-entity `urlpatterns` lists
with dozens of duplicated `path()` calls. The factory IS the better structure here.

ORDER IS BEHAVIOUR. Django resolves first-match-wins, so every literal route must
precede any `<int:pk>` route that could swallow it. `crud()` emits its own literals
(`create/`) before its member routes for exactly that reason, and the module-level
literals below are listed ahead of every `crud()` block.
"""
from django.urls import path

from apps.accounts import views

app_name = 'accounts'


def crud(base, name, view_module=views, extra=()):
    """Return the five standard CRUD routes for one entity.

        crud('users', 'user')  ->  user_list / user_create / user_detail
                                   user_edit / user_delete

    `base` is the URL path segment (plural), `name` the url-name stem (singular).
    Views are looked up as `<name>_list_view`, `<name>_create_view`, and so on, so
    an entity that follows the naming convention needs one line here.

    `extra` takes `(path_suffix, view_suffix, name_suffix)` triples for secondary
    actions on the same entity; they are emitted BEFORE the `<int:pk>` routes only
    when their suffix is a literal.
    """
    def view(suffix):
        return getattr(view_module, f'{name}_{suffix}_view')

    literal_routes = [
        path(f'{base}/', view('list'), name=f'{name}_list'),
        path(f'{base}/create/', view('create'), name=f'{name}_create'),
    ]
    for path_suffix, view_suffix, name_suffix in extra:
        literal_routes.append(
            path(f'{base}/{path_suffix}/', view(view_suffix), name=f'{name}_{name_suffix}')
        )

    member_routes = [
        path(f'{base}/<int:pk>/', view('detail'), name=f'{name}_detail'),
        path(f'{base}/<int:pk>/edit/', view('edit'), name=f'{name}_edit'),
        path(f'{base}/<int:pk>/delete/', view('delete'), name=f'{name}_delete'),
    ]
    return literal_routes + member_routes


urlpatterns = [
    # -- 0.1 Authentication & Session ------------------------------------- #
    path('', views.dashboard_view, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('password-reset/', views.password_reset_request_view,
         name='password_reset_request'),
    path('password-reset/<uidb64>/<token>/', views.password_reset_confirm_view,
         name='password_reset_confirm'),
]

# Later sub-modules append their crud() blocks here:
#   urlpatterns += crud('users', 'user')            # 0.3 User Directory
# Keep them AFTER the literals above.
