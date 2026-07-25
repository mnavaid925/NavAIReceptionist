"""Tests for `apps/accounts/navigation.py` — the sidebar catalog and account
tab strip.

The key property under test is graceful degradation: a `LIVE_LINKS` entry
naming a url that does not reverse must grey that one row out, never 500 the
whole page, and a missing/unreadable catalog file must degrade to an empty
tree rather than crashing every page's render.
"""
import pytest

from apps.accounts import navigation as nav

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    """`parse_catalog()` is `@lru_cache(maxsize=1)` — tests that monkeypatch
    `BASE_DIR`/`CATALOG_FILENAME` must not leak a cached result into (or out of)
    other tests.
    """
    nav.parse_catalog.cache_clear()
    yield
    nav.parse_catalog.cache_clear()


# --------------------------------------------------------------------------- #
# _resolve() — the guard the whole degrade-gracefully story depends on
# --------------------------------------------------------------------------- #

def test_resolve_returns_none_for_a_url_name_that_does_not_reverse():
    assert nav._resolve('accounts:this-does-not-exist') is None


def test_resolve_returns_the_url_for_a_real_name():
    assert nav._resolve('accounts:login') == '/login/'


# --------------------------------------------------------------------------- #
# parse_catalog()
# --------------------------------------------------------------------------- #

def test_parse_catalog_returns_a_nonempty_tree_from_the_real_file():
    modules = nav.parse_catalog()
    assert modules
    numbers = {m['number'] for m in modules}
    assert {'0', '1', '2', '3', '4', '5'} <= numbers


def test_parse_catalog_assigns_icons_from_the_module_icon_map():
    modules = nav.parse_catalog()
    module_0 = next(m for m in modules if m['number'] == '0')
    assert module_0['icon'] == nav.MODULE_ICONS['0']


def test_parse_catalog_degrades_to_empty_list_when_the_file_is_missing(tmp_path, settings):
    settings.BASE_DIR = tmp_path
    nav.parse_catalog.cache_clear()
    assert nav.parse_catalog() == []


def test_parse_catalog_degrades_to_empty_list_on_unreadable_bytes(tmp_path, settings):
    bad_file = tmp_path / nav.CATALOG_FILENAME
    bad_file.write_bytes(b'\xff\xfe\x00\x00not-utf8\xff')
    settings.BASE_DIR = tmp_path
    nav.parse_catalog.cache_clear()
    assert nav.parse_catalog() == []


def test_parse_catalog_ignores_headings_inside_a_fenced_code_block(tmp_path, settings):
    (tmp_path / nav.CATALOG_FILENAME).write_text(
        '## 0. Accounts\n'
        '### 0.1 Auth\n'
        '```\n'
        '## 9. Not A Real Module\n'
        '### 9.9 Not A Real Submodule\n'
        '```\n'
        '### 0.2 Credentials\n',
        encoding='utf-8',
    )
    settings.BASE_DIR = tmp_path
    nav.parse_catalog.cache_clear()

    modules = nav.parse_catalog()
    assert len(modules) == 1
    assert [s['key'] for s in modules[0]['submodules']] == ['0.1', '0.2']


def test_parse_catalog_guards_against_a_stray_submodule_under_the_wrong_module(tmp_path, settings):
    (tmp_path / nav.CATALOG_FILENAME).write_text(
        '## 0. Accounts\n'
        '### 0.1 Auth\n'
        '### 4.1 Contacts\n'  # belongs to module 4, must not attach to module 0
        '## 4. Scheduling\n',
        encoding='utf-8',
    )
    settings.BASE_DIR = tmp_path
    nav.parse_catalog.cache_clear()

    modules = nav.parse_catalog()
    module_0 = next(m for m in modules if m['number'] == '0')
    assert [s['key'] for s in module_0['submodules']] == ['0.1']


# --------------------------------------------------------------------------- #
# build_sidebar()
# --------------------------------------------------------------------------- #

def test_build_sidebar_excludes_module_0():
    tree = nav.build_sidebar()
    assert all(m['number'] != '0' for m in tree)


def test_build_sidebar_marks_a_catalogued_submodule_as_live_when_it_has_a_live_links_entry():
    tree = nav.build_sidebar()
    module_1 = next(m for m in tree if m['number'] == '1')
    sub_1_1 = next(s for s in module_1['submodules'] if s['key'] == '1.1')
    assert sub_1_1['is_live'] is True
    assert sub_1_1['links']


