import logging
import time
from xml.sax.saxutils import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.idempotency import WatiIdempotency


_logger = logging.getLogger(__name__)


def _clean(value):
    if value in (None, False):
        return ""
    return str(value).strip()


class WatiOtpFlowWorkflow(models.Model):
    _inherit = "wati.otp.flow"

    manual_button_placement = fields.Selection(
        [
            ("header", "Form header"),
            ("smart", "Smart button area"),
            ("actions", "Actions menu"),
        ],
        string="Button location",
        default="header",
        required=True,
    )
    manual_button_label = fields.Char(
        string="Button label", default="Send OTP", required=True
    )
    manual_view_id = fields.Many2one(
        "ir.ui.view",
        string="Form screen",
        ondelete="set null",
        domain="[('model', '=', model_name), ('type', '=', 'form')]",
        help="The form where the OTP button should appear. Odoo selects the primary form automatically.",
    )
    generated_manual_view_id = fields.Many2one(
        "ir.ui.view",
        string="Generated OTP button view",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    manual_condition_field_id = fields.Many2one(
        "ir.model.fields",
        string="Show button only when",
        ondelete="set null",
        domain="[('model_id', '=', model_id), ('store', '=', True), ('ttype', 'in', ['char', 'text', 'selection', 'boolean', 'integer', 'float', 'many2one'])]",
        help="Optional. Leave blank to show the button on every record of this type.",
    )
    manual_condition_operator = fields.Selection(
        [("equals", "Equals"), ("not_empty", "Has a value")],
        string="Button condition",
        default="equals",
        required=True,
    )
    manual_condition_value = fields.Char(
        string="Button condition value",
        help="For relational fields such as Stage, enter the visible value, for example: Resolved.",
    )

    post_action_ids = fields.One2many(
        "wati.otp.post.action",
        "flow_id",
        string="After verification actions",
        copy=True,
    )

    def _suggest_manual_form_view(self):
        self.ensure_one()
        if not self.model_name:
            return self.env["ir.ui.view"].browse()
        return self.env["ir.ui.view"].sudo().search(
            [
                ("model", "=", self.model_name),
                ("type", "=", "form"),
                ("mode", "=", "primary"),
                ("active", "=", True),
            ],
            order="priority asc, id asc",
            limit=1,
        )

    @api.onchange("model_id")
    def _onchange_model_for_manual_button(self):
        for flow in self:
            flow.manual_view_id = flow._suggest_manual_form_view()
            flow.manual_condition_field_id = False
            flow.manual_condition_value = False

    def _manual_condition_expected(self):
        self.ensure_one()
        field_record = self.manual_condition_field_id
        raw = _clean(self.manual_condition_value)
        if not field_record:
            return None
        if self.manual_condition_operator == "not_empty":
            return True
        if not raw:
            return False

        if field_record.ttype == "many2one":
            relation = field_record.relation
            if not relation or relation not in self.env:
                raise ValidationError(_("The related model for the button condition is unavailable."))
            Target = self.env[relation].sudo()
            if raw.isdigit():
                candidate = Target.browse(int(raw)).exists()
                if candidate:
                    return candidate.id
            rec_name = getattr(Target, "_rec_name", "name") or "name"
            if rec_name not in Target._fields:
                rec_name = "display_name"
            candidate = Target.search([(rec_name, "=", raw)], limit=1)
            if not candidate:
                candidates = Target.search([(rec_name, "ilike", raw)], limit=2)
                if len(candidates) > 1:
                    raise ValidationError(
                        _("More than one record matches the button condition '%s'. Use the exact visible value.")
                        % raw
                    )
                candidate = candidates
            if not candidate:
                raise ValidationError(
                    _("No value named '%s' was found for the button condition.") % raw
                )
            return candidate.id

        if field_record.ttype == "selection":
            field = self.env[self.model_name]._fields.get(field_record.name)
            selection = []
            if field:
                try:
                    selection = field._description_selection(self.env)
                except Exception:
                    selection = []
            for key, label in selection:
                if raw.casefold() in {_clean(key).casefold(), _clean(label).casefold()}:
                    return key
            return raw

        if field_record.ttype == "boolean":
            return raw.casefold() in {"1", "true", "yes", "on"}
        if field_record.ttype == "integer":
            return int(raw or 0)
        if field_record.ttype == "float":
            return float(raw or 0.0)
        return raw

    def _manual_condition_matches(self, record):
        self.ensure_one()
        field_record = self.manual_condition_field_id
        if not field_record:
            return True
        if field_record.name not in record._fields:
            return False
        current = record[field_record.name]
        if self.manual_condition_operator == "not_empty":
            return bool(current)
        expected = self._manual_condition_expected()
        field = record._fields[field_record.name]
        if field.type == "many2one":
            return bool(current and current.id == expected)
        if field.type == "selection":
            return current == expected
        if field.type == "boolean":
            return bool(current) is bool(expected)
        return current == expected or _clean(current).casefold() == _clean(expected).casefold()

    def _manual_invisible_expression(self):
        self.ensure_one()
        field_record = self.manual_condition_field_id
        if not field_record:
            return ""
        field_name = field_record.name
        if self.manual_condition_operator == "not_empty":
            return f"not {field_name}"
        expected = self._manual_condition_expected()
        return f"{field_name} != {repr(expected)}"

    def _manual_form_arch(self):
        self.ensure_one()
        if not self.manual_view_id or not self.model_name or self.model_name not in self.env:
            return ""
        try:
            payload = self.env[self.model_name].sudo().get_view(
                view_id=self.manual_view_id.id,
                view_type="form",
            )
            if isinstance(payload, dict):
                return _clean(payload.get("arch"))
        except Exception:
            pass
        return _clean(self.manual_view_id.arch_db)

    def _generated_manual_button_arch(self):
        self.ensure_one()
        if not self.manual_action_id:
            raise ValidationError(_("Activate the OTP Flow once so Odoo can create its button action."))
        arch = self._manual_form_arch()
        if not arch:
            raise ValidationError(_("The selected form screen could not be read."))

        label = escape(_clean(self.manual_button_label) or "Send OTP", {'"': '&quot;'})
        invisible = self._manual_invisible_expression()
        invisible_attr = (
            f' invisible="{escape(invisible, {chr(34): "&quot;"})}"' if invisible else ""
        )
        action_id = self.manual_action_id.id

        extra_field = ""
        if self.manual_condition_field_id:
            field_name = self.manual_condition_field_id.name
            token = f'name="{field_name}"'
            if token not in arch and "<sheet" in arch:
                extra_field = (
                    f'<xpath expr="//form/sheet" position="inside">'
                    f'<field name="{field_name}" invisible="1"/>'
                    f'</xpath>'
                )

        if self.manual_button_placement == "header":
            if "<header" not in arch:
                raise ValidationError(
                    _("This form does not have a header. Choose Smart button area, Actions menu, or another form screen.")
                )
            button = (
                f'<button name="{action_id}" type="action" string="{label}" '
                f'icon="fa-key" class="btn-primary"{invisible_attr}/>'
            )
            placement = f'<xpath expr="//form/header" position="inside">{button}</xpath>'
        elif self.manual_button_placement == "smart":
            if 'name="button_box"' not in arch:
                raise ValidationError(
                    _("This form does not have a smart-button area. Choose Form header, Actions menu, or another form screen.")
                )
            button = (
                f'<button name="{action_id}" type="action" class="oe_stat_button" '
                f'icon="fa-key"{invisible_attr}>'
                f'<div class="o_stat_info"><span class="o_stat_text">{label}</span></div>'
                f'</button>'
            )
            placement = (
                f'<xpath expr="//div[@name=\'button_box\']" position="inside">{button}</xpath>'
            )
        else:
            return "<data/>"

        return f"<data>{extra_field}{placement}</data>"

    def _sync_manual_button_view(self):
        for flow in self:
            generated = flow.generated_manual_view_id.sudo().exists()
            should_generate = bool(
                flow.active
                and flow.trigger_method == "manual"
                and flow.model_id
                and flow.manual_button_placement in ("header", "smart")
            )
            if not should_generate:
                if generated and generated.active:
                    generated.active = False
                continue

            if not flow.manual_view_id:
                suggested = flow._suggest_manual_form_view()
                if not suggested:
                    raise ValidationError(_("No form screen was found for this record type."))
                super(WatiOtpFlowWorkflow, flow.with_context(wati_otp_manual_internal=True)).write(
                    {"manual_view_id": suggested.id}
                )

            vals = {
                "name": f"WATI OTP Button · {flow.model_name} · {flow.id}",
                "model": flow.model_name,
                "inherit_id": flow.manual_view_id.id,
                "mode": "extension",
                "priority": 96,
                "active": True,
                "arch_db": flow._generated_manual_button_arch(),
            }
            if generated:
                generated.write(vals)
            else:
                generated = self.env["ir.ui.view"].sudo().create(vals)
                super(WatiOtpFlowWorkflow, flow.with_context(wati_otp_manual_internal=True)).write(
                    {"generated_manual_view_id": generated.id}
                )

    def _sync_trigger_actions(self):
        result = super()._sync_trigger_actions()
        for flow in self:
            manual_action = flow.manual_action_id.sudo().exists()
            if manual_action and flow.active and flow.trigger_method == "manual":
                if flow.manual_button_placement == "actions":
                    if manual_action.binding_model_id != flow.model_id:
                        manual_action.write({"binding_model_id": flow.model_id.id})
                elif manual_action.binding_model_id:
                    manual_action.write({"binding_model_id": False})
            flow._sync_manual_button_view()
        return result

    def action_request_for_records(self, records):
        self.ensure_one()
        if self.trigger_method == "manual" and self.manual_condition_field_id:
            blocked = records.filtered(lambda record: not self._manual_condition_matches(record))
            if blocked:
                raise UserError(
                    _("Send OTP is not available yet because the button condition is not satisfied for this record.")
                )
        return super().action_request_for_records(records)

    def _validate_step(self, step=None):
        result = super()._validate_step(step)
        current = step or self.setup_step
        if current == "source" and self.trigger_method == "manual":
            if self.manual_button_placement in ("header", "smart") and not (
                self.manual_view_id or self._suggest_manual_form_view()
            ):
                raise UserError(_("Choose the form screen where the OTP button should appear."))
            if (
                self.manual_condition_field_id
                and self.manual_condition_operator == "equals"
                and not _clean(self.manual_condition_value)
            ):
                raise UserError(_("Enter the value that controls when the OTP button is available."))
        if current == "verification":
            for action in self.post_action_ids.filtered("active"):
                action._validate_configuration()
        return result

    def write(self, vals):
        result = super().write(vals)
        watched = {
            "manual_button_placement",
            "manual_button_label",
            "manual_view_id",
            "manual_condition_field_id",
            "manual_condition_operator",
            "manual_condition_value",
        }
        if not self.env.context.get("wati_otp_manual_internal") and set(vals) & watched:
            self._sync_trigger_actions()
        return result

    def unlink(self):
        generated = self.mapped("generated_manual_view_id").sudo().exists()
        result = super().unlink()
        if generated:
            generated.unlink()
        return result

    def _apply_completion(self, transaction):
        self.ensure_one()
        actions = self.post_action_ids.filtered("active").sorted(lambda item: (item.sequence, item.id))
        if not actions:
            return super()._apply_completion(transaction)

        record = transaction._get_record()
        if not record:
            raise UserError(_("The source record no longer exists."))

        errors = []
        successful = 0
        for action in actions:
            try:
                action._execute(transaction, record)
                successful += 1
            except Exception as exc:
                _logger.exception(
                    "OTP post-verification action failed flow=%s action=%s transaction=%s",
                    self.id,
                    action.id,
                    transaction.id,
                )
                errors.append(f"{action.display_name}: {_clean(exc)}")

        if errors and successful:
            state = "partial"
        elif errors:
            state = "failed"
        else:
            state = "success"
        transaction.sudo().write(
            {
                "post_actions_state": state,
                "post_actions_error": "\n".join(errors)[:4000] or False,
            }
        )
        return True


class WatiOtpPostAction(models.Model):
    _name = "wati.otp.post.action"
    _description = "OTP Post-verification Action"
    _order = "sequence, id"

    flow_id = fields.Many2one(
        "wati.otp.flow", required=True, ondelete="cascade", index=True
    )
    model_id = fields.Many2one(
        "ir.model", related="flow_id.model_id", readonly=True
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    action_type = fields.Selection(
        [
            ("update_field", "Update an Odoo field"),
            ("send_whatsapp", "Send a WhatsApp template"),
            ("server_action", "Run an Odoo server action"),
        ],
        string="Action",
        default="update_field",
        required=True,
    )
    name = fields.Char(compute="_compute_name", store=True)

    field_id = fields.Many2one(
        "ir.model.fields",
        string="Field to update",
        ondelete="set null",
        domain="[('model_id', '=', model_id), ('store', '=', True), ('ttype', 'in', ['char', 'text', 'selection', 'boolean', 'integer', 'float', 'many2one'])]",
    )
    value = fields.Char(
        string="New value",
        help="For relational fields such as Stage, enter the visible value, for example: Closed.",
    )

    template_id = fields.Many2one(
        "wati.template",
        string="WhatsApp template",
        ondelete="restrict",
        domain="[('status', '=', 'approved'), ('active', '=', True)]",
    )
    channel_number = fields.Char(
        string="WATI channel number",
        help="Optional. Leave blank to use the template or default WATI channel.",
    )
    binding_ids = fields.One2many(
        "wati.otp.post.variable.binding",
        "action_id",
        string="Template variables",
        copy=True,
    )

    server_action_id = fields.Many2one(
        "ir.actions.server",
        string="Server action",
        ondelete="set null",
        domain="[('model_id', '=', model_id)]",
    )

    @api.depends("action_type", "field_id", "template_id", "server_action_id")
    def _compute_name(self):
        labels = dict(self._fields["action_type"].selection)
        for action in self:
            detail = False
            if action.action_type == "update_field" and action.field_id:
                detail = action.field_id.field_description or action.field_id.name
            elif action.action_type == "send_whatsapp" and action.template_id:
                detail = action.template_id.name
            elif action.action_type == "server_action" and action.server_action_id:
                detail = action.server_action_id.name
            action.name = labels.get(action.action_type, _("Action")) + (f" · {detail}" if detail else "")

    @api.onchange("action_type")
    def _onchange_action_type(self):
        for action in self:
            if action.action_type != "update_field":
                action.field_id = False
                action.value = False
            if action.action_type != "send_whatsapp":
                action.template_id = False
                action.channel_number = False
                action.binding_ids = [(5, 0, 0)]
            if action.action_type != "server_action":
                action.server_action_id = False

    @api.onchange("template_id")
    def _onchange_template_id(self):
        for action in self:
            commands = [(5, 0, 0)]
            if action.template_id:
                for index, variable in enumerate(action.template_id.variable_ids.sorted("position")):
                    commands.append(
                        (
                            0,
                            0,
                            {
                                "sequence": variable.position or index + 1,
                                "variable_name": variable.name,
                                "source_type": "record",
                            },
                        )
                    )
            action.binding_ids = commands

    def _validate_configuration(self):
        self.ensure_one()
        if self.action_type == "update_field":
            if not self.field_id:
                raise UserError(_("Choose the field for the post-verification update action."))
            if not _clean(self.value) and self.field_id.ttype != "boolean":
                raise UserError(_("Enter the new value for the post-verification update action."))
        elif self.action_type == "send_whatsapp":
            if not self.template_id or self.template_id.status != "approved":
                raise UserError(_("Choose an approved WATI template for the post-verification message."))
            variables = set(self.template_id.variable_ids.mapped("name"))
            mapped = set(self.binding_ids.mapped("variable_name"))
            if variables != mapped:
                raise UserError(_("Re-select the post-verification template to refresh its variables."))
            for binding in self.binding_ids:
                if binding.source_type == "record" and not _clean(binding.field_path):
                    raise UserError(
                        _("Choose an Odoo field for template variable %s.") % binding.variable_name
                    )
        elif self.action_type == "server_action" and not self.server_action_id:
            raise UserError(_("Choose the Odoo server action to run after verification."))
        return True

    def _binding_value(self, binding, record):
        if binding.source_type == "static":
            return binding.static_value or ""
        return _clean(self.flow_id._resolve_path(record, binding.field_path))

    def _send_template(self, transaction, record):
        self.ensure_one()
        self._validate_configuration()
        flow = self.flow_id
        phone = flow._record_phone(record)
        if not phone:
            raise UserError(_("No valid WhatsApp number was found for the post-verification message."))

        params = [
            {"name": binding.variable_name, "value": _clean(self._binding_value(binding, record))}
            for binding in self.binding_ids.sorted("sequence")
        ]
        client = WatiClient(self.env)
        body = {
            "template_name": self.template_id.name,
            "broadcast_name": f"odoo_otp_verified_{flow.id}_{transaction.id}_{self.id}_{int(time.time())}",
            "receivers": [{"whatsappNumber": phone, "customParams": params}],
        }
        effective_channel = _clean(
            self.channel_number
            or self.template_id.channel_phone_number
            or client.config.channel_number
        )
        if effective_channel:
            body["channel_number"] = effective_channel

        idem = WatiIdempotency(self.env)
        scope = f"wati:otp-post:{self.id}"
        key = idem.digest(flow.technical_key, transaction.id, self.id, phone)
        if not idem.acquire_durable(scope, key, ttl_seconds=86400):
            return True
        try:
            client.send_template_messages(body)
        except WatiConfigurationError as exc:
            idem.release_durable(scope, key)
            raise UserError(_("WATI API settings are incomplete for the post-verification message.")) from exc
        except WatiRequestError as exc:
            raise UserError(
                _("WATI rejected the post-verification message%s.")
                % (f" ({exc.status_code})" if exc.status_code else "")
            ) from exc
        return True

    def _execute(self, transaction, record):
        self.ensure_one()
        self._validate_configuration()
        if self.action_type == "update_field":
            field = self.field_id
            if field.name not in record._fields:
                raise UserError(_("The selected field is no longer available on this record."))
            value = self.flow_id._coerce_completion_value(field, self.value)
            record.write({field.name: value})
        elif self.action_type == "send_whatsapp":
            self._send_template(transaction, record)
        elif self.action_type == "server_action":
            action = self.server_action_id.sudo().exists()
            if not action:
                raise UserError(_("The selected server action is no longer available."))
            action.with_context(
                active_model=record._name,
                active_id=record.id,
                active_ids=record.ids,
            ).run()
        return True


class WatiOtpPostVariableBinding(models.Model):
    _name = "wati.otp.post.variable.binding"
    _description = "OTP Post-verification Template Variable"
    _order = "sequence, id"

    action_id = fields.Many2one(
        "wati.otp.post.action", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    variable_name = fields.Char(string="Template variable", required=True)
    source_type = fields.Selection(
        [("record", "Odoo field"), ("static", "Fixed value")],
        string="Value source",
        default="record",
        required=True,
    )
    field_path = fields.Char(string="Odoo field path", help="Example: partner_id.name")
    static_value = fields.Char(string="Fixed value")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("variable_name"):
                continue
            action_id = vals.get("action_id") or self.env.context.get("default_action_id")
            action = self.env["wati.otp.post.action"].browse(action_id).exists() if action_id else False
            if not action or not action.template_id:
                continue
            variables = action.template_id.variable_ids.sorted("position")
            sequence = int(vals.get("sequence") or 0)
            variable = next((item for item in variables if item.position == sequence), False)
            if not variable and variables:
                variable = variables[0]
            if variable:
                vals["variable_name"] = variable.name
        return super().create(vals_list)


class WatiOtpTransactionWorkflow(models.Model):
    _inherit = "wati.otp.transaction"

    post_actions_state = fields.Selection(
        [
            ("none", "No actions"),
            ("success", "Completed"),
            ("partial", "Partially completed"),
            ("failed", "Action failed"),
        ],
        string="After verification",
        default="none",
        readonly=True,
    )
    post_actions_error = fields.Text(string="Post-verification errors", readonly=True)
