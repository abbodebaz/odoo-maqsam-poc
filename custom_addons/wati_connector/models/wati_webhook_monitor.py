import hashlib
import json
import logging
from datetime import timedelta

from odoo import api, fields, models

from .wati_automation_guard import (
    _digits,
    _extract_external_message_id,
    _payload_broadcast_name,
    _payload_template_name,
)


_logger = logging.getLogger(__name__)

_EVENT_FAMILIES = [
    ("received", "Incoming message"),
    ("sent", "Sent"),
    ("delivered", "Delivered"),
    ("read", "Read done"),
    ("replied", "Customer response"),
    ("failed", "Failed"),
    ("contact", "Update a contact"),
    ("conversation", "Update conversation"),
    ("other", "Another event"),
]

_EVENT_LABELS = dict(_EVENT_FAMILIES)
_LIFECYCLE_FAMILIES = {"sent", "delivered", "read", "replied", "failed"}


def _clean(value):
    if value in (None, False):
        return ""
    return str(value).strip()


def _payload_dict(raw):
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _normalise_event_family(event_type, status=""):
    """Collapse WATI callback variants into one stable business event family."""
    event = _clean(event_type).casefold().replace("_v2", "")
    state = _clean(status).casefold()
    combined = f"{event} {state}"

    if any(token in combined for token in ("fail", "error", "reject", "undeliver", "expired")):
        return "failed"
    if "repl" in combined:
        return "replied"
    if "read" in combined:
        return "read"
    if "deliver" in combined:
        return "delivered"
    if "sent" in combined or state in {"accepted", "queued", "pending"}:
        return "sent"
    if "newcontact" in event or "contact" in event:
        return "contact"
    if "conversation" in event or "ticket" in event:
        return "conversation"
    if event in {"message", "messagereceived"} or "received" in event:
        return "received"
    return "other"


def _message_identity(payload, external_id=""):
    for key in ("whatsappMessageId", "localMessageId"):
        value = _clean(payload.get(key))
        if value:
            return value

    nested_identity = _clean(_extract_external_message_id(payload))
    if nested_identity:
        return nested_identity

    # Some WATI callback families use the top-level id as the message identity.
    callback_id = _clean(payload.get("id"))
    return callback_id or _clean(external_id)


def _normalise_phone(value):
    digits = _digits(value)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) >= 9:
        digits = "966" + digits[1:]
    elif len(digits) == 9 and digits.startswith("5"):
        digits = "966" + digits
    return digits


