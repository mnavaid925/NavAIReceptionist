/* ==========================================================================
   NavAIReceptionist — layout engine
   ==========================================================================

   Owns every layout variant the product exposes. State lives as data-attributes
   on <html> (theme.css reads them) and is persisted to localStorage.

   This file is loaded in <head> WITHOUT defer, on purpose: the stored preferences
   are applied synchronously before first paint, so a dark-mode user never sees a
   white flash. DOM wiring is deferred to DOMContentLoaded further down.
   ========================================================================== */

(function () {
  'use strict';

  var STORAGE_PREFIX = 'navai.layout.';

  /* Every option, its allowed values and its default. The keys are exactly the
     data-attribute names used in theme.css — one source of truth. */
  var OPTIONS = {
    'theme':         { values: ['light', 'dark'],                            fallback: 'light' },
    'layout':        { values: ['vertical', 'horizontal', 'detached'],       fallback: 'vertical' },
    'sidebar-size':  { values: ['default', 'compact', 'small', 'hover'],     fallback: 'default' },
    'sidebar-theme': { values: ['light', 'dark', 'brand'],                   fallback: 'light' },
    'topbar':        { values: ['light', 'dark'],                            fallback: 'light' },
    'width':         { values: ['fluid', 'boxed'],                           fallback: 'fluid' },
    'position':      { values: ['fixed', 'scrollable'],                      fallback: 'fixed' },
    'preloader':     { values: ['enable', 'disable'],                        fallback: 'enable' }
  };

  var root = document.documentElement;

  function read(key) {
    try {
      return window.localStorage.getItem(STORAGE_PREFIX + key);
    } catch (e) {
      return null;   // private mode / storage disabled — fall back to defaults
    }
  }

  function write(key, value) {
    try {
      window.localStorage.setItem(STORAGE_PREFIX + key, value);
    } catch (e) { /* non-fatal: the option still applies for this page load */ }
  }

  function resolve(key) {
    var spec = OPTIONS[key];
    var stored = read(key);
    if (stored && spec.values.indexOf(stored) !== -1) return stored;

    // No stored theme? Follow the operating system.
    if (key === 'theme' && window.matchMedia &&
        window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark';
    }
    return spec.fallback;
  }

  function apply(key, value, persist) {
    var spec = OPTIONS[key];
    if (!spec || spec.values.indexOf(value) === -1) return;

    root.setAttribute('data-' + key, value);
    if (persist) write(key, value);

    // Keep every control that renders this option in sync, wherever it lives.
    var controls = document.querySelectorAll('[data-option="' + key + '"]');
    for (var i = 0; i < controls.length; i++) {
      var control = controls[i];
      var isActive = control.getAttribute('data-value') === value;
      control.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    }
  }

  /* Direction is stored the same way but lives on the `dir` attribute, which is a
     real HTML feature rather than one of our data-* options. */
  function applyDirection(value, persist) {
    if (value !== 'ltr' && value !== 'rtl') return;
    root.setAttribute('dir', value);
    if (persist) write('direction', value);
    var controls = document.querySelectorAll('[data-option="direction"]');
    for (var i = 0; i < controls.length; i++) {
      controls[i].setAttribute(
        'aria-pressed', controls[i].getAttribute('data-value') === value ? 'true' : 'false'
      );
    }
  }

  // ---- Synchronous pass: applied before first paint. --------------------- //
  for (var key in OPTIONS) {
    if (Object.prototype.hasOwnProperty.call(OPTIONS, key)) {
      apply(key, resolve(key), false);
    }
  }
  applyDirection(read('direction') === 'rtl' ? 'rtl' : 'ltr', false);

  /* Public surface — the settings drawer and the topbar toggle call into this. */
  window.NavAILayout = {
    set: function (key, value) {
      if (key === 'direction') { applyDirection(value, true); }
      else { apply(key, value, true); }
    },
    get: function (key) {
      return key === 'direction' ? root.getAttribute('dir') : root.getAttribute('data-' + key);
    },
    toggleTheme: function () {
      this.set('theme', this.get('theme') === 'dark' ? 'light' : 'dark');
    },
    reset: function () {
      for (var k in OPTIONS) {
        if (Object.prototype.hasOwnProperty.call(OPTIONS, k)) {
          try { window.localStorage.removeItem(STORAGE_PREFIX + k); } catch (e) {}
          apply(k, OPTIONS[k].fallback, false);
        }
      }
      try { window.localStorage.removeItem(STORAGE_PREFIX + 'direction'); } catch (e) {}
      applyDirection('ltr', false);
    }
  };

  // ---- Deferred pass: DOM wiring. ---------------------------------------- //

  function onReady(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  }

  function refreshIcons() {
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons();
    }
  }

  onReady(function () {
    var sidebar = document.getElementById('app-sidebar');
    var drawer = document.getElementById('settings-drawer');

    /* Any element carrying data-option/data-value sets that option. This covers
       the whole settings drawer without a listener per control. */
    document.addEventListener('click', function (event) {
      var optionEl = event.target.closest('[data-option][data-value]');
      if (optionEl) {
        event.preventDefault();
        window.NavAILayout.set(
          optionEl.getAttribute('data-option'),
          optionEl.getAttribute('data-value')
        );
        return;
      }

      if (event.target.closest('[data-action="toggle-theme"]')) {
        event.preventDefault();
        window.NavAILayout.toggleTheme();
        return;
      }

      if (event.target.closest('[data-action="reset-layout"]')) {
        event.preventDefault();
        window.NavAILayout.reset();
        return;
      }

      if (event.target.closest('[data-action="toggle-sidebar"]')) {
        event.preventDefault();
        if (window.matchMedia('(max-width: 1023px)').matches) {
          // Small screens: the sidebar is an overlay drawer.
          if (sidebar) sidebar.classList.toggle('is-open');
        } else {
          // Large screens: cycle between the roomy and the icon-only rail.
          var current = window.NavAILayout.get('sidebar-size');
          window.NavAILayout.set('sidebar-size', current === 'default' ? 'small' : 'default');
        }
        return;
      }

      if (event.target.closest('[data-action="open-settings"]')) {
        event.preventDefault();
        if (drawer) drawer.classList.add('is-open');
        return;
      }

      if (event.target.closest('[data-action="close-settings"]')) {
        event.preventDefault();
        if (drawer) drawer.classList.remove('is-open');
        return;
      }

      // Click outside an open mobile sidebar closes it.
      if (sidebar && sidebar.classList.contains('is-open') &&
          !event.target.closest('#app-sidebar')) {
        sidebar.classList.remove('is-open');
      }
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        if (drawer) drawer.classList.remove('is-open');
        if (sidebar) sidebar.classList.remove('is-open');
      }
      // Ctrl/Cmd-K focuses the topbar search.
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        var search = document.getElementById('topbar-search');
        if (search) { event.preventDefault(); search.focus(); }
      }
    });

    // Collapsible sidebar groups.
    document.addEventListener('click', function (event) {
      var toggle = event.target.closest('[data-nav-toggle]');
      if (!toggle) return;
      event.preventDefault();
      var target = document.getElementById(toggle.getAttribute('data-nav-toggle'));
      if (!target) return;
      var expanded = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', expanded ? 'false' : 'true');
      target.hidden = expanded;
    });

    /* Icons swapped in by HTMX are inert <i> tags until Lucide runs again. */
    document.body.addEventListener('htmx:afterSwap', refreshIcons);
    refreshIcons();

    var preloader = document.getElementById('preloader');
    if (preloader) {
      window.addEventListener('load', function () { preloader.classList.add('is-done'); });
      // Belt and braces: never leave the page hidden behind a stuck preloader.
      window.setTimeout(function () { preloader.classList.add('is-done'); }, 3000);
    }
  });
})();
