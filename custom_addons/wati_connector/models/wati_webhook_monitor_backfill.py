import logging

from odoo import api, models

from .wati_automation_guard import _payload_broadcast_name
from .wati_webhook_monitor import (
    _canonical_event_key,
    _clean,
    _is_odoo_originated_callback,
    _message_identity,
    _normalise_event_family,
    _payload_dict,
    _processing_truth,
)


_logger = logging.getLogger(__name__)
_UPDATE_CHUNK_SIZE = 500


class WatiWebhookEventMonitorFastBackfill(models.Model):
    _inherit = "wati.webhook.event"

    @api.model
    def _repair_webhook_monitor(self):
        """Backfill monitor metadata with bounded reads and set-based writes.

        Runtime callbacks use the richer relation matcher. Historical upgrades can
        contain thousands of audit rows, so this path preloads exact message and
        automation identifiers plus Odoo broadcast names, classifies events in
        memory, then updates rows through bounded VALUES-backed SQL.
        """
        events = self.sudo().search([], order="received_at asc, id asc")

        messages = self.env["wati.message"].sudo().search([])
        message_by_identity = {}
        message_conversation = {}
        for message in messages:
            for value in (
                message.whatsapp_message_id,
                message.local_message_id,
                message.name,
            ):
                key = _clean(value)
                if key and key not in message_by_identity:
                    message_by_identity[key] = message.id
            if message.conversation_id:
                message_conversation[message.id] = message.conversation_id.id

        conversations = (
            self.env["wati.conversation"]
            .sudo()
            .with_context(active_test=False)
            .search([])
        )
        conversation_by_uid = {}
        conversation_by_wa = {}
        for conversation in conversations:
            uid = _clean(conversation.conversation_uid)
            wa_id = _clean(conversation.wa_id)
            if uid and uid not in conversation_by_uid:
                conversation_by_uid[uid] = conversation.id
            if wa_id and wa_id not in conversation_by_wa:
                conversation_by_wa[wa_id] = conversation.id

        automation_logs = self.env["wati.automation.log"].sudo().search([])
        automation_by_identity = {}
        automation_by_broadcast = {}
        for log in automation_logs:
            identity = _clean(log.external_message_id)
            if identity and identity not in automation_by_identity:
                automation_by_identity[identity] = log.id
            broadcast_name = _clean(log.broadcast_name)
            if broadcast_name and broadcast_name not in automation_by_broadcast:
                automation_by_broadcast[broadcast_name] = log.id

        seen = {}
        rows = []
        duplicate_count = 0
        attention_count = 0

        for event in events:
            payload = _payload_dict(event.payload)
            family = _normalise_event_family(event.event_type, event.status)
            event_key = _canonical_event_key(
                family,
                payload,
                external_id=event.external_id,
                status=event.status,
            )

            duplicate_of_id = seen.get(event_key) if event_key else False
            if event_key and not duplicate_of_id:
                seen[event_key] = event.id

            identity = _message_identity(payload, external_id=event.external_id)
            linked_message_id = message_by_identity.get(identity) if identity else False
            linked_conversation_id = (
                message_conversation.get(linked_message_id) if linked_message_id else False
            )
            if not linked_conversation_id:
                conversation_uid = _clean(payload.get("conversationId")) or _clean(
                    event.conversation_uid
                )
                wa_id = _clean(payload.get("waId")) or _clean(event.wa_id)
                linked_conversation_id = (
                    conversation_by_uid.get(conversation_uid)
                    if conversation_uid
                    else False
                )
                if not linked_conversation_id and wa_id:
                    linked_conversation_id = conversation_by_wa.get(wa_id)

            linked_automation_log_id = (
                automation_by_identity.get(identity) if identity else False
            )
            if not linked_automation_log_id:
                broadcast_name = _payload_broadcast_name(payload)
                if broadcast_name:
                    linked_automation_log_id = automation_by_broadcast.get(broadcast_name)

            if duplicate_of_id:
                processing_state = "duplicate"
                processing_note = (
                    "Additional callback for the same business event; kept for audit only."
                )
                duplicate_count += 1
            else:
                processing_state, processing_note = _processing_truth(
                    family,
                    has_message=bool(linked_message_id),
                    has_conversation=bool(linked_conversation_id),
                    has_automation=bool(linked_automation_log_id),
                    odoo_origin=_is_odoo_originated_callback(payload),
                )
                attention_count += int(processing_state == "needs_attention")

            rows.append(
                (
                    event_key or None,
                    bool(duplicate_of_id),
                    duplicate_of_id or None,
                    processing_state,
                    processing_note,
                    linked_message_id or None,
                    linked_conversation_id or None,
                    linked_automation_log_id or None,
                    event.id,
                )
            )

        for offset in range(0, len(rows), _UPDATE_CHUNK_SIZE):
            chunk = rows[offset : offset + _UPDATE_CHUNK_SIZE]
            placeholders = ",".join(
                ["(%s,%s,%s,%s,%s,%s,%s,%s,%s)"] * len(chunk)
            )
            params = [value for row in chunk for value in row]
            self.env.cr.execute(
                f"""
                UPDATE wati_webhook_event AS event
                   SET event_key = values.event_key,
                       is_duplicate_variant = values.is_duplicate_variant::boolean,
                       duplicate_of_id = values.duplicate_of_id::integer,
                       processing_state = values.processing_state,
                       processing_note = values.processing_note,
                       linked_message_id = values.linked_message_id::integer,
                       linked_conversation_id = values.linked_conversation_id::integer,
                       linked_automation_log_id = values.linked_automation_log_id::integer
                  FROM (VALUES {placeholders}) AS values(
                       event_key,
                       is_duplicate_variant,
                       duplicate_of_id,
                       processing_state,
                       processing_note,
                       linked_message_id,
                       linked_conversation_id,
                       linked_automation_log_id,
                       event_id
                  )
                 WHERE event.id = values.event_id::integer
                """,
                params,
            )

        if rows:
            events.invalidate_recordset(
                [
                    "event_key",
                    "is_duplicate_variant",
                    "duplicate_of_id",
                    "processing_state",
                    "processing_note",
                    "linked_message_id",
                    "linked_conversation_id",
                    "linked_automation_log_id",
                ]
            )

        _logger.warning(
            "WATI_WEBHOOK_MONITOR_REPAIR processed=%s duplicates=%s attention=%s mode=set_based",
            len(events),
            duplicate_count,
            attention_count,
        )
        return True
