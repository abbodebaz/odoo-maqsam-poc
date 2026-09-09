from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request

from ..services.idempotency import WatiIdempotency
from ..services.media import WatiMediaService


def _config_flag(name, default=False):
    value = request.env["ir.config_parameter"].sudo().get_param(
        name, "True" if default else "False"
    )
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _mini_access_allowed():
    user = request.env.user
    return bool(
        user.has_group("wati_connector.group_wati_user")
        or user.has_group("base.group_system")
    )


def _mini_enabled():
    return _mini_access_allowed() and _config_flag(
        "wati_connector.enable_mini_inbox", default=False
    )


def _conversation_title(conversation):
    partner = conversation.partner_id
    return (
        partner.display_name
        if partner
        else conversation.name
        or conversation.sender_name
        or conversation.wa_id
        or "WhatsApp"
    )


def _conversation_identity(conversation):
    digits = "".join(
        character
        for character in str(conversation.wa_id or "")
        if character.isdigit()
    )
    return digits or f"conversation:{conversation.id}"


def _dedupe_conversations(conversations, limit=None):
    """Keep only the newest visible row for each WhatsApp recipient.

    WATI can briefly emit a contact stub before the real conversation callback. The
    ingestion layer now binds those callbacks to one record, but this defensive view
    guard also prevents legacy/race duplicates from appearing to service agents.
    """
    seen = set()
    ids = []
    for conversation in conversations:
        identity = _conversation_identity(conversation)
        if identity in seen:
            continue
        seen.add(identity)
        ids.append(conversation.id)
        if limit and len(ids) >= limit:
            break
    return request.env["wati.conversation"].browse(ids)


def _conversation_row(conversation, current_user):
    assigned = conversation.assigned_user_id
    return {
        "id": conversation.id,
        "name": _conversation_title(conversation),
        "wa_id": conversation.wa_id or "",
        "last_message": conversation.last_message or "",
        "last_message_at": fields.Datetime.to_string(conversation.last_message_at)
        if conversation.last_message_at
        else "",
        "unread_count": conversation.unread_count or 0,
        "assigned_user_name": assigned.name if assigned else "",
        "assigned_to_me": bool(assigned and assigned == current_user),
        "is_unassigned": not bool(assigned),
    }


def _message_rows(conversation):
    latest = request.env["wati.message"].search(
        [("conversation_id", "=", conversation.id)],
        order="received_at desc, id desc",
        limit=80,
    )
    messages = latest.sorted(
        key=lambda message: (message.received_at or fields.Datetime.now(), message.id)
    )
    rows = []
    for message in messages:
        descriptor = WatiMediaService.describe(message)
        raw_text = message.text or ""
        display_text = raw_text
        if (
            descriptor["has_media"]
            and descriptor["media_path"]
            and raw_text.strip() == descriptor["media_path"]
        ):
            display_text = ""

        rows.append(
            {
                "id": message.id,
                "direction": message.direction or "inbound",
                "text": display_text,
                "message_type": message.message_type or "text",
                "status": message.status or "",
                "received_at": fields.Datetime.to_string(message.received_at)
                if message.received_at
                else "",
                "has_media": bool(descriptor["has_media"]),
                "media_type": descriptor["type"],
                "file_name": descriptor["file_name"],
                "media_url": f"/wati/inbox/media/{message.id}"
                if descriptor["has_media"]
                else "",
            }
        )
    return rows


