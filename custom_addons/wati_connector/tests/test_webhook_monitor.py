from odoo.tests.common import TransactionCase


class TestWatiWebhookMonitor(TransactionCase):

    def setUp(self):
        super().setUp()
        self.events = self.env["wati.webhook.event"]
        self.conversation = self.env["wati.conversation"].create(
            {"name": "Webhook customer", "wa_id": "966500001234"}
        )
        self.message = self.env["wati.message"].create(
            {
                "name": "wamid.monitor-1",
                "whatsapp_message_id": "wamid.monitor-1",
                "conversation_id": self.conversation.id,
                "wa_id": self.conversation.wa_id,
                "direction": "outbound",
                "message_type": "template",
                "status": "Sent",
            }
        )

    def _payload(self, event_type, status, callback_id="callback-monitor-1"):
        return {
            "eventType": event_type,
            "statusString": status,
            "id": callback_id,
            "whatsappMessageId": "wamid.monitor-1",
            "conversationId": "conversation-monitor-1",
            "waId": self.conversation.wa_id,
            "text": None,
            "type": "template",
        }

    def test_legacy_and_v2_delivery_are_one_business_event(self):
        self.events.ingest(self._payload("sentMessageDELIVERED", "Delivered"))
        self.events.ingest(self._payload("sentMessageDELIVERED_v2", "Delivered"))

        rows = self.events.search(
            [("external_id", "=", "callback-monitor-1")], order="id asc"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows.mapped("event_family")), {"delivered"})
        self.assertEqual(len(rows.filtered(lambda row: not row.is_duplicate_variant)), 1)
        duplicate = rows.filtered("is_duplicate_variant")
        self.assertEqual(len(duplicate), 1)
        self.assertEqual(duplicate.processing_state, "duplicate")
        self.assertTrue(duplicate.duplicate_of_id)

    def test_known_message_is_marked_processed(self):
        self.events.ingest(self._payload("sentMessageREAD_v2", "Read", "callback-read-1"))
        row = self.events.search([("external_id", "=", "callback-read-1")], limit=1)

        self.assertEqual(row.event_family, "read")
        self.assertEqual(row.processing_state, "processed")
        self.assertEqual(row.linked_message_id, self.message)
        self.assertEqual(row.linked_conversation_id, self.conversation)

    def test_lifecycle_event_without_message_needs_attention(self):
        self.events.ingest(
            {
                "eventType": "sentMessageDELIVERED_v2",
                "statusString": "Delivered",
                "id": "orphan-monitor-1",
                "whatsappMessageId": "wamid.missing-monitor-1",
                "conversationId": "missing-conversation-monitor-1",
                "text": None,
                "type": "template",
            }
        )
        row = self.events.search([("external_id", "=", "orphan-monitor-1")], limit=1)
        self.assertEqual(row.event_family, "delivered")
        self.assertEqual(row.processing_state, "needs_attention")
        self.assertFalse(row.linked_message_id)

    def test_different_lifecycle_states_are_not_duplicates(self):
        self.events.ingest(self._payload("templateMessageSent_v2", "SENT", "callback-sent-1"))
        self.events.ingest(self._payload("sentMessageDELIVERED_v2", "Delivered", "callback-delivered-1"))
        self.events.ingest(self._payload("sentMessageREAD_v2", "Read", "callback-read-2"))

        rows = self.events.search(
            [("external_id", "in", ["callback-sent-1", "callback-delivered-1", "callback-read-2"])]
        )
        self.assertEqual(len(rows), 3)
        self.assertFalse(any(rows.mapped("is_duplicate_variant")))
        self.assertEqual(set(rows.mapped("event_family")), {"sent", "delivered", "read"})

    def test_repair_marks_historical_variant_duplicate(self):
        first = self.events.create(
            {
                "event_type": "sentMessageDELIVERED",
                "external_id": "historical-monitor-1",
                "wa_id": self.conversation.wa_id,
                "conversation_uid": "conversation-monitor-1",
                "status": "Delivered",
                "payload": '{"id":"historical-monitor-1","whatsappMessageId":"wamid.monitor-1","statusString":"Delivered","eventType":"sentMessageDELIVERED"}',
            }
        )
        second = self.events.create(
            {
                "event_type": "sentMessageDELIVERED_v2",
                "external_id": "historical-monitor-1",
                "wa_id": self.conversation.wa_id,
                "conversation_uid": "conversation-monitor-1",
                "status": "Delivered",
                "payload": '{"id":"historical-monitor-1","whatsappMessageId":"wamid.monitor-1","statusString":"Delivered","eventType":"sentMessageDELIVERED_v2"}',
            }
        )

        self.events._repair_webhook_monitor()
        first.invalidate_recordset()
        second.invalidate_recordset()
        self.assertFalse(first.is_duplicate_variant)
        self.assertTrue(second.is_duplicate_variant)
        self.assertEqual(second.duplicate_of_id, first)
