import hmac
import json

from odoo import http
from odoo.http import request


class MaqsamWebhookController(http.Controller):
    def _token_is_valid(self, supplied):
        params = request.env["ir.config_parameter"].sudo()
        expected = (params.get_param("maqsam_connector.webhook_token") or "").strip()
        supplied = (supplied or "").strip()
        return bool(expected and supplied and hmac.compare_digest(expected, supplied))

    @http.route(
        "/maqsam/webhook/notify/<string:token>",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def notify(self, token, **kwargs):
        if not self._token_is_valid(token):
            return request.make_response("Forbidden", status=403)

        if request.httprequest.method == "GET":
            payload = request.httprequest.args.to_dict(flat=True)
        else:
            payload = request.httprequest.get_json(silent=True)
            if not isinstance(payload, dict):
                payload = request.httprequest.form.to_dict(flat=True)

        def as_int(value):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return 0

        agents = payload.get("agents")
        if isinstance(agents, str):
            agents_json = agents
        else:
            agents_json = json.dumps(agents or [], ensure_ascii=False)

        request.env["maqsam.call.event"].sudo().create(
            {
                "call_id": str(payload.get("id") or ""),
                "caller": str(payload.get("caller") or ""),
                "callee": str(payload.get("callee") or ""),
                "caller_number": str(payload.get("callerNumber") or ""),
                "callee_number": str(payload.get("calleeNumber") or ""),
                "state": str(payload.get("state") or ""),
                "direction": str(payload.get("direction") or ""),
                "event_timestamp": as_int(payload.get("timestamp")),
                "duration": as_int(payload.get("duration")),
                "handling_time": as_int(payload.get("handlingTime")),
                "agents_json": agents_json,
                "payload_json": json.dumps(payload, ensure_ascii=False, default=str),
            }
        )
        return request.make_response("ok", status=200)

    @http.route(
        "/maqsam/api/events",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def events(self, **kwargs):
        try:
            limit = min(max(int(kwargs.get("limit") or 50), 1), 200)
        except ValueError:
            limit = 50

        records = request.env["maqsam.call.event"].sudo().search([], limit=limit)
        payload = [
            {
                "id": record.id,
                "call_id": record.call_id,
                "caller": record.caller,
                "callee": record.callee,
                "callerNumber": record.caller_number,
                "calleeNumber": record.callee_number,
                "state": record.state,
                "direction": record.direction,
                "timestamp": record.event_timestamp,
                "duration": record.duration,
                "handlingTime": record.handling_time,
                "agents": record.agents_json,
                "receivedAt": record.received_at.isoformat() if record.received_at else None,
            }
            for record in records
        ]
        response = request.make_json_response({"ok": True, "events": payload})
        response.headers["Cache-Control"] = "no-store, private, max-age=0"
        return response
