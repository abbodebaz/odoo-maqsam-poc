import html

from odoo import fields, http
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


def _dt(value):
    return fields.Datetime.to_string(value) if value else False


def _base_url():
    return (request.httprequest.url_root or "").rstrip("/")


def _transaction_payload(transaction, ok=None, message=None):
    transaction._ensure_verification_token()
    flow = transaction.flow_id
    if ok is None:
        ok = transaction.state in ("sent", "verified")
    payload = {
        "ok": bool(ok),
        "transaction_id": transaction.id,
        "state": transaction.state,
        "record": transaction.res_name,
        "record_id": transaction.res_id,
        "expires_at": _dt(transaction.expires_at),
        "attempts": transaction.attempt_count,
        "attempts_remaining": transaction.attempts_remaining,
        "verified_at": _dt(transaction.verified_at),
        "verification_channel": transaction.verification_source or False,
        "post_actions_state": getattr(transaction, "post_actions_state", False) or False,
        "message": message or transaction.error_message or "OTP request accepted.",
    }
    token = transaction.verification_token
    root = _base_url()
    if token and flow.pwa_verification_enabled:
        payload["pwa"] = {
            "verification_token": token,
            "verify_url": f"{root}/wati/otp/v1/pwa/{token}/verify",
            "status_url": f"{root}/wati/otp/v1/pwa/{token}/status",
            "resend_url": f"{root}/wati/otp/v1/pwa/{token}/resend",
        }
    if token and flow.website_verification_enabled:
        payload["verification_page_url"] = f"{root}/wati/otp/verify/{token}"
    return payload


def _flow_by_key(flow_key):
    return request.env["wati.otp.flow"].sudo().search(
        [("technical_key", "=", str(flow_key or "").strip()), ("active", "=", True)],
        limit=1,
    )


def _transaction_by_token(token):
    return request.env["wati.otp.transaction"].sudo().search(
        [("verification_token", "=", str(token or "").strip())], limit=1
    )


def _numeric_code(data):
    code = str(data.get("otp_code") or data.get("code") or "").strip()
    if not code.isdigit():
        raise UserError("Enter the numeric OTP sent to the customer.")
    return code


