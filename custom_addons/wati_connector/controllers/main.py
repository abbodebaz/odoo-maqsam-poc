import hashlib
import hmac
import re
import threading
import time

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request


_SEND_GUARD = {}
_SEND_GUARD_LOCK = threading.Lock()
_SEND_GUARD_TTL = 120.0

_PARTNER_CACHE = {}
_PARTNER_CACHE_LOCK = threading.Lock()
_PARTNER_CACHE_TTL = 300.0


def _reserve_send_guard(user_id, conversation_id, request_id, message):
    now = time.monotonic()
    request_id = (request_id or "").strip()
    if request_id:
        key = f"{user_id}:{request_id}"
    else:
        digest = hashlib.sha256((message or "").encode("utf-8")).hexdigest()
        key = f"{user_id}:{conversation_id}:{digest}"

    with _SEND_GUARD_LOCK:
        expired = [item for item, created_at in _SEND_GUARD.items() if now - created_at > _SEND_GUARD_TTL]
        for item in expired:
            _SEND_GUARD.pop(item, None)

        if key in _SEND_GUARD:
            return key, False

        _SEND_GUARD[key] = now
        return key, True


def _release_send_guard(key):
    with _SEND_GUARD_LOCK:
        _SEND_GUARD.pop(key, None)


def _phone_identity(value):
    digits = re.sub(r"\D+", "", str(value or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    if not digits:
        return {"digits": "", "e164": "", "local": "", "suffix": ""}

    if digits.startswith("966"):
        international = digits
        local = "0" + digits[3:] if len(digits) > 3 else digits
    elif digits.startswith("0") and len(digits) >= 9:
        local = digits
        international = "966" + digits[1:]
    elif len(digits) == 9 and digits.startswith("5"):
        local = "0" + digits
        international = "966" + digits
    else:
        local = digits
        international = digits

    return {
        "digits": digits,
        "e164": f"+{international}" if international else "",
        "local": local,
        "suffix": international[-9:] if international else digits[-9:],
    }


def _partner_phone_fields(partner_model):
    return [field_name for field_name in ("mobile", "phone") if field_name in partner_model._fields]


def _partner_phone_value(partner):
    if not partner:
        return ""
    for field_name in _partner_phone_fields(partner):
        value = partner[field_name]
        if value:
            return value
    return ""


def _find_partner_by_wa_id(wa_id):
    identity = _phone_identity(wa_id)
    cache_key = identity["digits"]
    if not cache_key:
        return request.env["res.partner"].browse()

    now = time.monotonic()
    with _PARTNER_CACHE_LOCK:
        cached = _PARTNER_CACHE.get(cache_key)
        if cached and now - cached[0] <= _PARTNER_CACHE_TTL:
            partner_id = cached[1]
            return request.env["res.partner"].sudo().browse(partner_id).exists() if partner_id else request.env["res.partner"].browse()

    partner_model = request.env["res.partner"].sudo()
    partner = partner_model.browse()

    if "phone_sanitized" in partner_model._fields and identity["e164"]:
        partner = partner_model.search(
            [("phone_sanitized", "=", identity["e164"])],
            order="id asc",
            limit=1,
        )

    phone_fields = _partner_phone_fields(partner_model)
    if not partner and identity["suffix"] and phone_fields:
        hint = identity["suffix"][-4:]
        domain = []
        for index, field_name in enumerate(phone_fields):
            if index:
                domain.insert(0, "|")
            domain.append((field_name, "ilike", hint))

        candidates = partner_model.search(domain, order="id asc", limit=100)
        for candidate in candidates:
            for field_name in phone_fields:
                candidate_identity = _phone_identity(candidate[field_name])
                if candidate_identity["suffix"] and candidate_identity["suffix"] == identity["suffix"]:
                    partner = candidate
                    break
            if partner:
                break

    with _PARTNER_CACHE_LOCK:
        _PARTNER_CACHE[cache_key] = (now, partner.id if partner else 0)

    return partner


def _partner_url(partner):
    if not partner:
        return ""
    action = request.env.ref("contacts.action_contacts", raise_if_not_found=False)
    url = f"/web#id={partner.id}&model=res.partner&view_type=form"
    if action:
        url += f"&action={action.id}"
    return url


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

        return request.make_json_response({"ok": True, "accepted": accepted}, status=200)

    @http.route(
        "/wati/inbox",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def inbox(self, **kwargs):
        conversations_action = request.env.ref(
            "wati_connector.action_wati_conversations",
            raise_if_not_found=False,
        )
        odoo_return_url = (
            f"/odoo/action-{conversations_action.id}"
            if conversations_action
            else "/odoo"
        )
        return request.render(
            "wati_connector.wati_inbox_page",
            {
                "csrf_token": request.csrf_token(),
                "user_name": request.env.user.name or "Odoo",
                "odoo_return_url": odoo_return_url,
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
        current_user = request.env.user

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
            wati_name = conversation.name or conversation.sender_name or conversation.wa_id or "WhatsApp"
            partner = conversation.partner_id or _find_partner_by_wa_id(conversation.wa_id)
            display_name = partner.display_name if partner else wati_name
            assigned = conversation.assigned_user_id
            conversation_rows.append(
                {
                    "id": conversation.id,
                    "name": display_name,
                    "wati_name": wati_name,
                    "wa_id": conversation.wa_id or "",
                    "operator_name": conversation.operator_name or "",
                    "status": conversation.status or "",
                    "last_message": conversation.last_message or "",
                    "last_message_at": fields.Datetime.to_string(conversation.last_message_at) if conversation.last_message_at else "",
                    "unread_count": conversation.unread_count or 0,
                    "partner_id": partner.id if partner else False,
                    "partner_name": partner.display_name if partner else "",
                    "partner_phone": _partner_phone_value(partner),
                    "partner_url": _partner_url(partner),
                    "assigned_user_id": assigned.id if assigned else False,
                    "assigned_user_name": assigned.name if assigned else "",
                    "assigned_to_me": bool(assigned and assigned == current_user),
                    "is_unassigned": not bool(assigned),
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
                "current_user_id": current_user.id,
                "current_user_name": current_user.name,
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
    def inbox_send(self, conversation_id=None, message=None, request_id=None, **kwargs):
        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0

        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return request.make_json_response({"ok": False, "message": "المحادثة غير موجودة."}, status=404)

        guard_key, reserved = _reserve_send_guard(
            request.env.user.id,
            conversation_id,
            request_id,
            message or "",
        )
        if not reserved:
            return request.make_json_response(
                {"ok": True, "message": "تم تجاهل إعادة إرسال مكررة.", "duplicate_suppressed": True},
                status=200,
            )

        try:
            conversation.send_session_message(message or "")
        except UserError as exc:
            _release_send_guard(guard_key)
            return request.make_json_response({"ok": False, "message": str(exc)}, status=400)
        except Exception:
            _release_send_guard(guard_key)
            raise

        return request.make_json_response({"ok": True, "message": "تم الإرسال إلى WATI."}, status=200)
