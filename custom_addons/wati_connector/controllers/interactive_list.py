import json

from odoo import http
from odoo.http import request

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.idempotency import WatiIdempotency


def _clean(value):
    return str(value or "").strip()


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

    @http.route("/wati/inbox/send-list", type="http", auth="user", methods=["POST"])
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
            return request.make_json_response({"ok": False, "message": "The conversation does not exist."}, status=404)

        current_user = request.env.user
        if not conversation.assigned_user_id:
            return request.make_json_response({"ok": False, "message": "Receive the chat first before sending an interactive menu."}, status=409)
        if conversation.assigned_user_id != current_user:
            return request.make_json_response(
                {"ok": False, "message": f"Conversation received by {conversation.assigned_user_id.name}. Move the conversation to you first."},
                status=409,
            )
        if not conversation.wa_id:
            return request.make_json_response({"ok": False, "message": "There is no number WhatsApp for this conversation."}, status=400)

        header = _clean(header)
        body = _clean(body)
        footer = _clean(footer)
        button_text = _clean(button_text)
        sections = _parse_sections(sections_json)
        if not body:
            return request.make_json_response({"ok": False, "message": "Write the body of the message first."}, status=400)
        if not button_text:
            return request.make_json_response({"ok": False, "message": "Type the text for the Open Menu button."}, status=400)
        if len(header) > 60:
            return request.make_json_response({"ok": False, "message": "The address must not exceed 60 A letter."}, status=400)
        if len(body) > 1024:
            return request.make_json_response({"ok": False, "message": "The text of the message must not exceed 1024 A letter."}, status=400)
        if len(footer) > 60:
            return request.make_json_response({"ok": False, "message": "The footer must not exceed 60 A letter."}, status=400)
        if len(button_text) > 20:
            return request.make_json_response({"ok": False, "message": "Menu button text must not exceed 20 A letter."}, status=400)
        if not sections:
            return request.make_json_response({"ok": False, "message": "Add at least one section and one option."}, status=400)
        if len(sections) > 10:
            return request.make_json_response({"ok": False, "message": "max 10 Sections."}, status=400)
        total_rows = sum(len(section["rows"]) for section in sections)
        if not 1 <= total_rows <= 10:
            return request.make_json_response({"ok": False, "message": "The number of options should be from 1 To 10."}, status=400)
        if len(sections) > 1 and any(not section["title"] for section in sections):
            return request.make_json_response({"ok": False, "message": "When using more than one section, write a title for each section."}, status=400)
        for section in sections:
            if len(section["title"]) > 24:
                return request.make_json_response({"ok": False, "message": "The section title must not exceed 24 A letter."}, status=400)
            for row in section["rows"]:
                if len(row["title"]) > 24:
                    return request.make_json_response({"ok": False, "message": "The option title must not exceed 24 A letter."}, status=400)
                if len(row["description"]) > 72:
                    return request.make_json_response({"ok": False, "message": "Option description must not exceed 72 A letter."}, status=400)
        titles = [row["title"].casefold() for section in sections for row in section["rows"]]
        if len(set(titles)) != len(titles):
            return request.make_json_response({"ok": False, "message": "Make the title of each option different so that the response is clear within Odoo."}, status=400)

        payload = {"body": body, "buttonText": button_text, "sections": sections}
        if header:
            payload["header"] = header
        if footer:
            payload["footer"] = footer

        idem = WatiIdempotency(request.env)
        scope = f"outbound:list:user:{current_user.id}"
        key = (request_id or "").strip() or idem.digest(conversation.id, header, body, footer, button_text, sections_json or "")
        if not idem.acquire(scope, key, ttl_seconds=180):
            return request.make_json_response({"ok": True, "duplicate_suppressed": True, "message": "Duplicate resubmission was ignored."}, status=200)

        try:
            WatiClient(request.env).send_interactive_list(conversation.wa_id, payload)
        except WatiConfigurationError:
            idem.release(scope, key)
            return request.make_json_response({"ok": False, "message": "Settings WATI API Incomplete."}, status=503)
        except WatiRequestError as exc:
            idem.release(scope, key)
            detail = (exc.response_text or str(exc) or "").strip()[:1000]
            status = exc.status_code or 502
            return request.make_json_response({"ok": False, "message": f"WATI Reject list ({status}): {detail}"}, status=status)

        return request.make_json_response({"ok": True, "accepted": True, "message": "Interactive menu accepted in WATI ✅"}, status=200)
