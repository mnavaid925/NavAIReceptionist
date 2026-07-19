"""Provider working-hours form (sub-module 1.4).

One interval per form, several forms per location, via a plain formset. The
formset writes nothing itself — the view hands the cleaned intervals to
`apps.tenants.services.validate_provider_hours` and `set_provider_hours`, so the
JSON shape has exactly one writer.
"""
from apps.tenants.forms._common import *  # noqa: F401,F403
from apps.tenants.services import WEEKDAYS, format_hhmm, parse_hhmm

__all__ = ['IntervalForm', 'IntervalFormSet', 'build_interval_initial']


class IntervalForm(forms.Form):  # noqa: F405
    """A single working window: a start, an end, and the days it applies to."""

    start_time = forms.CharField(  # noqa: F405
        label='From', required=False,
        widget=forms.TimeInput(attrs={'type': 'time'}),  # noqa: F405
    )
    end_time = forms.CharField(  # noqa: F405
        label='To', required=False,
        widget=forms.TimeInput(attrs={'type': 'time'}),  # noqa: F405
    )
    days = forms.MultipleChoiceField(  # noqa: F405
        label='Days', required=False, choices=WEEKDAYS,
        widget=forms.CheckboxSelectMultiple,  # noqa: F405
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_widgets(self)  # noqa: F405

    @property
    def is_blank(self):
        """True when the row was left entirely empty — it is simply skipped."""
        if not self.is_bound:
            return not (self.initial.get('start_time') or self.initial.get('end_time'))
        data = getattr(self, 'cleaned_data', None) or {}
        return not (data.get('start_time') or data.get('end_time') or data.get('days'))

    def clean(self):
        cleaned = super().clean()
        start_raw = (cleaned.get('start_time') or '').strip()
        end_raw = (cleaned.get('end_time') or '').strip()
        days = cleaned.get('days') or []

        # A wholly empty row is not an error — it is an unused slot in the editor.
        if not start_raw and not end_raw and not days:
            return cleaned

        start = parse_hhmm(start_raw)
        end = parse_hhmm(end_raw)

        if start is None:
            self.add_error('start_time', 'Enter a start time.')
        if end is None:
            self.add_error('end_time', 'Enter an end time.')
        if start and end and end <= start:
            self.add_error('end_time', 'The end time must be after the start time.')
        if not days:
            self.add_error('days', 'Choose at least one day.')

        cleaned['start_time'] = format_hhmm(start) if start else ''
        cleaned['end_time'] = format_hhmm(end) if end else ''
        return cleaned


#: Six rows is enough for a split shift plus spares, without an unbounded form.
IntervalFormSet = forms.formset_factory(  # noqa: F405
    IntervalForm, extra=0, min_num=0, max_num=12, validate_max=True, can_delete=False
)


def build_interval_initial(intervals, minimum_rows=3):
    """Turn stored intervals into formset `initial`, padded with blank rows."""
    initial = [
        {
            'start_time': format_hhmm(item['start_time']),
            'end_time': format_hhmm(item['end_time']),
            'days': item['days'],
        }
        for item in intervals
    ]
    while len(initial) < minimum_rows:
        initial.append({'start_time': '', 'end_time': '', 'days': []})
    return initial