def _payload_source(payload):
    if not isinstance(payload, dict):
        return ""
    source = _clean(payload.get("source"))
    if source:
        return source
    for key in ("data", "result"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            source = _payload_source(nested)
            if source:
                return source
    return ""


def _is_odoo_originated_callback(payload):
    """Return True only when the callback carries explicit Odoo-origin evidence.

    WATI can send the same lifecycle events for messages created in WATI itself,
    mobile clients, integrations, and Odoo. Those external events are useful for
    audit but must not become alarming dashboard errors merely because Odoo does
    not own their original send record.
    """
    broadcast_name = _payload_broadcast_name(payload).casefold()
    if broadcast_name.startswith("odoo_auto_"):
        return True

    source = _payload_source(payload).casefold()
    return source.startswith("odoo_")


def _canonical_event_key(family, payload, external_id="", status=""):
    identity = _message_identity(payload, external_id=external_id)
    conversation = _clean(payload.get("conversationId"))
    wa_id = _clean(payload.get("waId"))
    stable_identity = identity or conversation or wa_id or _clean(external_id)
    if not stable_identity:
        return ""
    raw = "|".join(
        [
            _clean(family).casefold(),
            stable_identity.casefold(),
            _clean(status).casefold(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _processing_truth(
    family,
    has_message=False,
    has_conversation=False,
    has_automation=False,
    odoo_origin=False,
):
    """Return a user-facing processing state for one normalized callback.

    A lifecycle callback is an actionable integration problem only when there is
    evidence that Odoo originated the send and Odoo still cannot correlate it.
    Lifecycle traffic belonging to activity created elsewhere in WATI remains a
    useful audit record, but it must not inflate the dashboard alert counter.
    """
    if family in _LIFECYCLE_FAMILIES:
        if has_message or has_automation:
            return (
                "processed",
                "The message status was linked to its Odoo record and processed successfully.",
            )
        if odoo_origin:
            return (
                "needs_attention",
                "This callback belongs to an Odoo-originated send, but its local message or automation run could not be found.",
            )
        return (
            "audit_only",
            "This WATI lifecycle event is not proven to originate from Odoo, so it is kept for audit only.",
        )

    if has_message or has_conversation or has_automation:
        return (
            "processed",
            "The event is linked to Odoo data and was processed successfully.",
        )
    return (
        "audit_only",
        "The event is saved as a technical audit record and does not require additional action.",
    )


class WatiWebhookEventMonitor(models.Model):
    _inherit = "wati.webhook.event"
    _rec_name = "event_label"

    event_family = fields.Selection(
        _EVENT_FAMILIES,
        string="Unified family",
        compute="_compute_monitor_labels",
        store=True,
        index=True,
    )
    event_label = fields.Char(
        string="Event",
        compute="_compute_monitor_labels",
        store=True,
    )
    source_version = fields.Selection(
        [("legacy", "Legacy"), ("v2", "v2")],
        string="Copy Callback",
        compute="_compute_monitor_labels",
        store=True,
    )
    event_key = fields.Char(string="Event fingerprint", readonly=True, copy=False, index=True)
    is_duplicate_variant = fields.Boolean(
        string="Callback Duplicate",
        readonly=True,
        copy=False,
        index=True,
    )
    duplicate_of_id = fields.Many2one(
        "wati.webhook.event",
        string="Copy of",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    processing_state = fields.Selection(
        [
            ("processed", "Processed"),
            ("needs_attention", "Needs attention"),
            ("audit_only", "Technical record"),
            ("duplicate", "Callback Duplicate"),
        ],
        string="Processing status",
        readonly=True,
        copy=False,
        index=True,
    )
    processing_note = fields.Char(string="Treatment result", readonly=True, copy=False)
    linked_message_id = fields.Many2one(
        "wati.message",
        string="Associated message",
        readonly=True,
        copy=False,
        ondelete="set null",
        index=True,
    )
    linked_conversation_id = fields.Many2one(
        "wati.conversation",
        string="Associated conversation",
        readonly=True,
        copy=False,
        ondelete="set null",
        index=True,
    )
    linked_automation_log_id = fields.Many2one(
        "wati.automation.log",
        string="Run associated automation",
        readonly=True,
        copy=False,
        ondelete="set null",
        index=True,
    )

    @api.depends("event_type", "status")
    def _compute_monitor_labels(self):
        for event in self:
            family = _normalise_event_family(event.event_type, event.status)
            event.event_family = family
            event.event_label = _EVENT_LABELS.get(family, "Another event")
            event.source_version = (
                "v2" if _clean(event.event_type).casefold().endswith("_v2") else "legacy"
            )

    def _monitor_payload(self):
        self.ensure_one()
        return _payload_dict(self.payload)

    def _monitor_find_relations(self, payload):
        """Find the same local records used by message and automation lifecycles.

        Exact message IDs remain the strongest match. Automation callbacks also
        support WATI broadcast names and the same conservative recent-recipient
        fallback used by the delivery lifecycle so the monitor does not report a
        false alert merely because a provider callback omitted an ID.
        """
        self.ensure_one()
        message = self.env["wati.message"].sudo().browse()
        if hasattr(self, "_wati_find_existing_message"):
            message = self._wati_find_existing_message(payload)

        identity = _message_identity(payload, external_id=self.external_id)
        if not message and identity:
            Message = self.env["wati.message"].sudo()
            message = Message.search(
                [
                    "|",
                    "|",
                    ("whatsapp_message_id", "=", identity),
                    ("local_message_id", "=", identity),
                    ("name", "=", identity),
                ],
                order="id desc",
                limit=1,
            )

        conversation = message.conversation_id if message else self.env["wati.conversation"].browse()
        Conversation = self.env["wati.conversation"].sudo().with_context(active_test=False)
        conversation_uid = _clean(payload.get("conversationId")) or _clean(self.conversation_uid)
        wa_id = _clean(payload.get("waId")) or _clean(self.wa_id)
        if not conversation and conversation_uid:
            conversation = Conversation.search(
                [("conversation_uid", "=", conversation_uid)],
                order="id desc",
                limit=1,
            )
        if not conversation and wa_id:
            conversation = Conversation.search(
                [("wa_id", "=", wa_id)], order="id desc", limit=1
            )

        Log = self.env["wati.automation.log"].sudo()
        automation_log = Log.browse()
        if identity:
            automation_log = Log.search(
                [("external_message_id", "=", identity)],
                order="create_date desc, id desc",
                limit=1,
            )

        broadcast_name = _payload_broadcast_name(payload)
        if not automation_log and broadcast_name:
            automation_log = Log.search(
                [("broadcast_name", "=", broadcast_name)],
                order="create_date desc, id desc",
                limit=1,
            )

        if not automation_log and identity:
            automation_log = Log.search(
                [("response_excerpt", "ilike", identity)],
                order="create_date desc, id desc",
                limit=1,
            )

        if not automation_log:
            phone = _normalise_phone(
                payload.get("waId")
                or payload.get("whatsappNumber")
                or payload.get("phoneNumber")
                or ""
            )
            if phone:
                anchor = self.received_at or fields.Datetime.now()
                cutoff = anchor - timedelta(minutes=60)
                upper_bound = anchor + timedelta(minutes=5)
                domain = [
                    ("phone", "=", phone),
                    ("status", "in", ("accepted", "sent", "delivered", "read", "failed")),
                    ("create_date", ">=", cutoff),
                    ("create_date", "<=", upper_bound),
                ]
                template_name = _payload_template_name(payload)
                if template_name:
                    domain.append(("template_name", "=", template_name))
                candidates = Log.search(domain, order="create_date desc, id desc", limit=2)
                if len(candidates) == 1:
                    automation_log = candidates

        return message, conversation, automation_log

    def _monitor_enrich(self, payload=None, seen=None):
        """Attach semantic monitoring metadata without mutating the raw audit event."""
        for event in self.sudo():
            current_payload = (
                payload
                if len(self) == 1 and payload is not None
                else event._monitor_payload()
            )
            family = _normalise_event_family(event.event_type, event.status)
            key = _canonical_event_key(
                family,
                current_payload,
                external_id=event.external_id,
                status=event.status,
            )

            duplicate = self.env["wati.webhook.event"].browse()
            if key:
                if seen is not None and key in seen:
                    duplicate = self.browse(seen[key])
                elif seen is None:
                    duplicate = self.sudo().search(
                        [
                            ("event_key", "=", key),
                            ("id", "!=", event.id),
                            ("is_duplicate_variant", "=", False),
                        ],
                        order="received_at asc, id asc",
                        limit=1,
                    )

            message, conversation, automation_log = event._monitor_find_relations(
                current_payload
            )

            if duplicate:
                processing_state = "duplicate"
                note = "Additional callback for the same business event; kept for audit only."
            else:
                processing_state, note = _processing_truth(
                    family,
                    has_message=bool(message),
                    has_conversation=bool(conversation),
                    has_automation=bool(automation_log),
                    odoo_origin=_is_odoo_originated_callback(current_payload),
                )

            event.with_context(wati_webhook_monitor_internal=True).write(
                {
                    "event_key": key or False,
                    "is_duplicate_variant": bool(duplicate),
                    "duplicate_of_id": duplicate.id or False,
                    "processing_state": processing_state,
                    "processing_note": note,
                    "linked_message_id": message.id or False,
                    "linked_conversation_id": conversation.id or False,
                    "linked_automation_log_id": automation_log.id or False,
                }
            )
            if seen is not None and key and not duplicate:
                seen[key] = event.id
        return True

    @api.model
    def ingest(self, payload):
        result = super().ingest(payload)
        if not isinstance(payload, dict):
            return result

        event_type = _clean(payload.get("eventType") or payload.get("type") or "event")
        external_id = ""
        for key in ("id", "localMessageId", "whatsappMessageId"):
            external_id = _clean(payload.get(key))
            if external_id:
                break
        status = _clean(payload.get("statusString") or payload.get("status"))

        domain = [("event_type", "=", event_type), ("status", "=", status)]
        if external_id:
            domain.append(("external_id", "=", external_id))
        event = self.sudo().search(domain, order="received_at desc, id desc", limit=1)
        if event:
            event._monitor_enrich(payload=payload)
        return result

    @api.model
    def _repair_webhook_monitor(self):
        """Fallback repair; production backfill override is loaded after this model."""
        events = self.sudo().search([], order="received_at asc, id asc")
        seen = {}
        processed = duplicates = attention = 0
        for event in events:
            event._monitor_enrich(seen=seen)
            processed += 1
            duplicates += int(event.is_duplicate_variant)
            attention += int(event.processing_state == "needs_attention")
        _logger.warning(
            "WATI_WEBHOOK_MONITOR_REPAIR processed=%s duplicates=%s attention=%s mode=fallback",
            processed,
            duplicates,
            attention,
        )
        return True
