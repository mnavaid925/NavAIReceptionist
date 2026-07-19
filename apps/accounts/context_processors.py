"""Template context available on every rendered page.

Supplies the shell: the sidebar catalog, the active location and the set of
locations the signed-in user may switch into.

Everything here is read defensively with `getattr`. This runs for anonymous
requests (the login page), for the superuser (who has `tenant=None` by design)
and for error pages rendered before the middleware has run — none of which may
raise from a context processor, because a failure here breaks every page at once.
"""


# Chrome links that arrive across several sub-module runs. Each is resolved
# defensively, so the shell renders correctly at every point in the build rather
# than 500-ing on a url name that does not exist yet.
OPTIONAL_CHROME_URLS = {
    'switch_location': 'accounts:switch_location',
    'profile': 'accounts:profile',
    'change_password': 'accounts:change_password',
    'change_email': 'accounts:change_email',
    'logout': 'accounts:logout',
    'user_list': 'accounts:user_list',
}


def navigation(request):
    """Sidebar tree, active location and the user's assignable locations."""
    from apps.accounts.navigation import build_sidebar, _resolve

    user = getattr(request, 'user', None)
    is_authenticated = bool(user and user.is_authenticated)

    context = {
        'nav_modules': build_sidebar(request.path) if is_authenticated else [],
        'nav_urls': {key: _resolve(name) for key, name in OPTIONAL_CHROME_URLS.items()},
        'active_tenant': getattr(request, 'tenant', None),
        'active_location': getattr(request, 'location', None),
        'user_locations': [],
    }

    if is_authenticated:
        # Only the locations this user has a UserLocation row for. The switcher
        # re-validates the chosen id server-side too — this list is the UI
        # surface, never the authorization.
        context['user_locations'] = list(getattr(user, 'assigned_locations', lambda: [])())

    return context
