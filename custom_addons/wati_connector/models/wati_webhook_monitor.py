import hashlib
import json
import logging

from odoo import api, fields, models


_logger = logging.getLogger(__name__)

_EVENT_FAMILIES = [
    ("received", "رسالة واردة"),
    ("sent", "تم الإرسال"),
    ("delivered", "تم التسليم"),
    ("read", "تمت القراءة"),
    ("replied", "رد العميل"),
    ("failed", "فشل"),
    ("contact", "تحديث جهة اتصال"),
    ("conversation", "تحديث محادثة"),
    ("other", "حدث آخر"),
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
    for key in ("whatsappMessageId", "localMessageId", "id"):
        value = _clean(payload.get(key))
        if value:
            return value
    return _clean(external_id)


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


def _processing_truth(family, has_message=False, has_conversation=False, has_automation=False):
    """Return a truthful monitor state for one normalized callback.

    Lifecycle callbacks such as Delivered/Read are only considered processed when
    Odoo can tie them to the concrete message (or to the automation run that sent
    it). A conversation match alone is useful context but does not prove that the
    message lifecycle was applied correctly.
    """
    if family in _LIFECYCLE_FAMILIES:
        if has_message or has_automation:
            return (
                "processed",
                "تم ربط حالة الرسالة ببيانات Odoo ومعالجتها بنجاح.",
            )
        return (
            "needs_attention",
            "وصلت حالة من WATI لكن لم يتم العثور على الرسالة المرتبطة داخل Odoo.",
        )
    if has_message or has_conversation or has_automation:
        return (
            "processed",
            "تم ربط الحدث ببيانات Odoo ومعالجته بنجاح.",
        )
    return (
        "audit_only",
        "تم حفظ الحدث كسجل تدقيق تقني، ولا يحتاج إجراءً إضافيًا.",
    )


class WatiWebhookEventMonitor(models.Model):
    _inherit = "wati.webhook.event"
    _rec_name = "event_label"

    event_family = fields.Selection(
        _EVENT_FAMILIES,
        string="العائلة الموحدة",
        compute="_compute_monitor_labels",
        store=True,
        index=True,
    )
    event_label = fields.Char(
        string="الحدث",
        compute="_compute_monitor_labels",
        store=True,
    )
    source_version = fields.Selection(
        [("legacy", "Legacy"), ("v2", "v2")],
        string="نسخة Callback",
        compute="_compute_monitor_labels",
        store=True,
    )
    event_key = fields.Char(string="بصمة الحدث", readonly=True, copy=False, index=True)
    is_duplicate_variant = fields.Boolean(
        string="Callback مكرر",
        readonly=True,
        copy=False,
        index=True,
    )
    duplicate_of_id = fields.Many2one(
        "wati.webhook.event",
        string="نسخة من",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    processing_state = fields.Selection(
        [
            ("processed", "تمت المعالجة"),
            ("needs_attention", "يحتاج انتباه"),
            ("audit_only", "سجل تقني"),
            ("duplicate", "Callback مكرر"),
        ],
        string="حالة المعالجة",
        readonly=True,
        copy=False,
        index=True,
    )
    processing_note = fields.Char(string="نتيجة المعالجة", readonly=True, copy=False)
    linked_message_id = fields.Many2one(
        "wati.message",
        string="الرسالة المرتبطة",
        readonly=True,
        copy=False,
        ondelete="set null",
        index=True,
    )
    linked_conversation_id = fields.Many2one(
        "wati.conversation",
        string="المحادثة المرتبطة",
        readonly=True,
        copy=False,
        ondelete="set null",
        index=True,
    )
    linked_automation_log_id = fields.Many2one(
        "wati.automation.log",
        string="تشغيل الأتمتة المرتبط",
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
            event.event_label = _EVENT_LABELS.get(family, "حدث آخر")
            event.source_version = (
                "v2" if _clean(event.event_type).casefold().endswith("_v2") else "legacy"
            )

    def _monitor_payload(self):
        self.ensure_one()
        return _payload_dict(self.payload)

    def _monitor_find_relations(self, payload):
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

        automation_log = self.env["wati.automation.log"].sudo().browse()
        if identity:
            automation_log = self.env["wati.automation.log"].sudo().search(
                [("external_message_id", "=", identity)],
                order="id desc",
                limit=1,
            )
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
                note = (
                    "نسخة Callback إضافية لنفس الحدث؛ تم الاحتفاظ بها للتدقيق فقط."
                )
            else:
                processing_state, note = _processing_truth(
                    family,
                    has_message=bool(message),
                    has_conversation=bool(conversation),
                    has_automation=bool(automation_log),
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
