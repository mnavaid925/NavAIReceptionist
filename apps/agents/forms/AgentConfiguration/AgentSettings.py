"""Agent configuration form (sub-module 2.1).

Owns `enabled`, `voice_provider`, `greeting`, `prompt_text` and `variables`.
Deliberately touches none of the Twilio fields (2.2) or transfer fields (2.3) —
three forms over one row, each blind to the others, so saving a greeting cannot
clear a credential.
"""
from apps.agents.forms._common import *  # noqa: F401,F403
from apps.agents.models import AgentSetting
from apps.agents.services import RESERVED_RUNTIME_VARIABLES, unknown_variable_names

__all__ = ['AgentConfigForm']


class AgentConfigForm(TenantLocationModelForm):  # noqa: F405
    """Edit what the agent says and how it sounds."""

    variables_text = forms.CharField(  # noqa: F405
        label='Prompt variables',
        required=False,
        widget=forms.Textarea(attrs={'rows': 4}),  # noqa: F405
        help_text='One per line as name = value. Reference them in the greeting '
                  'or prompt as {{name}}.',
    )

    class Meta:
        model = AgentSetting
        fields = ('enabled', 'voice_provider', 'greeting', 'prompt_text')
        widgets = {
            'greeting': forms.Textarea(attrs={'rows': 3}),  # noqa: F405
            'prompt_text': forms.Textarea(attrs={'rows': 12}),  # noqa: F405
        }
        help_texts = {
            'greeting': 'Spoken the instant the call connects, rendered without '
                        'the model, so the caller never waits in silence.',
            'prompt_text': "The agent's standing instructions for this location.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['variables_text'].initial = self._to_text(self.instance.variables)
        style_widgets(self)  # noqa: F405

    @staticmethod
    def _to_text(mapping):
        return '\n'.join(f'{k} = {v}' for k, v in (mapping or {}).items())

    def clean_variables_text(self):
        """Parse `name = value` lines into a dict.

        Rejects names that collide with the server-computed runtime variables: a
        tenant pinning `current_time` to a constant would make the agent state a
        false time to every caller, confidently.
        """
        raw = self.cleaned_data.get('variables_text') or ''
        parsed, seen = {}, set()

        for number, line in enumerate(raw.splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                raise ValidationError(  # noqa: F405
                    f'Line {number}: use the form  name = value'
                )
            name, value = line.split('=', 1)
            name, value = name.strip(), value.strip()

            if not name.isidentifier():
                raise ValidationError(  # noqa: F405
                    f'Line {number}: "{name}" is not a valid variable name.'
                )
            if name in RESERVED_RUNTIME_VARIABLES:
                raise ValidationError(  # noqa: F405
                    f'"{name}" is computed by the server at call time and cannot '
                    'be set here.'
                )
            if name in seen:
                raise ValidationError(f'"{name}" is defined twice.')  # noqa: F405
            seen.add(name)
            parsed[name] = value

        return parsed

    def clean(self):
        """Reject placeholders that would render as nothing on a live call."""
        cleaned = super().clean()
        variables = cleaned.get('variables_text')
        if variables is None:
            return cleaned

        for field_name, label in (('greeting', 'greeting'), ('prompt_text', 'prompt')):
            unknown = unknown_variable_names(cleaned.get(field_name) or '', variables)
            if unknown:
                names = ', '.join(f'{{{{{n}}}}}' for n in unknown)
                self.add_error(
                    field_name,
                    f'The {label} uses {names}, which is not defined. Add it above '
                    'or remove it — an undefined placeholder is spoken as a gap.',
                )

        if cleaned.get('enabled') and not (cleaned.get('greeting') or '').strip():
            self.add_error(
                'greeting',
                'A greeting is required before the agent can be enabled — without '
                'one the caller hears silence when it answers.',
            )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.variables = self.cleaned_data.get('variables_text') or {}
        if commit:
            instance.save()
        return instance
