from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_mobile = fields.Char(string="Alternate Mobile")
    x_sap_customer_no = fields.Char(string="SAP Customer No.")


class CrmLead(models.Model):
    _inherit = "crm.lead"

    approximate_budget = fields.Monetary(currency_field="budget_currency_id")
    budget_currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    kitchen_reception_visible = fields.Boolean(default=False)
    project_type = fields.Selection([
        ("new_kitchen", "New Kitchen"),
        ("renovation", "Renovation"),
        ("service", "Service"),
    ])
    followup_message = fields.Text()
    seriousness_level = fields.Selection([
        ("low", "Low"), ("medium", "Medium"), ("high", "High")
    ])
    purchase_decision = fields.Selection([
        ("customer", "Customer"), ("family", "Family"), ("other", "Other")
    ])
    measurement_required = fields.Boolean()
    measurement_appointment = fields.Datetime()


class OperationsOperationCase(models.Model):
    _name = "operations.operation.case"
    _description = "Bayt Alebaa Operation Case Simulator"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, default="New")
    partner_id = fields.Many2one("res.partner", tracking=True)
    invoice_id = fields.Many2one("account.move")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    current_stage = fields.Char(default="Ready", tracking=True)
    current_step_name = fields.Char()
    state = fields.Selection([
        ("ready", "Ready"),
        ("in_progress", "In Progress"),
        ("done", "Done"),
        ("cancelled", "Cancelled"),
    ], default="ready", tracking=True)
    service_id = fields.Char()
    service_family_id = fields.Char()
    routing_name = fields.Char()
    questionnaire_complete = fields.Boolean()
    needs_attention = fields.Boolean()
    attention_message = fields.Char()
    task_ids = fields.One2many("project.task", "operation_case_id")
    question_answer_ids = fields.One2many("operations.question.case.answer", "operation_case_id")
    workflow_instance_ids = fields.One2many("operations.workflow.instance", "operation_case_id")


class ProjectTask(models.Model):
    _inherit = "project.task"

    operation_case_id = fields.Many2one("operations.operation.case")
    customer_mobile = fields.Char()
    hcos_workflow_node_state = fields.Selection([
        ("pending", "Pending"), ("active", "Active"), ("done", "Done"), ("blocked", "Blocked")
    ])


class OperationsWorkflowInstance(models.Model):
    _name = "operations.workflow.instance"
    _description = "Bayt Alebaa Workflow Instance Simulator"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True)
    operation_case_id = fields.Many2one("operations.operation.case", required=True, ondelete="cascade")
    invoice_id = fields.Many2one("account.move")
    scenario_source = fields.Selection([
        ("family_match", "Service Family Match"),
        ("manual", "Manual"),
    ], default="family_match")
    state = fields.Selection([
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("exception", "Exception"),
        ("cancelled", "Cancelled"),
    ], default="in_progress", tracking=True)
    progress = fields.Float(default=0)
    blocked_reason = fields.Char()
    idempotency_key = fields.Char()


class OperationsQuestion(models.Model):
    _name = "operations.question"
    _description = "Operation Question"
    name = fields.Char(required=True)


class OperationsQuestionAnswerOption(models.Model):
    _name = "operations.question.answer"
    _description = "Operation Question Answer Option"
    name = fields.Char(required=True)
    question_id = fields.Many2one("operations.question", required=True, ondelete="cascade")


class OperationsQuestionCaseAnswer(models.Model):
    _name = "operations.question.case.answer"
    _description = "Operation Case Question Answer"

    operation_case_id = fields.Many2one("operations.operation.case", required=True, ondelete="cascade")
    question_id = fields.Many2one("operations.question", required=True)
    answer_id = fields.Many2one("operations.question.answer", required=True)


class DecorMeasurement(models.Model):
    _name = "hcos.task.form.decor.measurement"
    _description = "Decor Measurement Form Simulator"

    task_id = fields.Many2one("project.task", required=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    partner_id = fields.Many2one("res.partner")
    customer_name = fields.Many2one("res.partner")
    customer_mobile = fields.Char()
    customer_location = fields.Char()
    visit_datetime = fields.Datetime()
    site_readiness = fields.Selection([("ready", "Ready"), ("not_ready", "Not Ready")], default="ready")
    state = fields.Selection([("draft", "Draft"), ("otp_sent", "OTP Sent"), ("verified", "Verified")], default="draft", tracking=True)
    status = fields.Selection([("draft", "Draft"), ("in_progress", "In Progress"), ("done", "Done")], default="draft")
    otp_verified = fields.Boolean()
    note = fields.Text()


class InstallationForm(models.Model):
    _name = "hcos.task.form.installation"
    _description = "Installation Form Simulator"

    request_number = fields.Char(required=True, default="New")
    task_id = fields.Many2one("project.task", required=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    partner_id = fields.Many2one("res.partner")
    customer_name = fields.Many2one("res.partner")
    customer_mobile = fields.Char()
    customer_location = fields.Char()
    installation_datetime = fields.Datetime()
    installation_status = fields.Selection([("scheduled", "Scheduled"), ("in_progress", "In Progress"), ("completed", "Completed")], default="scheduled", tracking=True)
    state = fields.Selection([("draft", "Draft"), ("otp_sent", "OTP Sent"), ("verified", "Verified")], default="draft", tracking=True)
    status = fields.Selection([("draft", "Draft"), ("in_progress", "In Progress"), ("done", "Done")], default="draft")
    otp_verified = fields.Boolean()
    note = fields.Text()


class HelpdeskStage(models.Model):
    _name = "helpdesk.stage"
    _description = "Helpdesk Stage Simulator"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)


class HelpdeskTicket(models.Model):
    _name = "helpdesk.ticket"
    _description = "Helpdesk Ticket Simulator"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    partner_id = fields.Many2one("res.partner")
    partner_name = fields.Char()
    partner_phone = fields.Char()
    partner_email = fields.Char()
    stage_id = fields.Many2one("helpdesk.stage", tracking=True)
    priority = fields.Selection([("0", "Normal"), ("1", "Low"), ("2", "High"), ("3", "Urgent")], default="0")
    description = fields.Html()
    task_id = fields.Many2one("project.task")
    operation_case_id = fields.Many2one("operations.operation.case")


class AppointmentType(models.Model):
    _name = "appointment.type"
    _description = "Appointment Type Simulator"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True)
    appointment_duration = fields.Float(default=1.0)
    appointment_tz = fields.Selection(selection=lambda self: [(tz, tz) for tz in __import__('pytz').all_timezones], default="UTC")
    min_schedule_hours = fields.Integer(default=24)
    max_schedule_days = fields.Integer(default=60)
    auto_confirm = fields.Boolean(default=True)
    website_url = fields.Char()
    website_absolute_url = fields.Char()


class CalendarEvent(models.Model):
    _inherit = "calendar.event"

    appointment_type_id = fields.Many2one("appointment.type")
    appointment_status = fields.Selection([
        ("booked", "Booked"), ("cancelled", "Cancelled"), ("no_show", "No Show")
    ])
    booking_location_url = fields.Char()
    booking_location_latitude = fields.Float()
    booking_location_longitude = fields.Float()
