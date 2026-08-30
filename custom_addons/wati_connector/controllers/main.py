import hmac

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request


class WatiWebhookController(http.Controller):

    @http.route(
        "/wati/webhook/<string:token>",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def webhook(self, token, **kwargs):
        configured = request.env["ir.config_parameter"].sudo().get_param("wati_connector.webhook_token") or ""
        if not configured or not hmac.compare_digest(str(token), str(configured)):
            return request.make_json_response({"ok": False, "message": "unauthorized"}, status=401)

        payload = request.httprequest.get_json(silent=True)
        if payload is None:
            return request.make_json_response({"ok": False, "message": "invalid json"}, status=400)

        events = payload if isinstance(payload, list) else [payload]
        accepted = 0
        for event in events:
            if isinstance(event, dict):
                request.env["wati.webhook.event"].sudo().ingest(event)
                accepted += 1

        # WATI expects HTTP 200 to acknowledge successful receipt.
        return request.make_json_response({"ok": True, "accepted": accepted}, status=200)

    @http.route(
        "/wati/inbox",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def inbox(self, **kwargs):
        """Standalone authenticated inbox.

        The page intentionally does not register anything in web.assets_web,
        so a UI error here cannot break the Odoo backend shell.
        """
        return request.render(
            "wati_connector.wati_inbox_page",
            {
                "csrf_token": request.csrf_token(),
                "user_name": request.env.user.name or "Odoo",
            },
        )

    @http.route(
        "/wati/inbox/data",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def inbox_data(self, conversation_id=None, **kwargs):
        conversation_model = request.env["wati.conversation"]
        conversations = conversation_model.search([], order="last_message_at desc, id desc", limit=150)

        selected = conversation_model.browse()
        try:
            selected_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            selected_id = 0

        if selected_id:
            candidate = conversation_model.browse(selected_id).exists()
            if candidate:
                selected = candidate
        if not selected and conversations:
            selected = conversations[0]

        if selected and selected.unread_count:
            selected.write({"unread_count": 0})

        messages = request.env["wati.message"].browse()
        if selected:
            latest = request.env["wati.message"].search(
                [("conversation_id", "=", selected.id)],
                order="received_at desc, id desc",
                limit=250,
            )
            messages = latest.sorted(key=lambda message: (message.received_at or fields.Datetime.now(), message.id))

        conversation_rows = []
        for conversation in conversations:
            conversation_rows.append(
                {
                    "id": conversation.id,
                    "name": conversation.name or conversation.sender_name or conversation.wa_id or "WhatsApp",
                    "wa_id": conversation.wa_id or "",
                    "operator_name": conversation.operator_name or "",
                    "status": conversation.status or "",
                    "last_message": conversation.last_message or "",
                    "last_message_at": fields.Datetime.to_string(conversation.last_message_at) if conversation.last_message_at else "",
                    "unread_count": conversation.unread_count or 0,
                    "partner_id": conversation.partner_id.id if conversation.partner_id else False,
                    "partner_name": conversation.partner_id.display_name if conversation.partner_id else "",
                }
            )

        message_rows = []
        for message in messages:
            message_rows.append(
                {
                    "id": message.id,
                    "external_id": message.name or "",
                    "direction": message.direction or "inbound",
                    "sender_name": message.sender_name or "",
                    "text": message.text or "",
                    "message_type": message.message_type or "text",
                    "status": message.status or "",
                    "operator_name": message.operator_name or "",
                    "received_at": fields.Datetime.to_string(message.received_at) if message.received_at else "",
                }
            )

        return request.make_json_response(
            {
                "ok": True,
                "selected_id": selected.id if selected else False,
                "conversations": conversation_rows,
                "messages": message_rows,
            },
            status=200,
        )

    @http.route(
        "/wati/inbox/send",
        type="http",
        auth="user",
        methods=["POST"],
    )
    def inbox_send(self, conversation_id=None, message=None, **kwargs):
        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0

        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return request.make_json_response({"ok": False, "message": "المحادثة غير موجودة."}, status=404)

        try:
            conversation.send_session_message(message or "")
        except UserError as exc:
            return request.make_json_response({"ok": False, "message": str(exc)}, status=400)

        return request.make_json_response({"ok": True, "message": "تم الإرسال إلى WATI."}, status=200)
