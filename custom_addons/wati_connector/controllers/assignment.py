from odoo import http
from odoo.exceptions import UserError
from odoo.http import request


class WatiAssignmentController(http.Controller):

    @http.route("/wati/inbox/assignment", type="http", auth="user", methods=["GET"], csrf=False)
    def assignment(self, conversation_id=None, **kwargs):
        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0
        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return request.make_json_response({"ok": False, "message": "The conversation does not exist."}, status=404)
        current_user = request.env.user
        assigned = conversation.assigned_user_id
        return request.make_json_response({
            "ok": True,
            "conversation_id": conversation.id,
            "assigned_user_id": assigned.id if assigned else False,
            "assigned_user_name": assigned.name if assigned else "",
            "assigned_to_me": bool(assigned and assigned == current_user),
            "is_unassigned": not bool(assigned),
            "can_takeover": bool(assigned and assigned != current_user and current_user._wati_email()),
            "current_user_id": current_user.id,
            "current_user_name": current_user.name,
            "wati_email": current_user._wati_email(),
            "is_supervisor": current_user._wati_can_supervise(),
            "is_admin": current_user.has_group("base.group_system"),
        }, status=200)

    @http.route("/wati/inbox/assign-me", type="http", auth="user", methods=["POST"])
    def assign_me(self, conversation_id=None, force=None, **kwargs):
        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0
        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return request.make_json_response({"ok": False, "message": "The conversation does not exist."}, status=404)
        current_user = request.env.user
        try:
            conversation.assign_to_odoo_user(current_user)
        except UserError as exc:
            return request.make_json_response({"ok": False, "message": str(exc)}, status=409)
        conversation.invalidate_recordset(["assigned_user_id"])
        if conversation.assigned_user_id != current_user:
            return request.make_json_response({"ok": False, "message": "Could not confirm the assignment. Refresh and retry."}, status=409)
        return request.make_json_response({
            "ok": True,
            "message": f"The conversation is now assigned to {current_user.name}.",
            "assigned_user_id": current_user.id,
            "assigned_user_name": current_user.name,
        }, status=200)
