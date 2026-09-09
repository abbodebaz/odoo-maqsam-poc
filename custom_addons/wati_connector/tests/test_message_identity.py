import json

from odoo.tests.common import TransactionCase


class TestWatiMessageIdentity(TransactionCase):

    def test_v2_callback_merges_local_and_provider_rows(self):
        conversation = self.env["wati.conversation"].create(
            {
                "name": "Identity test",
                "wa_id": "966500009999",
                "conversation_uid": "conversation-identity-test",
            }
        )
        local_id = "local-identity-1"
        whatsapp_id = "wamid.identity-1"
        local_message = self.env["wati.message"].create(
            {
                "name": local_id,
                "local_message_id": local_id,
                "conversation_id": conversation.id,
                "conversation_uid": conversation.conversation_uid,
                "wa_id": conversation.wa_id,
                "direction": "outbound",
                "message_type": "text",
                "text": "identity test",
                "status": "Accepted",
                "raw_payload": json.dumps(
                    {
                        "source": "odoo_session_send",
                        "localMessageId": local_id,
                        "httpStatus": 200,
                    }
                ),
            }
        )

        self.env["wati.webhook.event"].ingest(
            {
                "eventType": "sessionMessageSent",
                "id": "event-identity-legacy",
                "whatsappMessageId": whatsapp_id,
                "conversationId": conversation.conversation_uid,
                "ticketId": "ticket-identity-test",
                "waId": conversation.wa_id,
                "text": "identity test",
                "type": "text",
                "statusString": "SENT",
                "owner": True,
            }
        )
        self.assertEqual(
            self.env["wati.message"].search_count(
                [
                    "|",
                    ("local_message_id", "=", local_id),
                    ("whatsapp_message_id", "=", whatsapp_id),
                ]
            ),
            2,
        )

        self.env["wati.webhook.event"].ingest(
            {
                "eventType": "sessionMessageSent_v2",
                "id": "event-identity-v2",
                "localMessageId": local_id,
                "whatsappMessageId": whatsapp_id,
                "conversationId": conversation.conversation_uid,
                "ticketId": "ticket-identity-test",
                "waId": conversation.wa_id,
                "text": "identity test",
                "type": "text",
                "statusString": "SENT",
                "owner": True,
            }
        )

        rows = self.env["wati.message"].search(
            [
                "|",
                ("local_message_id", "=", local_id),
                ("whatsapp_message_id", "=", whatsapp_id),
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.id, local_message.id)
        self.assertEqual(rows.local_message_id, local_id)
        self.assertEqual(rows.whatsapp_message_id, whatsapp_id)
        self.assertEqual(rows.status, "SENT")

    def test_conflicting_provider_ids_are_not_collapsed_by_local_id(self):
        conversation = self.env["wati.conversation"].create(
            {"name": "Conflict test", "wa_id": "966500007771"}
        )
        local_id = "local-conflict-1"
        for index in (1, 2):
            self.env["wati.message"].create(
                {
                    "name": f"wamid.conflict-{index}",
                    "whatsapp_message_id": f"wamid.conflict-{index}",
                    "local_message_id": local_id,
                    "conversation_id": conversation.id,
                    "wa_id": conversation.wa_id,
                    "direction": "outbound",
                    "status": "SENT",
                }
            )

        rows = self.env["wati.message"].search(
            [("local_message_id", "=", local_id)]
        )
        rows._wati_reconcile_identity()
        self.assertEqual(
            self.env["wati.message"].search_count(
                [("local_message_id", "=", local_id)]
            ),
            2,
        )