class WatiOtpUniversalController(http.Controller):

    def _external_request(self, flow_key, source):
        data = _payload()
        flow = _flow_by_key(flow_key)
        if not flow:
            return request.make_json_response(
                {"ok": False, "message": "OTP flow not found."}, status=404
            )
        try:
            flow._validate_external_secret(_secret_from_request(data), source)
            transaction = flow.request_by_reference(
                flow.technical_key, data.get("record_id") or data.get("res_id"), source=source
            )
            transaction._ensure_verification_token()
        except UserError as exc:
            return request.make_json_response(
                {"ok": False, "message": str(exc)}, status=400
            )
        status = 200 if transaction.state == "sent" else 422
        return request.make_json_response(
            _transaction_payload(transaction, ok=transaction.state == "sent"), status=status
        )

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

    def _portal_record(self, flow, res_id):
        if not flow.model_name or flow.model_name not in request.env:
            raise UserError("OTP record type is unavailable.")
        record = request.env[flow.model_name].browse(int(res_id or 0)).exists()
        if not record:
            raise UserError("Record not found.")
        try:
            record.check_access("read")
        except AccessError as exc:
            raise UserError("You do not have access to this record.") from exc
        return record

    @http.route(
        "/wati/otp/portal/<string:flow_key>/request/<int:res_id>",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def portal_request(self, flow_key, res_id, **kwargs):
        flow = _flow_by_key(flow_key)
        if not flow:
            return request.make_json_response(
                {"ok": False, "message": "OTP flow not found."}, status=404
            )
        if not flow.portal_entry_enabled:
            return request.make_json_response(
                {"ok": False, "message": "Portal entry is disabled for this OTP flow."},
                status=403,
            )
        try:
            record = self._portal_record(flow, res_id)
            transaction = flow.with_context(
                wati_requested_by_user_id=request.env.user.id
            ).request_otp(record.sudo(), source="portal")
            transaction._ensure_verification_token()
        except UserError as exc:
            return request.make_json_response(
                {"ok": False, "message": str(exc)}, status=400
            )
        status = 200 if transaction.state == "sent" else 422
        return request.make_json_response(
            _transaction_payload(transaction, ok=transaction.state == "sent"), status=status
        )

    @http.route(
        "/wati/otp/portal/<string:flow_key>/verify/<int:res_id>",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def portal_verify(self, flow_key, res_id, **kwargs):
        flow = _flow_by_key(flow_key)
        if not flow:
            return request.make_json_response(
                {"ok": False, "message": "OTP flow not found."}, status=404
            )
        try:
            self._portal_record(flow, res_id)
            data = _payload() or kwargs
            code = _numeric_code(data)
            transaction, ok, message = flow.verify_record_code(
                res_id,
                code,
                source="portal",
                verified_by_user_id=request.env.user.id,
                actor=request.env.user.display_name,
            )
        except UserError as exc:
            return request.make_json_response(
                {"ok": False, "message": str(exc)}, status=400
            )
        return request.make_json_response(
            _transaction_payload(transaction, ok=ok, message=message),
            status=200 if ok else 422,
        )

    @http.route(
        "/wati/otp/portal/<string:flow_key>/status/<int:res_id>",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def portal_status(self, flow_key, res_id, **kwargs):
        flow = _flow_by_key(flow_key)
        if not flow:
            return request.make_json_response(
                {"ok": False, "message": "OTP flow not found."}, status=404
            )
        try:
            self._portal_record(flow, res_id)
            if not flow.portal_verification_enabled:
                raise UserError("Portal verification is disabled for this OTP flow.")
            transaction = flow._latest_transaction_for_record(res_id)
            if not transaction:
                raise UserError("No OTP transaction was found for this record.")
        except UserError as exc:
            return request.make_json_response(
                {"ok": False, "message": str(exc)}, status=400
            )
        return request.make_json_response(_transaction_payload(transaction))

    @http.route(
        "/wati/otp/portal/<string:flow_key>/resend/<int:res_id>",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def portal_resend(self, flow_key, res_id, **kwargs):
        flow = _flow_by_key(flow_key)
        if not flow:
            return request.make_json_response(
                {"ok": False, "message": "OTP flow not found."}, status=404
            )
        try:
            self._portal_record(flow, res_id)
            transaction = flow._latest_transaction_for_record(res_id)
            if not transaction:
                raise UserError("No OTP transaction was found for this record.")
            new_transaction = transaction.resend_for_channel(
                "portal", requested_by_user_id=request.env.user.id
            )
        except UserError as exc:
            return request.make_json_response(
                {"ok": False, "message": str(exc)}, status=400
            )
        return request.make_json_response(
            _transaction_payload(new_transaction, ok=new_transaction.state == "sent"),
            status=200 if new_transaction.state == "sent" else 422,
        )

    def _api_flow(self, flow_key, data):
        flow = _flow_by_key(flow_key)
        if not flow:
            raise UserError("OTP flow not found.")
        flow._validate_verification_secret(_secret_from_request(data))
        return flow

    @http.route(
        "/wati/otp/v1/api/<string:flow_key>/verify",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def api_verify(self, flow_key, **kwargs):
        data = _payload()
        try:
            flow = self._api_flow(flow_key, data)
            code = _numeric_code(data)
            transaction, ok, message = flow.verify_record_code(
                data.get("record_id") or data.get("res_id"),
                code,
                source="api",
                actor=data.get("actor") or "REST API",
            )
        except UserError as exc:
            return request.make_json_response(
                {"ok": False, "message": str(exc)}, status=400
            )
        return request.make_json_response(
            _transaction_payload(transaction, ok=ok, message=message),
            status=200 if ok else 422,
        )

    @http.route(
        "/wati/otp/v1/api/<string:flow_key>/status",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def api_status(self, flow_key, **kwargs):
        data = _payload()
        try:
            flow = self._api_flow(flow_key, data)
            transaction = flow._latest_transaction_for_record(
                data.get("record_id") or data.get("res_id")
            )
            if not transaction:
                raise UserError("No OTP transaction was found for this record.")
        except UserError as exc:
            return request.make_json_response(
                {"ok": False, "message": str(exc)}, status=400
            )
        return request.make_json_response(_transaction_payload(transaction))

    @http.route(
        "/wati/otp/v1/api/<string:flow_key>/resend",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def api_resend(self, flow_key, **kwargs):
        data = _payload()
        try:
            flow = self._api_flow(flow_key, data)
            transaction = flow._latest_transaction_for_record(
                data.get("record_id") or data.get("res_id")
            )
            if not transaction:
                raise UserError("No OTP transaction was found for this record.")
            new_transaction = transaction.resend_for_channel("api")
        except UserError as exc:
            return request.make_json_response(
                {"ok": False, "message": str(exc)}, status=400
            )
        return request.make_json_response(
            _transaction_payload(new_transaction, ok=new_transaction.state == "sent"),
            status=200 if new_transaction.state == "sent" else 422,
        )

    def _pwa_transaction(self, token):
        transaction = _transaction_by_token(token)
        if not transaction:
            raise UserError("Verification session not found.")
        if not transaction.flow_id.pwa_verification_enabled:
            raise UserError("PWA verification is disabled for this OTP flow.")
        return transaction

    @http.route(
        "/wati/otp/v1/pwa/<string:token>/status",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def pwa_status(self, token, **kwargs):
        try:
            transaction = self._pwa_transaction(token)
        except UserError as exc:
            return request.make_json_response(
                {"ok": False, "message": str(exc)}, status=404
            )
        return request.make_json_response(_transaction_payload(transaction))

    @http.route(
        "/wati/otp/v1/pwa/<string:token>/verify",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def pwa_verify(self, token, **kwargs):
        data = _payload()
        try:
            transaction = self._pwa_transaction(token)
            code = _numeric_code(data)
            ok, message = transaction.with_context(
                wati_verification_source="pwa",
                wati_verification_actor=data.get("actor") or "PWA / Web App",
            ).verify_code(code)
        except UserError as exc:
            return request.make_json_response(
                {"ok": False, "message": str(exc)}, status=400
            )
        return request.make_json_response(
            _transaction_payload(transaction, ok=ok, message=message),
            status=200 if ok else 422,
        )

    @http.route(
        "/wati/otp/v1/pwa/<string:token>/resend",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def pwa_resend(self, token, **kwargs):
        try:
            transaction = self._pwa_transaction(token)
            new_transaction = transaction.resend_for_channel("pwa")
        except UserError as exc:
            return request.make_json_response(
                {"ok": False, "message": str(exc)}, status=400
            )
        return request.make_json_response(
            _transaction_payload(new_transaction, ok=new_transaction.state == "sent"),
            status=200 if new_transaction.state == "sent" else 422,
        )

    def _website_transaction(self, token):
        transaction = _transaction_by_token(token)
        if not transaction:
            raise UserError("Verification session not found.")
        if not transaction.flow_id.website_verification_enabled:
            raise UserError("Website verification is disabled for this OTP flow.")
        return transaction

    def _verification_page(self, transaction, message="", message_type="info"):
        transaction._ensure_verification_token()
        flow = transaction.flow_id
        state = transaction.state
        verified = state == "verified"
        waiting = state == "sent"
        title = html.escape(flow.name or "OTP Verification")
        record = html.escape(transaction.res_name or "Service")
        phone = html.escape(transaction.phone_masked or "")
        message_html = ""
        if message:
            cls = "ok" if message_type == "success" else "warn" if message_type == "warning" else "error"
            message_html = f'<div class="notice {cls}">{html.escape(str(message))}</div>'

        if verified:
            form_html = (
                '<div class="success-box"><div class="check">✓</div>'
                '<h2>OTP verified</h2><p>The confirmation was accepted successfully.</p></div>'
            )
        elif waiting:
            form_html = f"""
                <form method="post" action="/wati/otp/verify/{transaction.verification_token}" class="verify-form">
                    <label for="otp_code">6-digit verification code</label>
                    <input id="otp_code" name="otp_code" inputmode="numeric" pattern="[0-9]*" autocomplete="one-time-code" maxlength="8" placeholder="Enter OTP" required autofocus/>
                    <button type="submit">Verify OTP</button>
                </form>
            """
        else:
            state_label = html.escape(dict(transaction._fields["state"].selection).get(state, state))
            form_html = f'<div class="notice warn">This OTP is {state_label}. Send a new code to continue.</div>'

        resend_html = ""
        if flow.allow_resend and not verified:
            resend_html = f"""
                <form method="post" action="/wati/otp/verify/{transaction.verification_token}/resend" class="resend-form">
                    <button type="submit" class="secondary">Resend OTP</button>
                </form>
            """

        expires = html.escape(_dt(transaction.expires_at) or "—")
        attempts = transaction.attempts_remaining
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow"><title>{title}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f7f5f9;color:#24202a;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}.wrap{{max-width:560px;margin:0 auto;padding:28px 18px 48px}}.brand{{color:#76529b;font-size:13px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}}.card{{margin-top:14px;background:#fff;border:1px solid #e7e1ec;border-radius:20px;padding:24px;box-shadow:0 12px 34px rgba(60,42,73,.08)}}h1{{font-size:25px;margin:0 0 7px}}.sub{{margin:0;color:#766e7e}}.meta{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:20px 0}}.meta div{{background:#faf8fb;border-radius:12px;padding:11px}}.meta small{{display:block;color:#8a8191;margin-bottom:3px}}.meta strong{{font-size:14px}}label{{display:block;font-weight:700;margin:0 0 8px}}input{{width:100%;height:54px;border:1px solid #d9d1df;border-radius:13px;padding:0 16px;font-size:22px;letter-spacing:.18em;outline:none}}input:focus{{border-color:#7c5aa5;box-shadow:0 0 0 3px rgba(124,90,165,.12)}}button{{width:100%;height:50px;margin-top:12px;border:0;border-radius:13px;background:#76529b;color:#fff;font-size:16px;font-weight:750;cursor:pointer}}button.secondary{{background:#f0ebf4;color:#5d416f}}.notice{{margin:16px 0;padding:12px 14px;border-radius:12px;background:#f4f1f6}}.notice.ok{{background:#ebf8ef;color:#176b34}}.notice.warn{{background:#fff6dd;color:#7e5b00}}.notice.error{{background:#fdecec;color:#9c2727}}.success-box{{text-align:center;padding:20px 4px}}.check{{width:58px;height:58px;line-height:58px;margin:0 auto 10px;border-radius:50%;background:#e9f8ee;color:#16853d;font-size:30px;font-weight:800}}.success-box h2{{margin:6px 0}}.success-box p{{color:#716979}}.foot{{text-align:center;color:#918899;font-size:12px;margin-top:16px}}@media(max-width:480px){{.wrap{{padding:18px 12px 36px}}.card{{padding:19px;border-radius:17px}}.meta{{grid-template-columns:1fr}}}}
</style></head><body><main class="wrap"><div class="brand">WATI OTP Bridge</div><section class="card"><h1>{title}</h1><p class="sub">Confirm the service with the code sent on WhatsApp.</p>{message_html}<div class="meta"><div><small>Record</small><strong>{record}</strong></div><div><small>WhatsApp</small><strong>{phone}</strong></div><div><small>Expires</small><strong>{expires}</strong></div><div><small>Attempts remaining</small><strong>{attempts}</strong></div></div>{form_html}{resend_html}</section><div class="foot">Secure verification · OTP Bridge</div></main></body></html>"""
        return request.make_response(
            page,
            headers=[
                ("Content-Type", "text/html; charset=utf-8"),
                ("Cache-Control", "no-store, no-cache, must-revalidate"),
                ("X-Robots-Tag", "noindex, nofollow"),
            ],
        )

    @http.route(
        "/wati/otp/verify/<string:token>",
        type="http",
        auth="none",
        methods=["GET", "POST"],
        csrf=False,
    )
    def website_verify(self, token, **post):
        try:
            transaction = self._website_transaction(token)
        except UserError:
            return request.make_response(
                "Verification session not found or unavailable.", status=404
            )
        if request.httprequest.method == "POST":
            code = str(post.get("otp_code") or "").strip()
            if not code.isdigit():
                return self._verification_page(
                    transaction, "Enter the numeric OTP sent to the customer.", "error"
                )
            try:
                ok, message = transaction.with_context(
                    wati_verification_source="website",
                    wati_verification_actor="Website verification page",
                ).verify_code(code)
            except UserError as exc:
                return self._verification_page(transaction, str(exc), "error")
            return self._verification_page(
                transaction, message, "success" if ok else "error"
            )
        return self._verification_page(transaction)

    @http.route(
        "/wati/otp/verify/<string:token>/resend",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def website_resend(self, token, **post):
        try:
            transaction = self._website_transaction(token)
            new_transaction = transaction.resend_for_channel("website")
        except UserError as exc:
            try:
                transaction = self._website_transaction(token)
                return self._verification_page(transaction, str(exc), "error")
            except UserError:
                return request.make_response(str(exc), status=400)
        return request.redirect(
            f"/wati/otp/verify/{new_transaction.verification_token}"
        )
