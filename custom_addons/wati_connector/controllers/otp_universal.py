from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request


def _payload():
    data = request.httprequest.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _secret_from_request(data):
    return (
        request.httprequest.headers.get("X-WATI-OTP-Secret")
        or data.get("secret")
        or ""
    )


def _response_for_transaction(transaction):
    return {
        "ok": transaction.state == "sent",
        "transaction_id": transaction.id,
        "state": transaction.state,
        "record": transaction.res_name,
        "expires_at": transaction.expires_at,
        "message": transaction.error_message or "OTP request accepted.",
    }


class WatiOtpUniversalController(http.Controller):

    def _external_request(self, flow_key, source):
        data = _payload()
        Flow = request.env["wati.otp.flow"].sudo()
        flow = Flow.search(
            [("technical_key", "=", str(flow_key or "").strip()), ("active", "=", True)],
            limit=1,
        )
        if not flow:
            return request.make_json_response(
                {"ok": False, "message": "OTP flow not found."}, status=404
            )
        try:
            flow._validate_external_secret(_secret_from_request(data), source)
            transaction = Flow.request_by_reference(
                flow.technical_key, data.get("record_id") or data.get("res_id"), source=source
            )
        except UserError as exc:
            return request.make_json_response(
                {"ok": False, "message": str(exc)}, status=400
            )
        status = 200 if transaction.state == "sent" else 422
        return request.make_json_response(_response_for_transaction(transaction), status=status)

    @http.route(
        "/wati/otp/v1/api/<string:flow_key>/request",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def api_request(self, flow_key, **kwargs):
        return self._external_request(flow_key, "api")

    @http.route(
        "/wati/otp/v1/webhook/<string:flow_key>",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def webhook_request(self, flow_key, **kwargs):
        return self._external_request(flow_key, "webhook")

    @http.route(
        "/wati/otp/v1/form/<string:flow_key>/request",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def website_form_request(self, flow_key, **kwargs):
        return self._external_request(flow_key, "website_form")

    @http.route(
        "/wati/otp/portal/<string:flow_key>/request/<int:res_id>",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def portal_request(self, flow_key, res_id, **kwargs):
        Flow = request.env["wati.otp.flow"].sudo()
        flow = Flow.search(
            [("technical_key", "=", str(flow_key or "").strip()), ("active", "=", True)],
            limit=1,
        )
        if not flow:
            return request.make_json_response(
                {"ok": False, "message": "OTP flow not found."}, status=404
            )
        if not flow.portal_entry_enabled:
            return request.make_json_response(
                {"ok": False, "message": "Portal entry is disabled for this OTP flow."},
                status=403,
            )
        if not flow.model_name or flow.model_name not in request.env:
            return request.make_json_response(
                {"ok": False, "message": "OTP record type is unavailable."}, status=400
            )

        record = request.env[flow.model_name].browse(res_id).exists()
        if not record:
            return request.make_json_response(
                {"ok": False, "message": "Record not found."}, status=404
            )
        try:
            record.check_access("read")
        except AccessError:
            return request.make_json_response(
                {"ok": False, "message": "You do not have access to this record."},
                status=403,
            )

        try:
            transaction = flow.with_context(
                wati_requested_by_user_id=request.env.user.id
            ).request_otp(record.sudo(), source="portal")
        except UserError as exc:
            return request.make_json_response(
                {"ok": False, "message": str(exc)}, status=400
            )
        status = 200 if transaction.state == "sent" else 422
        return request.make_json_response(_response_for_transaction(transaction), status=status)
