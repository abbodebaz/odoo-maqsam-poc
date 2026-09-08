import logging

from psycopg2.extras import execute_values

from odoo import api, models

from .wati_webhook_monitor import (
    _canonical_event_key,
    _clean,
    _message_identity,
    _normalise_event_family,
    _payload_dict,
    _processing_truth,
)


_logger = logging.getLogger(__name__)


class WatiWebhookEventMonitorFastBackfill(models.Model):
    _inherit = "wati.webhook.event"

    @api.model
    def _repair_webhook_monitor(self):
        """Backfill monitor metadata with bounded reads and set-based writes.

        Runtime callbacks are enriched one at a time for correctness. Historical
        upgrades can contain thousands of audit rows, so this path preloads exact
        identifiers once, classifies events in memory, then sends set-based UPDATE
        statements in chunks. The number of database round trips stays bounded as
        history grows.
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

        automation_logs = self.env["wati.automation.log"].sudo().search(
            [("external_message_id", "!=", False)]
        )
        automation_by_identity = {}
        for log in automation_logs:
            identity = _clean(log.external_message_id)
            if identity and identity not in automation_by_identity:
                automation_by_identity[identity] = log.id

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

            if duplicate_of_id:
                processing_state = "duplicate"
                processing_note = (
                    "نسخة Callback إضافية لنفس الحدث؛ تم الاحتفاظ بها للتدقيق فقط."
                )
                duplicate_count += 1
            else:
                processing_state, processing_note = _processing_truth(
                    family,
                    has_message=bool(linked_message_id),
                    has_conversation=bool(linked_conversation_id),
                    has_automation=bool(linked_automation_log_id),
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

        if rows:
            execute_values(
                self.env.cr._obj,
                """
                UPDATE wati_webhook_event AS event
                   SET event_key = values.event_key,
                       is_duplicate_variant = values.is_duplicate_variant::boolean,
                       duplicate_of_id = values.duplicate_of_id::integer,
                       processing_state = values.processing_state,
                       processing_note = values.processing_note,
                       linked_message_id = values.linked_message_id::integer,
                       linked_conversation_id = values.linked_conversation_id::integer,
                       linked_automation_log_id = values.linked_automation_log_id::integer
                  FROM (VALUES %s) AS values(
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
                rows,
                page_size=1000,
            )
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
