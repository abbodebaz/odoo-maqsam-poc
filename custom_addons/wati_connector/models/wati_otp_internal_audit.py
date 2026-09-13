from odoo import _, fields, models
from odoo.exceptions import UserError


class WatiOtpFlowInternalAudit(models.Model):
    _inherit = "wati.otp.flow"

    def _audit_trigger_snapshot(self, actual_source):
        self.ensure_one()
        if actual_source == "portal":
            return _("Portal action")
        if actual_source == "resend":
            return _("Resend")
        if actual_source == "hook" or self.trigger_method == "hook":
            return _("Integration hook · %s") % self.technical_key
        if self.trigger_method == "field" and self.trigger_field_id:
            field_label = self.trigger_field_id.field_description or self.trigger_field_id.name
            operator_label = dict(self._fields["trigger_operator"].selection).get(
                self.trigger_operator, self.trigger_operator
            )
            value = self.trigger_value or ""
            return f"{field_label} · {operator_label}" + (f" · {value}" if value else "")
        button_label = getattr(self, "manual_button_label", False) or _("Send OTP")
        return _("Manual action · %s") % button_label

    def request_otp(self, record, source="manual", resend_of=None):
        transaction = super().request_otp(record, source=source, resend_of=resend_of)
        requested_by_user_id = self.env.context.get("wati_requested_by_user_id")
        if transaction and requested_by_user_id:
            transaction.sudo().write({"requested_by_id": int(requested_by_user_id)})
        return transaction

    def action_request_for_records(self, records):
        requester_id = records.env.user.id if records else self.env.user.id
        return super(
            WatiOtpFlowInternalAudit,
            self.with_context(wati_requested_by_user_id=requester_id),
        ).action_request_for_records(records)


class WatiOtpTransactionInternalAudit(models.Model):
    _inherit = "wati.otp.transaction"

    source = fields.Selection(
        selection_add=[("portal", "Portal")],
        ondelete={"portal": "set default"},
    )
    audit_otp_code = fields.Char(
        string="OTP Code",
        readonly=True,
        copy=False,
        groups="wati_connector.group_wati_admin",
        help="Exact OTP retained for Bayt Alebaa internal audit and support traceability.",
    )
    recipient_phone = fields.Char(
        string="Recipient number",
        readonly=True,
        copy=False,
        groups="wati_connector.group_wati_admin",
    )
    application_name = fields.Char(string="Application", readonly=True, copy=False)
    record_type_name = fields.Char(string="Record type", readonly=True, copy=False)
    flow_name_snapshot = fields.Char(string="Flow at send time", readonly=True, copy=False)
    trigger_snapshot = fields.Char(string="Trigger details", readonly=True, copy=False)
    recipient_source_snapshot = fields.Char(
        string="Recipient source", readonly=True, copy=False
    )

    def _send_generated_code(self, code, phone):
        self.ensure_one()
        result = super()._send_generated_code(code, phone)
        if result:
            flow = self.flow_id
            app_name = flow.app_menu_id.name if flow.app_menu_id else ""
            record_type = flow.model_id.name if flow.model_id else self.model_name
            recipient_source = (
                flow.recipient_summary
                or flow.recipient_path
                or dict(flow._fields["recipient_mode"].selection).get(
                    flow.recipient_mode, flow.recipient_mode
                )
            )
            self.sudo().write(
                {
                    "audit_otp_code": str(code or ""),
                    "recipient_phone": str(phone or ""),
                    "application_name": app_name,
                    "record_type_name": record_type,
                    "flow_name_snapshot": flow.name,
                    "trigger_snapshot": flow._audit_trigger_snapshot(self.source),
                    "recipient_source_snapshot": recipient_source or "",
                }
            )
        return result

    def verify_code(self, code):
        ok, message = super().verify_code(code)
        verified_by_user_id = self.env.context.get("wati_verified_by_user_id")
        if ok and verified_by_user_id:
            self.sudo().write({"verified_by_id": int(verified_by_user_id)})
        return ok, message

    def action_open_source_record(self):
        self.ensure_one()
        record = self._get_record()
        if not record:
            raise UserError(_("The source record no longer exists."))
        return {
            "type": "ir.actions.act_window",
            "name": record.display_name,
            "res_model": record._name,
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
        }
