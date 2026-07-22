"""Sidebar catalog — the module 0-5 tree, and which parts of it are actually built.

Three pieces:

* `parse_catalog()` reads the headings out of `NavAIReceptionist.md`, the scope
  authority, so the sidebar can never drift from the documented module list.
* `MODULE_ICONS` maps a module number to its Lucide icon.
* `LIVE_LINKS` is the build-state ledger. A sub-module is BUILT if and only if it
  has a `LIVE_LINKS["N.M"]` entry — that is what turns its sidebar row from a
  greyed-out roadmap placeholder into a real link. Every `/next-module` run adds
  EXACTLY ONE entry and touches no other.

Value shape: `{"N.M": {"<Feature label>": "<app_name>:<url_name>"}}`.

**Presence of the key means BUILT; the links are optional.** A sub-module whose
surfaces are not pages a signed-in user navigates to — 0.1 is login, logout,
password reset and throttling — maps to an empty dict. It still counts as built
and still shows in the sidebar, it just contributes no link. Pointing such a
sub-module at some other module's page instead produces a duplicate row that
appears to do nothing when clicked.
"""
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.urls import NoReverseMatch, reverse

CATALOG_FILENAME = 'NavAIReceptionist.md'

_MODULE_RE = re.compile(r'^##\s+(\d+)\.\s+(.+?)\s*$')
_SUBMODULE_RE = re.compile(r'^###\s+(\d+\.\d+)\s+(.+?)\s*$')

# Module 0 is deliberately absent from the SIDEBAR. Its surfaces are personal
# account settings, not day-to-day operational areas, so they live in the topbar
# user dropdown and as tabs across the account pages instead. The module keeps its
# LIVE_LINKS entries regardless — those are the build-state ledger, and dropping
# them would make finished sub-modules read as unbuilt.
SIDEBAR_EXCLUDED_MODULES = {'0'}

MODULE_ICONS = {
    '0': 'shield-check',
    '1': 'building-2',
    '2': 'bot',
    '3': 'radio',
    '4': 'calendar-days',
    '5': 'phone-call',
}

# ---------------------------------------------------------------------------
# BUILD STATE. One entry per built sub-module. Add exactly one per module run.
# ---------------------------------------------------------------------------
LIVE_LINKS = {
    # BUILT, but deliberately contributes no sidebar link: all four of 0.1's
    # features (login, logout, forgot/reset password, throttling) are
    # pre-authentication surfaces or topbar controls. There is no page here for a
    # signed-in user to navigate to, and pointing this at the dashboard just
    # duplicated the sidebar's own Dashboard row.
    '0.1': {},
    '0.2': {'Change Password': 'accounts:change_password',
            'Change Email': 'accounts:change_email'},
    '0.3': {'My Profile': 'accounts:profile',
            'Users': 'accounts:user_list'},
    '0.4': {'My Locations': 'accounts:my_locations'},
    '1.1': {'Business Settings': 'tenants:business_settings'},
    '1.2': {'Locations': 'tenants:location_list'},
    '1.3': {'Staff & Locations': 'tenants:staff_locations'},
    '1.4': {'Working Hours': 'tenants:provider_hours_report'},
    '2.1': {'Agent Setup': 'agents:agent_setup'},
    '2.2': {'Twilio Connection': 'agents:twilio_connection'},
    '2.3': {'Transfer Settings': 'agents:transfer_settings'},
    '2.4': {'Test Call': 'agents:test_call'},
    # Module 3 is the service module — no CRUD. 3.1's one navigable surface is the
    # runtime diagnostics page (the webhook itself answers a carrier, not a user).
    '3.1': {'Runtime Diagnostics': 'runtime:diagnostics'},
    # BUILT, and deliberately contributes no sidebar link (same posture as 0.1 /
    # 5.2-5.4). 3.2's surfaces — the media-stream consumer and the `simulate_call`
    # management command — are not pages a signed-in user navigates to. What 3.2
    # makes real is 3.1's existing "active calls" stat on the diagnostics page: it
    # reads zero until 3.2's disconnect() is the first code to move a session out
    # of `in_progress`. Pointing this at runtime:diagnostics would just duplicate
    # 3.1's row.
    '3.2': {},
    '4.1': {'Contacts': 'scheduling:contact_list'},
    '4.2': {'Services': 'scheduling:service_list',
            'Resources': 'scheduling:resource_list'},
    '4.3': {'Appointments': 'scheduling:appointment_list',
            'Find a slot': 'scheduling:appointment_slots'},
    '4.4': {'Calendar': 'scheduling:calendar_day',
            'Week view': 'scheduling:calendar_week'},
    '4.5': {'Callback Requests': 'scheduling:callbackrequest_list'},
    '5.1': {'Call Logs': 'calls:callsession_list'},
    # BUILT, and deliberately contributes no sidebar link. 5.2's surfaces — the
    # transcript panel, the analysis panel and the print view — are all reached
    # THROUGH the call detail page that 5.1's 'Call Logs' link already leads to.
    # Pointing this at callsession_detail would need a pk it does not have, and
    # pointing it back at the list would just duplicate 5.1's row. Same posture
    # as 0.1.
    '5.2': {},
    # BUILT, empty for the same reason as 5.2: the event log and cost breakdown
    # are two more cards on the call detail page that 5.1's 'Call Logs' link
    # already reaches. No page of its own to point at.
    '5.3': {},
    # BUILT, empty like 5.2/5.3: the recording player and transfer outcome are the
    # last two cards on the call detail page 5.1's 'Call Logs' link already reaches.
    # With this, Module 5 is complete. The signed-media SERVE route is not a
    # navigable page — it streams bytes — so it has nothing to contribute here.
    '5.4': {},
}


