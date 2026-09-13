from odoo import _, http
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import UserError
from odoo.http import request


class ServiceCompletionPortal(CustomerPortal):
    def _task_domain(self):
        user = request.env.user
        if user.has_group("base.group_user"):
            return []
        partner = user.partner_id.commercial_partner_id
        return [
            "|",
            ("assigned_user_id", "=", user.id),
            ("customer_id", "child_of", partner.id),
        ]

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if "service_completion_count" in counters:
            values["service_completion_count"] = request.env[
                "wati.service.completion.task"
            ].search_count(self._task_domain())
        return values

    def _get_task(self, task_id):
        domain = [("id", "=", int(task_id))] + self._task_domain()
        return request.env["wati.service.completion.task"].search(domain, limit=1)

    def _set_flash(self, message, level="info"):
        request.session["service_completion_flash"] = {
            "message": str(message),
            "level": level,
        }

    def _pop_flash(self):
        return request.session.pop("service_completion_flash", None)

    def _detail_values(self, task):
        flow = request.env["wati.otp.flow"].sudo().browse()
        flow_error = False
        try:
            flow = task._active_otp_flow()
        except UserError as exc:
            flow_error = str(exc)

        transaction = task._latest_otp_transaction()
        waiting_transaction = (
            transaction if transaction and transaction.state == "sent" else False
        )
        verified_transaction = (
            transaction if transaction and transaction.state == "verified" else False
        )
        can_send = bool(
            flow and task.state != "completed" and not verified_transaction
        )
        if can_send and flow.manual_condition_field_id:
            try:
                can_send = flow._manual_condition_matches(task.sudo())
            except Exception:
                can_send = False

        return {
            "page_name": "service_completion_task",
            "task": task,
            "otp_flow": flow,
            "flow_error": flow_error,
            "otp_transaction": transaction,
            "waiting_transaction": waiting_transaction,
            "verified_transaction": verified_transaction,
            "can_send_otp": can_send,
            "flash": self._pop_flash(),
        }

    @http.route(
        ["/my/service-completions", "/my/service-completions/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_service_completions(self, page=1, **kwargs):
        Task = request.env["wati.service.completion.task"]
        domain = self._task_domain()
        total = Task.search_count(domain)
        pager = portal_pager(
            url="/my/service-completions",
            total=total,
            page=page,
            step=20,
        )
        tasks = Task.search(
            domain,
            order="create_date desc, id desc",
            limit=20,
            offset=pager["offset"],
        )
        return request.render(
            "wati_connector_service_completion.portal_service_completion_list",
            {
                "page_name": "service_completion_list",
                "tasks": tasks,
                "pager": pager,
            },
        )

    @http.route(
        "/my/service-completions/<int:task_id>",
        type="http",
        auth="user",
        website=True,
    )
    def portal_service_completion_detail(self, task_id, **kwargs):
        task = self._get_task(task_id)
        if not task:
            return request.not_found()
        return request.render(
            "wati_connector_service_completion.portal_service_completion_detail",
            self._detail_values(task),
        )

    @http.route(
        "/my/service-completions/<int:task_id>/otp/send",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_service_completion_send_otp(self, task_id, **post):
        task = self._get_task(task_id)
        if not task:
            return request.not_found()
        try:
            flow = task._active_otp_flow()
            if not flow:
                raise UserError(
                    _(
                        "Create and activate one Manual OTP Flow for Service Completion Task first."
                    )
                )
            flow.sudo().action_request_for_records(task.sudo())
            transaction = task._latest_otp_transaction()
            if not transaction or transaction.state != "sent":
                detail = transaction.error_message if transaction else False
                raise UserError(detail or _("The OTP could not be sent."))
            self._set_flash(_("OTP sent to the customer via WhatsApp."), "success")
        except UserError as exc:
            self._set_flash(str(exc), "danger")
        return request.redirect(f"/my/service-completions/{task.id}")

    @http.route(
        "/my/service-completions/<int:task_id>/otp/verify",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_service_completion_verify_otp(self, task_id, **post):
        task = self._get_task(task_id)
        if not task:
            return request.not_found()
        code = (post.get("otp_code") or "").strip()
        if not code.isdigit():
            self._set_flash(_("Enter the numeric OTP sent to the customer."), "danger")
            return request.redirect(f"/my/service-completions/{task.id}")

        transaction = task._latest_otp_transaction(states=["sent"])
        if not transaction:
            self._set_flash(_("There is no OTP waiting for verification."), "warning")
            return request.redirect(f"/my/service-completions/{task.id}")

        ok, message = transaction.sudo().verify_code(code)
        self._set_flash(message, "success" if ok else "danger")
        return request.redirect(f"/my/service-completions/{task.id}")

    @http.route(
        "/my/service-completions/<int:task_id>/otp/resend",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_service_completion_resend_otp(self, task_id, **post):
        task = self._get_task(task_id)
        if not task:
            return request.not_found()
        transaction = task._latest_otp_transaction(states=["sent"])
        try:
            if transaction:
                transaction.sudo().action_resend()
            else:
                flow = task._active_otp_flow()
                if not flow:
                    raise UserError(_("No active Manual OTP Flow is configured."))
                flow.sudo().action_request_for_records(task.sudo())
            self._set_flash(_("A new OTP was sent to the customer."), "success")
        except UserError as exc:
            self._set_flash(str(exc), "danger")
        return request.redirect(f"/my/service-completions/{task.id}")
