"""Shared view toolkit — the imports and small helpers every view module uses.

Entity modules pull it with `from apps.accounts.views._common import *`.

Helpers used by MORE THAN ONE sub-module go in `views/_helpers.py`; helpers used by
a single entity stay in that entity's own module.
"""
from django.conf import settings  # noqa: F401
from django.contrib import messages  # noqa: F401
from django.contrib.auth.decorators import login_required  # noqa: F401
from django.core.paginator import Paginator  # noqa: F401
from django.db.models import Q  # noqa: F401
from django.http import Http404, HttpResponseRedirect  # noqa: F401
from django.shortcuts import get_object_or_404, redirect, render  # noqa: F401
from django.urls import reverse, reverse_lazy  # noqa: F401
from django.utils import timezone  # noqa: F401
from django.views.decorators.http import require_http_methods, require_POST  # noqa: F401

__all__ = [
    'settings',
    'messages',
    'login_required',
    'Paginator',
    'Q',
    'Http404',
    'HttpResponseRedirect',
    'get_object_or_404',
    'redirect',
    'render',
    'reverse',
    'reverse_lazy',
    'timezone',
    'require_http_methods',
    'require_POST',
    'paginate',
]

#: Rows per page on every list surface in the product.
PAGE_SIZE = 25


def paginate(request, queryset, per_page=PAGE_SIZE):
    """Paginate `queryset` and return `(page_obj, elided_page_range)`.

    A junk or out-of-range `?page=` degrades to the first/last valid page rather
    than raising — a malformed query parameter must never 500 a list view.

    The elided range is what `partials/_pagination.html` renders, so a list with
    hundreds of pages does not emit hundreds of links.
    """
    paginator = Paginator(queryset, per_page)

    raw_page = (request.GET.get('page') or '1').strip()
    try:
        number = int(raw_page)
    except (TypeError, ValueError):
        number = 1
    number = max(1, min(number, paginator.num_pages))

    page_obj = paginator.get_page(number)
    try:
        elided = list(paginator.get_elided_page_range(page_obj.number))
    except Exception:  # pragma: no cover - defensive; get_page already clamped
        elided = list(paginator.page_range)

    return page_obj, elided