@lru_cache(maxsize=1)
def parse_catalog():
    """Return the module tree parsed from `NavAIReceptionist.md`.

    Shape::

        [{'number': '0',
          'title': 'Accounts & Access',
          'icon': 'shield-check',
          'submodules': [{'key': '0.1', 'title': 'Authentication & Session'}, ...]},
         ...]

    Degrades to an empty list if the catalog file is missing or unreadable — a
    missing doc must not take the whole application shell down with it.
    """
    path = Path(settings.BASE_DIR) / CATALOG_FILENAME
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return []

    modules = []
    current = None
    in_code_fence = False

    for line in text.splitlines():
        # Headings inside a fenced block are content, not structure.
        if line.startswith('```'):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue

        module_match = _MODULE_RE.match(line)
        if module_match:
            number, title = module_match.groups()
            current = {
                'number': number,
                'title': title,
                'icon': MODULE_ICONS.get(number, 'circle'),
                'submodules': [],
            }
            modules.append(current)
            continue

        submodule_match = _SUBMODULE_RE.match(line)
        if submodule_match and current is not None:
            key, title = submodule_match.groups()
            # Guard against a stray `### 4.1` appearing under module 3.
            if key.split('.')[0] == current['number']:
                current['submodules'].append({'key': key, 'title': title})

    return modules


def _resolve(url_name):
    """Reverse a url name, returning None instead of raising.

    A typo in `LIVE_LINKS` should grey out one sidebar row, not 500 every page in
    the application.
    """
    try:
        return reverse(url_name)
    except NoReverseMatch:
        return None


# The account area's tab strip — Module 0's surfaces, which no longer appear in
# the sidebar. `tiers` restricts a tab to those User.tier values; None means
# everyone. Order is the order they render in.
ACCOUNT_TABS = [
    {'label': 'Profile', 'url_name': 'accounts:profile',
     'icon': 'user', 'tiers': None},
    {'label': 'My Locations', 'url_name': 'accounts:my_locations',
     'icon': 'map-pin', 'tiers': None},
    {'label': 'Password', 'url_name': 'accounts:change_password',
     'icon': 'key-round', 'tiers': None},
    {'label': 'Email', 'url_name': 'accounts:change_email',
     'icon': 'mail', 'tiers': None},
    {'label': 'Users', 'url_name': 'accounts:user_list',
     'icon': 'users', 'tiers': ('owner', 'manager')},
]


def build_account_tabs(user, current_path=''):
    """The account-area tab strip for `user`.

    A tab whose url does not resolve is dropped rather than rendered dead, and a
    tab the user's tier cannot open is never shown — the views enforce that
    independently, so this only avoids offering a link that would bounce them.
    """
    if not (user and user.is_authenticated):
        return []

    tabs = []
    for spec in ACCOUNT_TABS:
        if spec['tiers'] and getattr(user, 'tier', None) not in spec['tiers']:
            continue
        url = _resolve(spec['url_name'])
        if not url:
            continue
        tabs.append({
            'label': spec['label'],
            'icon': spec['icon'],
            'url': url,
            'is_active': bool(current_path) and current_path.startswith(url),
        })
    return tabs


def build_sidebar(current_path=''):
    """Return the catalog decorated with live links and active-state flags."""
    tree = []

    for module in parse_catalog():
        if module['number'] in SIDEBAR_EXCLUDED_MODULES:
            continue
        submodules = []
        module_is_live = False

        for submodule in module['submodules']:
            links = []
            for label, url_name in LIVE_LINKS.get(submodule['key'], {}).items():
                url = _resolve(url_name)
                if url:
                    links.append({
                        'label': label,
                        'url': url,
                        'is_active': bool(current_path) and current_path.startswith(url) and url != '/',
                    })

            # Built is decided by the KEY, not by whether it produced links — a
            # sub-module can be finished and still have nothing to navigate to.
            is_live = submodule['key'] in LIVE_LINKS
            module_is_live = module_is_live or is_live
            submodules.append({
                'key': submodule['key'],
                'title': submodule['title'],
                'links': links,
                'is_live': is_live,
                'is_active': any(link['is_active'] for link in links),
            })

        tree.append({
            'number': module['number'],
            'title': module['title'],
            'icon': module['icon'],
            'submodules': submodules,
            'is_live': module_is_live,
            'is_active': any(sub['is_active'] for sub in submodules),
            'dom_id': f'nav-module-{module["number"]}',
        })

    return tree
