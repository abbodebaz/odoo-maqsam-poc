"""Gate only the human inbox HTTP/JSON routes, not webhooks, OTP or automations."""
from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from . import assignment, customer_context, file_send, interactive_buttons, interactive_list, main, media, mini_inbox, templates


def _identity_error():
    return request.env.user._wati_inbox_identity_error()


def _blocked_http(error, status=403):
    return request.make_json_response(
        {"ok": False, "identity_error": error, "message": error}, status=status,
    )


def _blocked_mini(error):
    return {"ok": False, "identity_error": error, "message": error}


class WatiInboxIdentityController(main.WatiWebhookController):
    @http.route()
    def inbox(self, **kwargs):
        error = _identity_error()
        if error:
            return request.render("wati_connector.wati_inbox_identity_blocked", {
                "identity_error": error,
                "user_name": request.env.user.name or "Odoo",
            })
        return super().inbox(**kwargs)

    @http.route()
    def inbox_data(self, conversation_id=None, **kwargs):
        error = _identity_error()
        if error:
            return request.make_json_response({
                "ok": False, "identity_error": error, "message": error,
                "selected_id": False, "conversations": [], "messages": [],
            }, status=200)
        return super().inbox_data(conversation_id=conversation_id, **kwargs)

    @http.route()
    def inbox_send(self, *args, **kwargs):
        error = _identity_error()
        return _blocked_http(error) if error else super().inbox_send(*args, **kwargs)


class WatiMiniIdentityController(mini_inbox.WatiMiniInboxController):
    @http.route()
    def bootstrap(self):
        if not mini_inbox._mini_enabled():
            return super().bootstrap()
        error = _identity_error()
        if error:
            return {
                "enabled": True, "identity_error": error,
                "conversations": [], "unread_total": 0, "latest_inbound_id": 0,
                "full_inbox_url": "/wati/inbox",
            }
        return super().bootstrap()

    @http.route()
    def conversation(self, conversation_id=None):
        error = _identity_error()
        if error:
            return _blocked_mini(error)
        result = super().conversation(conversation_id=conversation_id)
        # Normal agents can receive other agents' conversations; the model
        # already enforces the assignment rules and records the audit log.
        if result.get("ok") and result.get("assignment"):
            owner = result["assignment"]
            owner["can_takeover"] = bool(not owner["assigned_to_me"] and not owner["is_unassigned"])
        return result

    @http.route()
    def assign(self, conversation_id=None, force=False):
        error = _identity_error()
        if error:
            return _blocked_mini(error)
        if not mini_inbox._mini_enabled():
            return {"ok": False, "message": "Quick conversations are disabled."}
        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0
        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return {"ok": False, "message": "The conversation does not exist."}
        user = request.env.user
        previous = conversation.assigned_user_id
        try:
            conversation.assign_to_odoo_user(user, force=bool(force))
        except UserError as exc:
            return {"ok": False, "message": str(exc)}
        conversation.invalidate_recordset(["assigned_user_id"])
        if conversation.assigned_user_id != user:
            return {"ok": False, "message": "Could not confirm the assignment. Refresh and retry."}
        return {
            "ok": True, "assigned_user_name": user.name,
            "message": "Conversation received ✅" if not previous else "The conversation has been moved to you ✅",
        }

    @http.route()
    def send(self, *args, **kwargs):
        error = _identity_error()
        return _blocked_mini(error) if error else super().send(*args, **kwargs)


class WatiAssignmentIdentityController(assignment.WatiAssignmentController):
    @http.route()
    def assignment(self, *args, **kwargs):
        error = _identity_error()
        return _blocked_http(error) if error else super().assignment(*args, **kwargs)

    @http.route()
    def assign_me(self, *args, **kwargs):
        error = _identity_error()
        return _blocked_http(error) if error else super().assign_me(*args, **kwargs)


class WatiMediaIdentityController(media.WatiMediaController):
    @http.route()
    def media_meta(self, *args, **kwargs):
        error = _identity_error()
        return _blocked_http(error) if error else super().media_meta(*args, **kwargs)

    @http.route()
    def media(self, *args, **kwargs):
        error = _identity_error()
        if error:
            return request.make_response("WATI Agent identity is not approved.", status=403, headers=[("Cache-Control", "no-store")])
        return super().media(*args, **kwargs)


class WatiFileIdentityController(file_send.WatiFileSendController):
    @http.route()
    def send_file(self, *args, **kwargs):
        error = _identity_error()
        return _blocked_http(error) if error else super().send_file(*args, **kwargs)


class WatiTemplateIdentityController(templates.WatiTemplateController):
    @http.route()
    def templates(self, *args, **kwargs):
        error = _identity_error()
        return _blocked_http(error) if error else super().templates(*args, **kwargs)

    @http.route()
    def send_template(self, *args, **kwargs):
        error = _identity_error()
        return _blocked_http(error) if error else super().send_template(*args, **kwargs)


class WatiButtonsIdentityController(interactive_buttons.WatiInteractiveButtonsController):
    @http.route()
    def send_buttons(self, *args, **kwargs):
        error = _identity_error()
        return _blocked_http(error) if error else super().send_buttons(*args, **kwargs)


class WatiListIdentityController(interactive_list.WatiInteractiveListController):
    @http.route()
    def send_list(self, *args, **kwargs):
        error = _identity_error()
        return _blocked_http(error) if error else super().send_list(*args, **kwargs)


class WatiCustomerIdentityController(customer_context.WatiCustomerContextController):
    @http.route()
    def customer_context(self, *args, **kwargs):
        error = _identity_error()
        return _blocked_http(error) if error else super().customer_context(*args, **kwargs)

    @http.route()
    def create_customer(self, *args, **kwargs):
        error = _identity_error()
        return _blocked_http(error) if error else super().create_customer(*args, **kwargs)

    @http.route()
    def create_ticket(self, *args, **kwargs):
        error = _identity_error()
        return _blocked_http(error) if error else super().create_ticket(*args, **kwargs)
