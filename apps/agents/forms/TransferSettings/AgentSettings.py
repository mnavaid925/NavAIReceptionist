"""Transfer settings form (sub-module 2.3).

The weekly window is stored as a JSON dict keyed by weekday. It is edited through
21 generated fields (enabled/start/end per day) rather than a raw JSON box,
because this is the setting that decides whether a caller asking for a human gets
one — it has to be legible to whoever is on the phone at 5pm on a Friday.
"""
from apps.agents.forms._common import *  # noqa: F401,F403
from apps.agents.models import AgentSetting
from apps.agents.services import WEEKDAY_KEYS
from apps.tenants.forms.Business import timezone_choices

__all__ = ['TransferSettingsForm', 'MAX_KEYWORDS']

#: Enough for real phrasing variety; bounded so the runtime's per-utterance scan
#: stays cheap on the hot path.
MAX_KEYWORDS = 20


class TransferSettingsForm(TenantLocationModelForm):  # noqa: F405
    """When and where the agent hands a caller to a human."""

    keywords_text = forms.CharField(  # noqa: F405
        label='Extra escalation phrases',
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),  # noqa: F405
        help_text='One per line. These are ADDED to the built-in phrases (human, '
                  'agent, manager, emergency and similar), never a replacement '
                  'for them.',
    )

    class Meta:
        model = AgentSetting
        fields = (
            'transfer_enabled',
            'transfer_phone_number',
            'transfer_secondary_number',
            'transfer_timezone',
        )
        labels = {
            'transfer_enabled': 'Offer transfer to a human',
            'transfer_phone_number': 'Primary destination',
            'transfer_secondary_number': 'Secondary destination',
            'transfer_timezone': 'Hours are in this timezone',
        }
        help_texts = {
            'transfer_phone_number': 'E.164. The agent always dials this — never a '
                                     'number a caller reads out.',
            'transfer_secondary_number': 'Optional. A second line, e.g. another '
                                         'language or overflow.',
            'transfer_timezone': 'May differ from the location if handoffs go to a '
                                 'central team.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        stored = self.instance.transfer_working_hours or {}
        for day in WEEKDAY_KEYS:
            entry = stored.get(day) if isinstance(stored, dict) else None
            entry = entry if isinstance(entry, dict) else {}
            self.fields[f'{day}_enabled'] = forms.BooleanField(  # noqa: F405
                label=day.title(), required=False,
                initial=bool(entry.get('enabled')),
            )
            self.fields[f'{day}_start'] = forms.CharField(  # noqa: F405
                label='From', required=False,
                initial=entry.get('start', '09:00'),
                widget=forms.TimeInput(attrs={'type': 'time'}),  # noqa: F405
            )
            self.fields[f'{day}_end'] = forms.CharField(  # noqa: F405
                label='To', required=False,
                initial=entry.get('end', '17:00'),
                widget=forms.TimeInput(attrs={'type': 'time'}),  # noqa: F405
            )

        self.fields['transfer_timezone'] = forms.ChoiceField(  # noqa: F405
            label='Hours are in this timezone',
            choices=timezone_choices(self.instance.transfer_timezone or 'UTC'),
            initial=self.instance.transfer_timezone or 'UTC',
            help_text=self.Meta.help_texts['transfer_timezone'],
        )

        if self.instance.pk:
            self.fields['keywords_text'].initial = '\n'.join(
                self.instance.transfer_keywords or []
            )
        style_widgets(self)  # noqa: F405

    @property
    def day_rows(self):
        """`[(label, enabled_field, start_field, end_field), ...]` for the template.

        Built here because a Django template cannot compose a field name from a
        loop variable, and faking it with a filter chain is how a schedule editor
        ends up writing Tuesday's hours into Monday.
        """
        return [
            (day.title(), self[f'{day}_enabled'], self[f'{day}_start'], self[f'{day}_end'])
            for day in WEEKDAY_KEYS
        ]

    def _clean_number(self, field_name, label):
        import re

        value = (self.cleaned_data.get(field_name) or '').strip()
        if value and not re.match(r'^\+[1-9]\d{7,14}$', value):
            self.add_error(
                field_name,
                f'Enter the {label} in E.164 format, e.g. +13125550100.',
            )
        return value

    def clean_transfer_phone_number(self):
        return self._clean_number('transfer_phone_number', 'primary destination')

    def clean_transfer_secondary_number(self):
        return self._clean_number('transfer_secondary_number', 'secondary destination')

    def clean_keywords_text(self):
        raw = self.cleaned_data.get('keywords_text') or ''
        keywords, seen = [], set()
        for line in raw.splitlines():
            phrase = line.strip().lower()
            if not phrase or phrase in seen:
                continue
            seen.add(phrase)
            keywords.append(phrase)
        if len(keywords) > MAX_KEYWORDS:
            raise ValidationError(  # noqa: F405
                f'Keep this to {MAX_KEYWORDS} phrases or fewer — every one is '
                'scanned against each caller utterance during a live call.'
            )
        return keywords

    def clean(self):
        cleaned = super().clean()

        if cleaned.get('transfer_enabled') and not cleaned.get('transfer_phone_number'):
            self.add_error(
                'transfer_phone_number',
                'Transfer is on but there is nowhere to send the caller. The agent '
                'would offer a handoff it cannot make.',
            )

        hours = {}
        for day in WEEKDAY_KEYS:
            enabled = cleaned.get(f'{day}_enabled')
            start = (cleaned.get(f'{day}_start') or '').strip()
            end = (cleaned.get(f'{day}_end') or '').strip()
            if enabled:
                if not start or not end:
                    self.add_error(f'{day}_start', f'{day.title()} needs a start and end time.')
                    continue
                if end <= start:
                    self.add_error(f'{day}_end', f'{day.title()} must end after it starts.')
                    continue
            hours[day] = {'enabled': bool(enabled), 'start': start, 'end': end}

        cleaned['_transfer_working_hours'] = hours
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.transfer_working_hours = self.cleaned_data.get('_transfer_working_hours') or {}
        instance.transfer_keywords = self.cleaned_data.get('keywords_text') or []
        if commit:
            instance.save()
        return instance
