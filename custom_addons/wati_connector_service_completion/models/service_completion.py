from odoo import _, api, fields, models
from odoo.exceptions import UserError


class WatiServiceCompletionTask(models.Model):
    _name = "wati.service.completion.task"
    _description = "Service Completion Task"
    _inherit = ["portal.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        string="Reference",
        default=lambda self: _("New"),
        readonly=True,
        copy=False,
        tracking=True,
    )
    external_reference = fields.Char(string="External reference", tracking=True)
    service_name = fields.Char(string="Service", required=True, tracking=True)
    customer_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        tracking=True,
        ondelete="restrict",
    )
    assigned_user_id = fields.Many2one(
        "res.users",
        string="Driver / Technician",
        tracking=True,
        default=lambda self: self.env.user,
        ondelete="set null",
    )
    customer_mobile = fields.Char(
        string="Customer mobile",
        compute="_compute_customer_phones",
        readonly=True,
    )
    customer_phone = fields.Char(
        string="Customer phone",
        compute="_compute_customer_phones",
        readonly=True,
    )
    state = fields.Selection(
        [
            ("new", "New"),
            ("in_progress", "In Progress"),
            ("ready", "Ready for Confirmation"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="new",
        required=True,
        tracking=True,
        index=True,
    )
    started_at = fields.Datetime(string="Started at", readonly=True, tracking=True)
    completed_at = fields.Datetime(string="Completed at", readonly=True, tracking=True)
    location_url = fields.Char(string="Customer location URL")
    before_photo = fields.Image(
        string="Before photo",
        attachment=True,
        max_width=1920,
        max_height=1920,
    )
    completion_photo = fields.Image(
        string="Completion photo",
        attachment=True,
        max_width=1920,
        max_height=1920,
    )
    notes = fields.Html(string="Notes")

    @api.depends("customer_id")
    def _compute_customer_phones(self):
        for task in self:
            partner = task.customer_id
            if not partner:
                task.customer_mobile = False
                task.customer_phone = False
                continue
            mobile = partner["mobile"] if "mobile" in partner._fields else False
            phone = partner["phone"] if "phone" in partner._fields else False
            task.customer_mobile = mobile or phone or False
            task.customer_phone = phone or mobile or False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "wati.service.completion.task"
                ) or _("New")
        return super().create(vals_list)

    def write(self, vals):
        values = dict(vals)
        if values.get("state") == "in_progress" and "started_at" not in values:
            values["started_at"] = fields.Datetime.now()
        if values.get("state") == "completed" and "completed_at" not in values:
            values["completed_at"] = fields.Datetime.now()
        return super().write(values)

    def _compute_access_url(self):
        super()._compute_access_url()
        for task in self:
            task.access_url = f"/my/service-completions/{task.id}"

    def action_start(self):
        for task in self:
            if task.state == "new":
                task.write({"state": "in_progress"})
        return True

    def action_ready_for_confirmation(self):
        for task in self:
            if task.state in ("new", "in_progress"):
                values = {"state": "ready"}
                if not task.started_at:
                    values["started_at"] = fields.Datetime.now()
                task.write(values)
        return True

    def action_reset_to_progress(self):
        self.filtered(lambda task: task.state == "ready").write({"state": "in_progress"})
        return True

    def _active_otp_flow(self):
        self.ensure_one()
        flows = self.env["wati.otp.flow"].sudo().search(
            [
                ("active", "=", True),
                ("model_name", "=", self._name),
                ("trigger_method", "=", "manual"),
            ],
            order="sequence, id",
            limit=2,
        )
        if len(flows) > 1:
            raise UserError(
                _(
                    "More than one active Manual OTP Flow is configured for Service Completion Task. Keep one active flow for this test."
                )
            )
        return flows[:1]

    def _latest_otp_transaction(self, states=None):
        self.ensure_one()
        domain = [
            ("model_name", "=", self._name),
            ("res_id", "=", self.id),
        ]
        if states:
            domain.append(("state", "in", states))
        return self.env["wati.otp.transaction"].sudo().search(
            domain,
            order="create_date desc, id desc",
            limit=1,
        )
