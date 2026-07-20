from django.contrib import admin

from apps.calls.models import CallSession


@admin.register(CallSession)
class CallSessionAdmin(admin.ModelAdmin):
    list_display = ('provider_call_sid', 'status', 'tenant', 'location',
                    'contact', 'from_number', 'to_number', 'mode', 'started_at',
                    'ended_at')
    list_filter = ('status', 'mode', 'tenant', 'location')
    search_fields = ('provider_call_sid', 'from_number', 'to_number',
                     'contact__first_name', 'contact__last_name')
    list_select_related = ('tenant', 'location', 'contact')
    date_hierarchy = 'started_at'
    # Newest call first, which is `-started_at` — but `started_at` is nullable
    # (a session row can exist before the media stream has produced a frame), and
    # a column of NULLs sorts as one undifferentiated block. `-created_at` breaks
    # that tie so the not-yet-started rows still arrive in a stable, meaningful
    # order instead of whatever the backend happens to return.
    ordering = ('-started_at', '-created_at')

    # A call log is a record of what happened, so the admin is a break-glass tool
    # here and not a second edit surface. Everything the call runtime observed or
    # was told by the provider is readonly:
    #
    # * `provider_call_sid` is Twilio's identifier AND the idempotency key for
    #   webhook redelivery. Editing it does not rename a call — it detaches this
    #   row from the real one and lets the next retry mint a duplicate session.
    # * `from_number` / `to_number` came off the carrier. The dialed number is
    #   also what resolves tenant and location for an inbound call, so a typed-in
    #   value is a forged provenance trail, not a correction.
    # * `transcript`, `logs`, `analysis`, `usage`, `transfer`, `waveform_peaks`
    #   and `metadata` are the Invariant 2 columns — the whole evidentiary body of
    #   the call. They are also the PII surface and, in `metadata`'s case, carry
    #   the recording consent basis and retention window. A staff user quietly
    #   rewriting a transcript or a consent basis in a raw JSON textarea is the
    #   precise failure this list exists to prevent.
    # * `recording_blob` is a private storage path; retyping it would point the
    #   signed-URL view at another call's audio.
    # * `started_at` / `ended_at` are the clock. `duration_display` derives from
    #   them, so an editable pair is an editable duration by the back door.
    #
    # What stays editable is deliberately only the scoping and workflow fields —
    # `tenant`, `location`, `contact`, `channel`, `mode`, `status`. Attaching a
    # call to the right contact after the fact, or correcting a status stuck at
    # `in_progress` by a crashed consumer, are genuine back-office needs, and none
    # of them rewrite what was said.
    readonly_fields = ('provider_call_sid', 'from_number', 'to_number',
                       'transcript', 'logs', 'analysis', 'usage',
                       'recording_blob', 'transfer', 'waveform_peaks',
                       'metadata', 'started_at', 'ended_at',
                       'created_at', 'updated_at')

    def has_add_permission(self, request, obj=None):
        """No hand-made call logs.

        A `CallSession` is written by one process — the media-stream consumer
        Module 3 owns — and every field that makes it meaningful is readonly
        above. So the add form would produce a row with a made-up Twilio SID, an
        empty transcript and no audio behind it: a call that never happened,
        indistinguishable in the list from one that did. There is no legitimate
        reason to create one by hand, and the seeder goes through the ORM rather
        than this form.

        Deletion is deliberately NOT blocked the same way. It is the break-glass
        path for a retention purge or an erasure request, both of which are real
        obligations, and it fails honestly: a deleted call is visibly absent,
        whereas a hand-edited one still looks like evidence.
        """
        return False
