import hmac

from odoo import http
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
