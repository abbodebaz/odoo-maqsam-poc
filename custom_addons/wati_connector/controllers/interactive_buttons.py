import json

from odoo import http
from odoo.http import request

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.idempotency import WatiIdempotency


def _clean(value):
    return str(value or "").strip()


def _parse_buttons(value):
    try:
        raw = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        text = _clean(item.get("text")) if isinstance(item, dict) else _clean(item)
        if text:
            result.append(text)
    return result


class WatiInteractiveButtonsController(http.Controller):

    @http.route("/wati/inbox/send-buttons", type="http", auth="user", methods=["POST"])
    def send_buttons(
        self,
        conversation_id=None,
        header=None,
        body=None,
        footer=None,
        buttons_json=None,
        request_id=None,
        **kwargs,
    ):
        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0

        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return request.make_json_response(
                {"ok": False, "message": "المحادثة غير موجودة."}, status=404
            )

        current_user = request.env.user
        if not conversation.assigned_user_id:
            return request.make_json_response(
                {"ok": False, "message": "استلم المحادثة أولًا قبل إرسال رسالة تفاعلية."},
                status=409,
            )
        if conversation.assigned_user_id != current_user:
            return request.make_json_response(
                {
                    "ok": False,
                    "message": (
                        f"المحادثة مستلمة بواسطة {conversation.assigned_user_id.name}. "
                        "انقل المحادثة إليك أولًا."
                    ),
                },
                status=409,
            )
        if not conversation.wa_id:
            return request.make_json_response(
                {"ok": False, "message": "لا يوجد رقم WhatsApp لهذه المحادثة."},
                status=400,
            )

        header = _clean(header)
        body = _clean(body)
        footer = _clean(footer)
        buttons = _parse_buttons(buttons_json)
        if not body:
            return request.make_json_response(
                {"ok": False, "message": "اكتب نص الرسالة التفاعلية."}, status=400
            )
        if len(header) > 60:
            return request.make_json_response(
                {"ok": False, "message": "عنوان الرسالة يجب ألا يتجاوز 60 حرفًا."},
                status=400,
            )
        if len(body) > 1024:
            return request.make_json_response(
                {"ok": False, "message": "نص الرسالة يجب ألا يتجاوز 1024 حرفًا."},
                status=400,
            )
        if len(footer) > 60:
            return request.make_json_response(
                {"ok": False, "message": "تذييل الرسالة يجب ألا يتجاوز 60 حرفًا."},
                status=400,
            )
        if not 1 <= len(buttons) <= 3:
            return request.make_json_response(
                {"ok": False, "message": "أضف من زر واحد إلى 3 أزرار."}, status=400
            )
        if any(len(text) > 20 for text in buttons):
            return request.make_json_response(
                {"ok": False, "message": "نص كل زر يجب ألا يتجاوز 20 حرفًا."},
                status=400,
            )
        normalized = [text.casefold() for text in buttons]
        if len(set(normalized)) != len(normalized):
            return request.make_json_response(
                {"ok": False, "message": "اجعل نص كل زر مختلفًا عن الآخر."},
                status=400,
            )

        payload = {"body": body, "buttons": [{"text": text} for text in buttons]}
        if header:
            payload["header"] = {"type": "Text", "text": header}
        if footer:
            payload["footer"] = footer

        idem = WatiIdempotency(request.env)
        scope = f"outbound:buttons:user:{current_user.id}"
        key = (request_id or "").strip() or idem.digest(
            conversation.id, header, body, footer, buttons_json or ""
        )
        if not idem.acquire(scope, key, ttl_seconds=180):
            return request.make_json_response(
                {
                    "ok": True,
                    "duplicate_suppressed": True,
                    "message": "تم تجاهل إعادة إرسال مكررة.",
                },
                status=200,
            )

        try:
            WatiClient(request.env).send_interactive_buttons(conversation.wa_id, payload)
        except WatiConfigurationError:
            idem.release(scope, key)
            return request.make_json_response(
                {"ok": False, "message": "إعدادات WATI API غير مكتملة."}, status=503
            )
        except WatiRequestError as exc:
            idem.release(scope, key)
            detail = (exc.response_text or str(exc) or "").strip()[:1000]
            status = exc.status_code or 502
            return request.make_json_response(
                {
                    "ok": False,
                    "message": f"WATI رفض الرسالة التفاعلية ({status}): {detail}",
                },
                status=status,
            )

        return request.make_json_response(
            {
                "ok": True,
                "accepted": True,
                "message": "تم قبول الرسالة التفاعلية في WATI ✅",
            },
            status=200,
        )
