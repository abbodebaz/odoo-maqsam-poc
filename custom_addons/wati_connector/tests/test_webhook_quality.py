from odoo.tests.common import TransactionCase


class TestWatiWebhookQuality(TransactionCase):

    def test_unknown_status_callback_is_audit_only(self):
        payload = {
            "eventType": "sentMessageREAD_v2",
            "statusString": "Read",
            "id": "status-event-1",
            "whatsappMessageId": "wamid.status-only-1",
            "conversationId": "conversation-status-only-1",
            "ticketId": "ticket-status-only-1",
            "text": None,
            "type": "template",
        }

        self.env["wati.webhook.event"].ingest(payload)

        self.assertTrue(
            self.env["wati.webhook.event"].search_count(
                [("external_id", "=", "status-event-1")]
            )
        )
        self.assertFalse(
            self.env["wati.message"].search_count(
                [("whatsapp_message_id", "=", "wamid.status-only-1")]
            )
        )
        self.assertFalse(
            self.env["wati.conversation"].with_context(active_test=False).search_count(
                [("conversation_uid", "=", "conversation-status-only-1")]
            )
        )

    def test_status_callback_still_updates_known_message(self):
        conversation = self.env["wati.conversation"].create(
            {"name": "Known customer", "wa_id": "966500000001"}
        )
        message = self.env["wati.message"].create(
            {
                "name": "wamid.known-1",
                "whatsapp_message_id": "wamid.known-1",
                "conversation_id": conversation.id,
                "wa_id": conversation.wa_id,
                "direction": "outbound",
                "message_type": "template",
                "status": "Sent",
            }
        )

        self.env["wati.webhook.event"].ingest(
            {
                "eventType": "sentMessageREAD",
                "statusString": "Read",
                "id": "status-event-known-1",
                "whatsappMessageId": "wamid.known-1",
                "conversationId": "known-conversation-1",
                "text": None,
                "type": "template",
            }
        )

        message.invalidate_recordset(["status"])
        self.assertEqual(message.status, "Read")

    def test_placeholder_conversation_is_archived_from_normal_search(self):
        placeholder = self.env["wati.conversation"].with_context(active_test=False).create(
            {
                "name": "رقم غير متوفر",
                "conversation_uid": "placeholder-conversation-1",
                "wa_id": False,
            }
        )

        placeholder.invalidate_recordset(["active"])
        self.assertFalse(placeholder.active)
        self.assertFalse(
            self.env["wati.conversation"].search_count([("id", "=", placeholder.id)])
        )
        self.assertTrue(
            self.env["wati.conversation"].with_context(active_test=False).search_count(
                [("id", "=", placeholder.id)]
            )
        )
