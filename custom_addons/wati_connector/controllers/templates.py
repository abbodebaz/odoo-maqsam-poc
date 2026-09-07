import json
import re
import time

from odoo import http
from odoo.http import request

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.idempotency import WatiIdempotency


def _find_template_list(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("messageTemplates", "templates", "items", "results", "result", "data", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _find_template_list(value)
            if nested:
                return nested
    for value in payload.values():
        if isinstance(value, (dict, list)):
            nested = _find_template_list(value)
            if nested:
                return nested
    return []


def _first(mapping, keys):
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _body_text(item):
    body = item.get("body") if isinstance(item, dict) else None
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        text = _first(body, ("text", "body", "content"))
        if text:
            return text
    components = item.get("components") if isinstance(item, dict) else None
    if isinstance(components, list):
        for component in components:
            if isinstance(component, dict) and str(component.get("type") or "").upper() == "BODY":
                text = _first(component, ("text", "body", "content"))
                if text:
                    return text
    return ""


def _params(item, body):
    raw = item.get("customParams") if isinstance(item, dict) else None
    names = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                name = _first(entry, ("name", "paramName", "key", "field"))
            elif isinstance(entry, str):
                name = entry.strip()
            else:
                name = ""
            if name and name not in names:
                names.append(name)
    for token in re.findall(r"{{\s*([^{}]+?)\s*}}", body or ""):
        token = token.strip()
        if token and token not in names:
            names.append(token)
    return names


def _normalize_template(item):
    if not isinstance(item, dict):
        return None
    name = _first(item, ("elementName", "templateName", "template_name", "name"))
    if not name:
        return None
    body = _body_text(item)
    return {
        "name": name,
        "body": body,
        "status": _first(item, ("status", "approvalStatus", "templateStatus")),
        "language": _first(item, ("language", "languageCode", "locale")),
        "category": _first(item, ("category", "templateCategory")),
        "params": _params(item, body),
        "channel_number": _first(item, ("channelPhoneNumber", "channel_number", "channelNumber", "phoneNumber")),
    }


class WatiTemplateController(http.Controller):

    @http.route("/wati/inbox/templates", type="http", auth="user", methods=["GET"], csrf=False)
    def templates(self, **kwargs):
        try:
            response = WatiClient(request.env).get_message_templates(page_size=200, page_number=1)
        except WatiConfigurationError:
            return request.make_json_response({"ok": False, "message": "إعدادات WATI API غير مكتملة."}, status=503)
        except WatiRequestError as exc:
            detail = (exc.response_text or str(exc) or "").strip()[:600]
            status = exc.status_code or 502
            return request.make_json_response({"ok": False, "message": f"WATI رفض جلب القوالب ({status}): {detail}"}, status=status)
        try:
            payload = response.json()
        except ValueError:
            return request.make_json_response({"ok": False, "message": "WATI أعاد استجابة غير مفهومة عند جلب القوالب."}, status=502)
        rows = [row for row in (_normalize_template(item) for item in _find_template_list(payload)) if row]
        rows.sort(key=lambda row: (row["name"].lower(), row["language"].lower()))
        return request.make_json_response({"ok": True, "templates": rows}, status=200)

    @http.route("/wati/inbox/send-template", type="http", auth="user", methods=["POST"])
    def send_template(self, conversation_id=None, template_name=None, params_json=None, channel_number=None, request_id=None, **kwargs):
        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0
        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return request.make_json_response({"ok": False, "message": "المحادثة غير موجودة."}, status=404)

        current_user = request.env.user
        if not conversation.assigned_user_id:
            return request.make_json_response({"ok": False, "message": "استلم المحادثة أولًا قبل إرسال قالب."}, status=409)
        if conversation.assigned_user_id != current_user:
            return request.make_json_response({"ok": False, "message": f"المحادثة عند {conversation.assigned_user_id.name}. انقل المحادثة إليك أولًا."}, status=409)

        template_name = (template_name or "").strip()
        if not template_name:
            return request.make_json_response({"ok": False, "message": "اختر قالبًا أولًا."}, status=400)
        if not conversation.wa_id:
            return request.make_json_response({"ok": False, "message": "لا يوجد رقم WhatsApp للمحادثة."}, status=400)

        try:
            values = json.loads(params_json or "[]")
        except ValueError:
            values = []
        custom_params = []
        if isinstance(values, list):
            for entry in values:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name") or "").strip()
                value = str(entry.get("value") or "").strip()
                if name:
                    custom_params.append({"name": name, "value": value})

        idem = WatiIdempotency(request.env)
        scope = f"outbound:template:user:{current_user.id}"
        key = (request_id or "").strip() or idem.digest(conversation.id, template_name, params_json or "", channel_number or "")
        if not idem.acquire(scope, key, ttl_seconds=180):
            return request.make_json_response({"ok": True, "duplicate_suppressed": True, "message": "تم تجاهل إعادة إرسال مكررة."}, status=200)

        client = WatiClient(request.env)
        body = {
            "template_name": template_name,
            "broadcast_name": f"odoo_{template_name}_{int(time.time())}",
            "receivers": [{"whatsappNumber": conversation.wa_id, "customParams": custom_params}],
        }
        effective_channel = (channel_number or client.config.channel_number or "").strip()
        if effective_channel:
            body["channel_number"] = effective_channel

        try:
            client.send_template_messages(body)
        except WatiConfigurationError:
            idem.release(scope, key)
            return request.make_json_response({"ok": False, "message": "إعدادات WATI API غير مكتملة."}, status=503)
        except WatiRequestError as exc:
            idem.release(scope, key)
            detail = (exc.response_text or str(exc) or "").strip()[:1000]
            status = exc.status_code or 502
            return request.make_json_response({"ok": False, "message": f"WATI رفض إرسال القالب ({status}): {detail}"}, status=status)

        return request.make_json_response({"ok": True, "message": "تم إرسال القالب إلى WATI."}, status=200)