class WatiMiniInboxController(http.Controller):

    @http.route("/wati/mini/bootstrap", type="jsonrpc", auth="user")
    def bootstrap(self):
        if not _mini_enabled():
            return {"enabled": False}

        candidates = request.env["wati.conversation"].search(
            [], order="last_message_at desc, id desc", limit=90
        )
        conversations = _dedupe_conversations(candidates, limit=30)
        latest_inbound = request.env["wati.message"].search(
            [("direction", "=", "inbound")], order="id desc", limit=1
        )
        current_user = request.env.user
        rows = [_conversation_row(conversation, current_user) for conversation in conversations]
        return {
            "enabled": True,
            "unread_total": sum(row["unread_count"] for row in rows),
            "latest_inbound_id": latest_inbound.id if latest_inbound else 0,
            "conversations": rows,
            "full_inbox_url": "/wati/inbox",
            "csrf_token": request.csrf_token(),
        }

    @http.route("/wati/mini/conversation", type="jsonrpc", auth="user")
    def conversation(self, conversation_id=None):
        if not _mini_enabled():
            return {"ok": False, "message": "المحادثات السريعة غير مفعلة."}

        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0

        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return {"ok": False, "message": "المحادثة غير موجودة."}

        current_user = request.env.user
        assigned = conversation.assigned_user_id
        can_supervise = current_user._wati_can_supervise()
        return {
            "ok": True,
            "conversation": _conversation_row(conversation, current_user),
            "messages": _message_rows(conversation),
            "assignment": {
                "assigned_to_me": bool(assigned and assigned == current_user),
                "is_unassigned": not bool(assigned),
                "assigned_user_name": assigned.name if assigned else "",
                "can_takeover": bool(
                    assigned and assigned != current_user and can_supervise
                ),
                "wati_email": current_user._wati_email(),
            },
        }

    @http.route("/wati/mini/assign", type="jsonrpc", auth="user")
    def assign(self, conversation_id=None, force=False):
        if not _mini_enabled():
            return {"ok": False, "message": "المحادثات السريعة غير مفعلة."}

        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0

        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return {"ok": False, "message": "المحادثة غير موجودة."}

        current_user = request.env.user
        previous_user = conversation.assigned_user_id
        takeover_requested = bool(force)
        if (
            takeover_requested
            and previous_user
            and previous_user != current_user
            and not current_user._wati_can_supervise()
        ):
            return {
                "ok": False,
                "message": "نقل محادثة موظف آخر متاح فقط لمشرف WATI أو Administrator.",
            }

        try:
            conversation.assign_to_odoo_user(
                current_user, force=takeover_requested
            )
        except UserError as exc:
            return {"ok": False, "message": str(exc)}

        conversation.invalidate_recordset(["assigned_user_id"])
        if conversation.assigned_user_id != current_user:
            return {
                "ok": False,
                "message": "تعذر تثبيت إسناد المحادثة. حاول مرة أخرى.",
            }

        return {
            "ok": True,
            "assigned_user_name": current_user.name,
            "message": "تم استلام المحادثة ✅"
            if not previous_user
            else "تم نقل المحادثة إليك ✅",
        }

    @http.route("/wati/mini/send", type="jsonrpc", auth="user")
    def send(self, conversation_id=None, message=None, request_id=None):
        if not _mini_enabled():
            return {"ok": False, "message": "المحادثات السريعة غير مفعلة."}

        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0

        text = (message or "").strip()
        if not text:
            return {"ok": False, "message": "اكتب الرسالة أولًا."}

        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return {"ok": False, "message": "المحادثة غير موجودة."}

        idem = WatiIdempotency(request.env)
        scope = f"outbound:mini-text:user:{request.env.user.id}"
        key = (request_id or "").strip() or idem.digest(conversation_id, text)
        if not idem.acquire_durable(scope, key, ttl_seconds=120):
            return {
                "ok": True,
                "message": "تم تجاهل إعادة إرسال مكررة.",
                "duplicate_suppressed": True,
            }

        try:
            conversation.send_session_message(text)
        except UserError as exc:
            # Known business/provider rejection happens before WATI accepts the
            # message, so a deliberate retry should remain possible.
            idem.release_durable(scope, key)
            return {"ok": False, "message": str(exc)}
        except Exception:
            # Fail closed. WATI may already have accepted the message before a
            # local serialization/database error. Keeping the durable key makes
            # Odoo's automatic transaction retry a no-op instead of a 2nd send.
            raise

        return {"ok": True, "message": "تم إرسال الرسالة إلى WATI ✅"}
