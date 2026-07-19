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
"""
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.urls import NoReverseMatch, reverse

CATALOG_FILENAME = 'NavAIReceptionist.md'

_MODULE_RE = re.compile(r'^##\s+(\d+)\.\s+(.+?)\s*$')
_SUBMODULE_RE = re.compile(r'^###\s+(\d+\.\d+)\s+(.+?)\s*$')

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
    # 0.1's four features are all pre-authentication surfaces (login, logout,
    # forgot/reset password, throttling) — none is a page a signed-in user would
    # click from the sidebar. The dashboard is the reachable proof that
    # customer-scoped login works, so it is this sub-module's representative link.
    '0.1': {'Dashboard': 'accounts:dashboard'},
    '0.2': {'Change Password': 'accounts:change_password',
            'Change Email': 'accounts:change_email'},
    '0.3': {'My Profile': 'accounts:profile',
            'Users': 'accounts:user_list'},
    # The assigned-location list is the dashboard's "Your locations" table; the
    # switcher itself lives in the topbar, since it applies to every page rather
    # than being somewhere you navigate to.
    '0.4': {'My Locations': 'accounts:dashboard'},
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


def build_sidebar(current_path=''):
    """Return the catalog decorated with live links and active-state flags."""
    tree = []

    for module in parse_catalog():
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

            is_live = bool(links)
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
