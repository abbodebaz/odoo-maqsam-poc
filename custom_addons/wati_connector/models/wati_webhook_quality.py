import hashlib
import json

from odoo import api, fields, models


_STATUS_EVENT_MARKERS = (
    "sentmessage",
    "messagestatus",
    "message_status",
    "delivered",
    "delivery",
    "read",
)


def _clean(value):
    if value in (None, False):
        return ""
    return str(value).strip()


def _event_external_id(payload):
    for key in ("id", "localMessageId", "whatsappMessageId"):
        value = _clean(payload.get(key))
        if value:
            return value
    return ""


def _message_identity(payload):
    for key in ("whatsappMessageId", "localMessageId", "id"):
        value = _clean(payload.get(key))
        if value:
            return value
    return ""


def _advisory_key(namespace, value):
    """Return a stable signed bigint suitable for PostgreSQL advisory locks."""
    digest = hashlib.blake2b(
        f"wati:{namespace}:{value}".encode("utf-8"), digest_size=8
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


class WatiConversation(models.Model):
    _inherit = "wati.conversation"

    active = fields.Boolean(
        string="Active",
        compute="_compute_active",
        store=True,
        index=True,
    )

    @api.depends("wa_id", "partner_id")
    def _compute_active(self):
        """Archive transport-only placeholders that cannot represent a customer chat.

        A usable conversation must either know its WhatsApp recipient or already be
        linked to an Odoo contact. This also keeps old status-only placeholder rows
        out of every normal Odoo search without deleting their audit trail.
        """
        for conversation in self:
            conversation.active = bool(
                _clean(conversation.wa_id) or conversation.partner_id
            )


class WatiWebhookEvent(models.Model):
    _inherit = "wati.webhook.event"

    @api.model
    def _wati_lock_ingest_identity(self, payload):
        """Serialize duplicate/concurrent callbacks before search-then-create logic.

        WATI can deliver the same callback through multiple webhook variants at nearly
        the same instant. Without serialization, two transactions can both see no
        existing message/conversation and create duplicates. Transaction-scoped
        advisory locks keep ingestion idempotent without introducing permanent rows
        or external lock infrastructure.
        """
        if not isinstance(payload, dict):
            return

        lock_keys = set()
        message_identity = _message_identity(payload)
        conversation_uid = _clean(payload.get("conversationId"))
        wa_id = _clean(payload.get("waId"))

        if message_identity:
            lock_keys.add(_advisory_key("message", message_identity))
        if conversation_uid:
            lock_keys.add(_advisory_key("conversation", conversation_uid))
        if wa_id:
            lock_keys.add(_advisory_key("wa", wa_id))

        # Always acquire in deterministic order so two callbacks cannot deadlock
        # while sharing more than one identity.
        for lock_key in sorted(lock_keys):
            self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])

    @api.model
    def _wati_find_existing_message(self, payload):
        message_model = self.env["wati.message"].sudo()
        whatsapp_message_id = _clean(payload.get("whatsappMessageId"))
        local_message_id = _clean(payload.get("localMessageId"))
        message_identity = _message_identity(payload)

        message = message_model.browse()
        if whatsapp_message_id:
            message = message_model.search(
                [("whatsapp_message_id", "=", whatsapp_message_id)],
                order="id desc",
                limit=1,
            )
        if not message and local_message_id:
            message = message_model.search(
                [("local_message_id", "=", local_message_id)],
                order="id desc",
                limit=1,
            )
        if not message and message_identity:
            message = message_model.search(
                [("name", "=", message_identity)],
                order="id desc",
                limit=1,
            )
        return message

    @api.model
    def _wati_is_orphan_status_callback(self, payload):
        """Detect WATI delivery/read callbacks that contain no customer identity.

        WATI can emit status callbacks for template messages sent outside this Odoo
        connector. Those callbacks may contain conversationId/ticketId and a WhatsApp
        message id, but no waId, sender name or message body. They are useful audit
        events, but they are not enough information to create a customer conversation.
        """
        if not isinstance(payload, dict):
            return False
        if self._wati_find_existing_message(payload):
            return False
        if _clean(payload.get("waId")) or _clean(payload.get("senderName")):
            return False
        if payload.get("text") is not None:
            return False
        if not _clean(payload.get("statusString") or payload.get("status")):
            return False
        if not _clean(payload.get("whatsappMessageId")):
            return False

        event_type = _clean(payload.get("eventType") or payload.get("type")).casefold()
        return any(marker in event_type for marker in _STATUS_EVENT_MARKERS)

    @api.model
    def _wati_store_audit_event_only(self, payload):
        event_type = _clean(payload.get("eventType") or payload.get("type") or "event")
        external_id = _event_external_id(payload)
        status = _clean(payload.get("statusString") or payload.get("status"))
        wa_id = _clean(payload.get("waId"))
        conversation_uid = _clean(payload.get("conversationId"))

        domain = [
            ("external_id", "=", external_id),
            ("event_type", "=", event_type),
            ("status", "=", status),
        ]
        if not external_id or not self.sudo().search_count(domain, limit=1):
            self.sudo().create(
                {
                    "event_type": event_type,
                    "external_id": external_id,
                    "wa_id": wa_id,
                    "conversation_uid": conversation_uid,
                    "status": status,
                    "payload": json.dumps(payload, ensure_ascii=False, default=str),
                }
            )
        return True

    @api.model
    def ingest(self, payload):
        self._wati_lock_ingest_identity(payload)
        if self._wati_is_orphan_status_callback(payload):
            return self._wati_store_audit_event_only(payload)
        return super().ingest(payload)