def test_build_sidebar_never_raises_when_a_live_links_entry_has_a_bad_url_name(monkeypatch):
    """The explicit `_resolve()` guard: a bogus url name greys the row's LINKS
    out (empty `links`) rather than raising, while the submodule still reads as
    built and every other row on the page renders normally.
    """
    patched = dict(nav.LIVE_LINKS)
    patched['1.1'] = {'Business Settings': 'tenants:this-url-name-does-not-exist'}
    monkeypatch.setattr(nav, 'LIVE_LINKS', patched)

    tree = nav.build_sidebar()  # must not raise

    module_1 = next(m for m in tree if m['number'] == '1')
    sub_1_1 = next(s for s in module_1['submodules'] if s['key'] == '1.1')
    assert sub_1_1['is_live'] is True
    assert sub_1_1['links'] == []

    # Every other submodule's own links are unaffected by 1.1's bad entry.
    sub_1_2 = next(s for s in module_1['submodules'] if s['key'] == '1.2')
    assert sub_1_2['links']


def test_build_sidebar_a_submodule_with_no_live_links_entry_is_not_live():
    tree = nav.build_sidebar()
    module_1 = next(m for m in tree if m['number'] == '1')
    keyed = {s['key']: s for s in module_1['submodules']}
    # Any real, catalogued sub-module that has not shipped yet (not present in
    # LIVE_LINKS at all) must read as not-live with no links.
    not_yet_built = [s for s in keyed.values() if s['key'] not in nav.LIVE_LINKS]
    for submodule in not_yet_built:
        assert submodule['is_live'] is False
        assert submodule['links'] == []


def test_build_sidebar_an_empty_live_links_dict_still_counts_as_built():
    """0.1-shaped entries: present in LIVE_LINKS with an empty dict, no page to
    link to, but still BUILT — presence of the key is what matters, not links.
    """
    assert nav.LIVE_LINKS.get('3.2') == {}
    # 3.2 belongs to module 3, which IS in the sidebar.
    tree = nav.build_sidebar()
    module_3 = next(m for m in tree if m['number'] == '3')
    sub_3_2 = next(s for s in module_3['submodules'] if s['key'] == '3.2')
    assert sub_3_2['is_live'] is True
    assert sub_3_2['links'] == []


def test_build_sidebar_marks_active_state_from_current_path():
    from django.urls import reverse

    tree = nav.build_sidebar(current_path=reverse('tenants:location_list'))
    module_1 = next(m for m in tree if m['number'] == '1')
    assert module_1['is_active'] is True


# --------------------------------------------------------------------------- #
# build_account_tabs()
# --------------------------------------------------------------------------- #

def test_account_tabs_empty_for_anonymous():
    assert nav.build_account_tabs(None) == []


def test_account_tabs_staff_tier_does_not_see_users_tab(member_user):
    tabs = nav.build_account_tabs(member_user)
    labels = [t['label'] for t in tabs]
    assert 'Users' not in labels
    assert 'Profile' in labels


def test_account_tabs_owner_sees_users_tab(admin_user):
    tabs = nav.build_account_tabs(admin_user)
    labels = [t['label'] for t in tabs]
    assert 'Users' in labels


def test_account_tabs_drops_a_tab_whose_url_does_not_resolve(admin_user, monkeypatch):
    bad_tabs = [
        {'label': 'Ghost', 'url_name': 'accounts:not-a-real-url', 'icon': 'ghost', 'tiers': None},
        {'label': 'Profile', 'url_name': 'accounts:profile', 'icon': 'user', 'tiers': None},
    ]
    monkeypatch.setattr(nav, 'ACCOUNT_TABS', bad_tabs)

    tabs = nav.build_account_tabs(admin_user)  # must not raise

    labels = [t['label'] for t in tabs]
    assert 'Ghost' not in labels
    assert 'Profile' in labels


def test_account_tabs_active_tab_matches_current_path(admin_user):
    tabs = nav.build_account_tabs(admin_user, current_path='/profile/')
    profile_tab = next(t for t in tabs if t['label'] == 'Profile')
    assert profile_tab['is_active'] is True
