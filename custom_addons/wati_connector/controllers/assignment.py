from odoo import http
from odoo.exceptions import UserError
from odoo.http import request


class WatiAssignmentController(http.Controller):

    @http.route(
        "/wati/inbox/assignment",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def assignment(self, conversation_id=None, **kwargs):
        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0

        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return request.make_json_response({"ok": False, "message": "المحادثة غير موجودة."}, status=404)

        current_user = request.env.user
        assigned = conversation.assigned_user_id
        can_supervise = current_user._wati_can_supervise()
        return request.make_json_response(
            {
                "ok": True,
                "conversation_id": conversation.id,
                "assigned_user_id": assigned.id if assigned else False,
                "assigned_user_name": assigned.name if assigned else "",
                "assigned_to_me": bool(assigned and assigned == current_user),
                "is_unassigned": not bool(assigned),
                "can_takeover": bool(assigned and assigned != current_user and can_supervise),
                "current_user_id": current_user.id,
                "current_user_name": current_user.name,
                "wati_email": current_user._wati_email(),
                "is_supervisor": can_supervise,
                "is_admin": current_user.has_group("base.group_system"),
            },
            status=200,
        )

    @http.route(
        "/wati/inbox/assign-me",
        type="http",
        auth="user",
        methods=["POST"],
    )
    def assign_me(self, conversation_id=None, force=None, **kwargs):
        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0

        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return request.make_json_response({"ok": False, "message": "المحادثة غير موجودة."}, status=404)

        current_user = request.env.user
        previous_user = conversation.assigned_user_id
        takeover_requested = str(force or "").lower() in ("1", "true", "yes")
        if takeover_requested and previous_user and previous_user != current_user and not current_user._wati_can_supervise():
            return request.make_json_response(
                {"ok": False, "message": "أخذ محادثة موظف آخر متاح فقط لمشرف WATI أو Administrator."},
                status=403,
            )

        try:
            conversation.assign_to_odoo_user(current_user, force=takeover_requested)
        except UserError as exc:
            return request.make_json_response({"ok": False, "message": str(exc)}, status=409)

        # Re-read after the locked assignment transaction logic.
        conversation.invalidate_recordset(["assigned_user_id"])
        if conversation.assigned_user_id != current_user:
            return request.make_json_response(
                {"ok": False, "message": "تعذر تثبيت إسناد المحادثة. حدّث الصفحة وحاول مرة أخرى."},
                status=409,
            )

        if previous_user and previous_user != current_user:
            message = f"تم نقل المحادثة من {previous_user.name} إلى {current_user.name} ✅"
        else:
            message = f"تم إسناد المحادثة إلى {current_user.name} ✅"

        return request.make_json_response(
            {
                "ok": True,
                "message": message,
                "assigned_user_id": current_user.id,
                "assigned_user_name": current_user.name,
                "previous_user_id": previous_user.id if previous_user else False,
                "previous_user_name": previous_user.name if previous_user else "",
            },
            status=200,
        )
