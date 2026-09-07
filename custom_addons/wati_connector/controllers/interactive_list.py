import json
import threading
import time

from odoo import http
from odoo.http import request

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError


_LIST_GUARD = {}
_LIST_GUARD_LOCK = threading.Lock()
_LIST_GUARD_TTL = 180.0


def _clean(value):
    return str(value or "").strip()


def _reserve_guard(user_id, request_id):
    request_id = _clean(request_id)
    if not request_id:
        return "", True
    now = time.monotonic()
    key = f"{user_id}:{request_id}"
    with _LIST_GUARD_LOCK:
        expired = [item for item, created in _LIST_GUARD.items() if now - created > _LIST_GUARD_TTL]
        for item in expired:
            _LIST_GUARD.pop(item, None)
        if key in _LIST_GUARD:
            return key, False
        _LIST_GUARD[key] = now
    return key, True


def _release_guard(key):
    if not key:
        return
    with _LIST_GUARD_LOCK:
        _LIST_GUARD.pop(key, None)


def _parse_sections(value):
    try:
        raw = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(raw, list):
        return []

    sections = []
    for raw_section in raw:
        if not isinstance(raw_section, dict):
            continue
        section_title = _clean(raw_section.get("title"))
        raw_rows = raw_section.get("rows")
        if not isinstance(raw_rows, list):
            continue
        rows = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                continue
            title = _clean(raw_row.get("title"))
            description = _clean(raw_row.get("description"))
            if title:
                rows.append({"title": title, "description": description})
        if rows:
            sections.append({"title": section_title, "rows": rows})
    return sections


class WatiInteractiveListController(http.Controller):

    @http.route(
        "/wati/inbox/send-list",
        type="http",
        auth="user",
        methods=["POST"],
    )
    def send_list(
        self,
        conversation_id=None,
        header=None,
        body=None,
        footer=None,
        button_text=None,
        sections_json=None,
        request_id=None,
        **kwargs,
    ):
        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0

        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return request.make_json_response({"ok": False, "message": "المحادثة غير موجودة."}, status=404)

        current_user = request.env.user
        if not conversation.assigned_user_id:
            return request.make_json_response(
                {"ok": False, "message": "استلم المحادثة أولًا قبل إرسال قائمة تفاعلية."},
                status=409,
            )
        if conversation.assigned_user_id != current_user and not current_user.has_group("base.group_system"):
            return request.make_json_response(
                {
                    "ok": False,
                    "message": f"المحادثة مستلمة بواسطة {conversation.assigned_user_id.name}. استخدم أخذ المحادثة أولًا.",
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
        button_text = _clean(button_text)
        sections = _parse_sections(sections_json)

        if not body:
            return request.make_json_response({"ok": False, "message": "اكتب نص الرسالة أولًا."}, status=400)
        if not button_text:
            return request.make_json_response({"ok": False, "message": "اكتب نص زر فتح القائمة."}, status=400)
        if len(header) > 60:
            return request.make_json_response({"ok": False, "message": "العنوان يجب ألا يتجاوز 60 حرفًا."}, status=400)
        if len(body) > 1024:
            return request.make_json_response({"ok": False, "message": "نص الرسالة يجب ألا يتجاوز 1024 حرفًا."}, status=400)
        if len(footer) > 60:
            return request.make_json_response({"ok": False, "message": "التذييل يجب ألا يتجاوز 60 حرفًا."}, status=400)
        if len(button_text) > 20:
            return request.make_json_response({"ok": False, "message": "نص زر القائمة يجب ألا يتجاوز 20 حرفًا."}, status=400)
        if not sections:
            return request.make_json_response({"ok": False, "message": "أضف قسمًا واحدًا على الأقل وخيارًا واحدًا."}, status=400)
        if len(sections) > 10:
            return request.make_json_response({"ok": False, "message": "الحد الأقصى 10 أقسام."}, status=400)

        total_rows = sum(len(section["rows"]) for section in sections)
        if not 1 <= total_rows <= 10:
            return request.make_json_response({"ok": False, "message": "عدد الخيارات يجب أن يكون من 1 إلى 10."}, status=400)

        if len(sections) > 1 and any(not section["title"] for section in sections):
            return request.make_json_response(
                {"ok": False, "message": "عند استخدام أكثر من قسم، اكتب عنوانًا لكل قسم."},
                status=400,
            )
        for section in sections:
            if len(section["title"]) > 24:
                return request.make_json_response({"ok": False, "message": "عنوان القسم يجب ألا يتجاوز 24 حرفًا."}, status=400)
            for row in section["rows"]:
                if len(row["title"]) > 24:
                    return request.make_json_response({"ok": False, "message": "عنوان الخيار يجب ألا يتجاوز 24 حرفًا."}, status=400)
                if len(row["description"]) > 72:
                    return request.make_json_response({"ok": False, "message": "وصف الخيار يجب ألا يتجاوز 72 حرفًا."}, status=400)

        titles = [row["title"].casefold() for section in sections for row in section["rows"]]
        if len(set(titles)) != len(titles):
            return request.make_json_response(
                {"ok": False, "message": "اجعل عنوان كل خيار مختلفًا حتى يكون الرد واضحًا داخل Odoo."},
                status=400,
            )

        guard_key, reserved = _reserve_guard(current_user.id, request_id)
        if not reserved:
            return request.make_json_response(
                {"ok": True, "duplicate_suppressed": True, "message": "تم تجاهل إعادة إرسال مكررة."},
                status=200,
            )

        payload = {
            "body": body,
            "buttonText": button_text,
            "sections": sections,
        }
        if header:
            payload["header"] = header
        if footer:
            payload["footer"] = footer

        try:
            WatiClient(request.env).send_interactive_list(conversation.wa_id, payload)
        except WatiConfigurationError:
            _release_guard(guard_key)
            return request.make_json_response({"ok": False, "message": "إعدادات WATI API غير مكتملة."}, status=503)
        except WatiRequestError as exc:
            _release_guard(guard_key)
            detail = (exc.response_text or str(exc) or "").strip()[:1000]
            status = exc.status_code or 502
            return request.make_json_response(
                {"ok": False, "message": f"WATI رفض القائمة ({status}): {detail}"},
                status=status,
            )

        return request.make_json_response(
            {
                "ok": True,
                "accepted": True,
                "message": "تم قبول القائمة التفاعلية في WATI ✅",
            },
            status=200,
        )
