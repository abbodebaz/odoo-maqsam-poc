from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.config import WatiConfig


_EVENT_OPERATOR_LABELS = {
    "eq": "يساوي",
    "ne": "لا يساوي",
    "contains": "يحتوي على",
    "gt": "أكبر من",
    "gte": "أكبر من أو يساوي",
    "lt": "أقل من",
    "lte": "أقل من أو يساوي",
    "is_set": "تصبح له قيمة",
    "is_not_set": "يصبح فارغًا",
}


class WatiAutomationRuleBuilder(models.Model):
    _inherit = "wati.automation.rule"

    # ``ir.ui.menu`` root menus are the actual apps users see in Odoo's app switcher.
    # Using them gives us an app-first experience without hard-coding CRM, Sales,
    # Helpdesk, Project, or any custom module name.
    app_menu_id = fields.Many2one(
        "ir.ui.menu",
        string="التطبيق",
        ondelete="set null",
        copy=False,
        help="التطبيق الظاهر في واجهة Odoo الذي يحتوي السجل المراد مراقبته.",
    )
    available_app_menu_ids = fields.Many2many(
        "ir.ui.menu",
        compute="_compute_available_app_menu_ids",
        string="التطبيقات المتاحة",
    )
    available_model_ids = fields.Many2many(
        "ir.model",
        compute="_compute_available_model_ids",
        string="السجلات المتاحة داخل التطبيق",
    )
    event_type = fields.Selection(
        [
            ("field_condition", "عندما يتغير حقل ويطابق شرطًا"),
            ("on_create", "عند إنشاء سجل جديد"),
            ("on_update", "عند تحديث السجل"),
        ],
        string="نوع الحدث",
        default="field_condition",
        copy=True,
    )

    # Field conditions are optional for create/update events. This incrementally
    # relaxes the original required=True field while preserving its domain.
    trigger_field_id = fields.Many2one(
        "ir.model.fields",
        string="الحقل المراقَب",
        required=False,
        ondelete="cascade",
        domain="[('model_id', '=', model_id), ('store', '=', True)]",
        help="يُستخدم فقط عندما يكون نوع الحدث مبنيًا على تغير حقل.",
    )

    event_summary = fields.Char(
        string="ملخص الحدث",
        compute="_compute_event_summary",
        help="وصف مبسط للحدث الذي سيبدأ الأتمتة.",
    )

    @api.depends_context("uid")
    def _compute_available_app_menu_ids(self):
        roots = self.env["ir.ui.menu"].get_user_roots()
        for rule in self:
            rule.available_app_menu_ids = roots

    @api.depends("app_menu_id")
    def _compute_available_model_ids(self):
        Menu = self.env["ir.ui.menu"]
        IrModel = self.env["ir.model"].sudo()
        Access = self.env["ir.model.access"]

        for rule in self:
            rule.available_model_ids = IrModel.browse()
            if not rule.app_menu_id:
                continue

            menus = Menu.search([("id", "child_of", rule.app_menu_id.id)])
            try:
                menus = menus._filter_visible_menus()
            except Exception:
                # Visibility filtering is a UX refinement. Record/model ACL checks
                # below remain the authoritative security boundary.
                pass

            model_names = set()
            for action in menus.mapped("action"):
                if not action or action._name != "ir.actions.act_window":
                    continue
                model_name = (action.res_model or "").strip()
                if model_name and model_name in self.env:
                    model_names.add(model_name)

            if not model_names:
                continue

            candidates = IrModel.search([
                ("model", "in", sorted(model_names)),
                ("transient", "=", False),
                ("abstract", "=", False),
            ])
            rule.available_model_ids = candidates.filtered(
                lambda model: Access.check(model.model, "read", False)
            )

    @api.depends(
        "app_menu_id",
        "model_id",
        "event_type",
        "trigger_field_id",
        "condition_operator",
        "target_value",
    )
    def _compute_event_summary(self):
        for rule in self:
            app_label = rule.app_menu_id.name or ""
            if not rule.model_id:
                rule.event_summary = (
                    _("اختر ما تريد مراقبته داخل %s.", app_label)
                    if app_label
                    else _("اختر التطبيق أولًا.")
                )
                continue

            model_label = rule.model_id.name or rule.model_id.model or _("السجل")
            scope = _(" داخل %s", app_label) if app_label else ""
            event_type = rule.event_type or "field_condition"

            if event_type == "on_create":
                rule.event_summary = _("سيبدأ الإرسال عند إنشاء %(model)s جديد%(scope)s.", model=model_label, scope=scope)
                continue
            if event_type == "on_update":
                rule.event_summary = _("سيبدأ الإرسال عند تحديث %(model)s%(scope)s.", model=model_label, scope=scope)
                continue

            if not rule.trigger_field_id:
                rule.event_summary = _(
                    "سنراقب %(model)s%(scope)s. اختر الحقل الذي يبدأ الحدث.",
                    model=model_label,
                    scope=scope,
                )
                continue

            field_label = (
                rule.trigger_field_id.field_description
                or rule.trigger_field_id.name
                or _("الحقل")
            )
            operator = _EVENT_OPERATOR_LABELS.get(
                rule.condition_operator,
                rule.condition_operator or "",
            )
            target = (rule.target_value or "").strip()

            if rule.condition_operator in ("is_set", "is_not_set"):
                rule.event_summary = _(
                    "سيبدأ الإرسال عندما %(field)s %(operator)s في %(model)s%(scope)s.",
                    field=field_label,
                    operator=operator,
                    model=model_label,
                    scope=scope,
                )
            elif target:
                rule.event_summary = _(
                    "سيبدأ الإرسال عندما %(field)s %(operator)s «%(target)s» في %(model)s%(scope)s.",
                    field=field_label,
                    operator=operator,
                    target=target,
                    model=model_label,
                    scope=scope,
                )
            else:
                rule.event_summary = _(
                    "سنراقب %(field)s في %(model)s%(scope)s. أكمل الشرط والقيمة المطلوبة.",
                    field=field_label,
                    model=model_label,
                    scope=scope,
                )

    @api.onchange("app_menu_id")
    def _onchange_builder_app_menu_id(self):
        for rule in self:
            rule.model_id = False
            rule.trigger_field_id = False
            rule.target_value = False
            rule.recipient_field_id = False

    @api.onchange("model_id")
    def _onchange_builder_model_id(self):
        """Keep dependent selections valid when the user changes the Odoo model."""
        for rule in self:
            if rule.trigger_field_id and rule.trigger_field_id.model_id != rule.model_id:
                rule.trigger_field_id = False
                rule.target_value = False
            if rule.recipient_field_id and rule.recipient_field_id.model_id != rule.model_id:
                rule.recipient_field_id = False

    @api.onchange("event_type")
    def _onchange_builder_event_type(self):
        for rule in self:
            if (rule.event_type or "field_condition") != "field_condition":
                rule.trigger_field_id = False
                rule.target_value = False

    @api.onchange("trigger_field_id")
    def _onchange_builder_trigger_field_id(self):
        for rule in self:
            rule.target_value = False

    def _sync_odoo_automation(self):
        """Map the friendly builder event onto Odoo's native automation engine."""
        self.ensure_one()
        automation = self.base_automation_id.sudo().exists()

        if not self.id or not self.model_id:
            if automation:
                automation.write({"active": False})
            return

        event_type = self.event_type or "field_condition"
        if event_type == "field_condition":
            if not self.trigger_field_id:
                if automation:
                    automation.write({"active": False})
                return
            odoo_trigger = "on_create_or_write"
            trigger_field_ids = [self.trigger_field_id.id]
        elif event_type == "on_create":
            odoo_trigger = "on_create"
            trigger_field_ids = []
        elif event_type == "on_update":
            # Odoo 19 still supports on_write for update-only automations.
            odoo_trigger = "on_write"
            trigger_field_ids = []
        else:
            if automation:
                automation.write({"active": False})
            return

        automation_vals = {
            "name": f"WATI · {self.name}",
            "model_id": self.model_id.id,
            "trigger": odoo_trigger,
            "trigger_field_ids": [(6, 0, trigger_field_ids)],
            "active": bool(self.active),
        }

        if automation:
            automation.write(automation_vals)
        else:
            automation = self.env["base.automation"].sudo().create(automation_vals)
            self.with_context(wati_builder_internal=True).write({"base_automation_id": automation.id})

        code = (
            "if record:\n"
            f"    env['wati.automation.rule'].sudo().browse({self.id})._execute_record(record)"
        )
        action_vals = {
            "name": f"WATI · {self.name}",
            "model_id": self.model_id.id,
            "state": "code",
            "code": code,
            "usage": "base_automation",
            "base_automation_id": automation.id,
        }
        server_action = self.server_action_id.sudo().exists()
        if server_action:
            server_action.write(action_vals)
        else:
            server_action = self.env["ir.actions.server"].sudo().create(action_vals)
            self.with_context(wati_builder_internal=True).write({"server_action_id": server_action.id})

    def _condition_matches(self, record):
        if (self.event_type or "field_condition") in ("on_create", "on_update"):
            return True
        return super()._condition_matches(record)

    @api.depends(
        "name",
        "app_menu_id",
        "model_id",
        "event_type",
        "trigger_field_id",
        "condition_operator",
        "target_value",
        "recipient_field_id",
        "recipient_path",
        "template_name",
        "once_per_record",
        "parameter_ids.param_name",
        "parameter_ids.source_type",
        "parameter_ids.source_field_id",
        "parameter_ids.source_path",
        "parameter_ids.static_value",
    )
    def _compute_ux_state(self):
        api_ready = WatiConfig(self.env).is_api_configured
        for rule in self:
            app_label = rule.app_menu_id.name or ""
            model_label = rule.model_id.name or "السجل"
            event_type = rule.event_type or "field_condition"
            target = (rule.target_value or "").strip()

            if event_type == "on_create":
                condition_text = f"إنشاء {model_label} جديد"
                trigger_complete = bool(rule.model_id)
                condition_complete = True
            elif event_type == "on_update":
                condition_text = f"تحديث {model_label}"
                trigger_complete = bool(rule.model_id)
                condition_complete = True
            else:
                field_label = rule.trigger_field_id.field_description or rule.trigger_field_id.name or "الحقل"
                operator = _EVENT_OPERATOR_LABELS.get(rule.condition_operator, rule.condition_operator or "")
                if rule.condition_operator in ("is_set", "is_not_set"):
                    condition_text = f"{field_label} {operator}"
                elif target:
                    condition_text = f"{field_label} {operator} «{target}»"
                else:
                    condition_text = f"{field_label} {operator} ..."
                trigger_complete = bool(rule.model_id and rule.trigger_field_id)
                condition_complete = bool(
                    rule.condition_operator in ("is_set", "is_not_set") or target
                )

            if rule.recipient_field_id:
                recipient = rule.recipient_field_id.field_description or rule.recipient_field_id.name
            elif rule.recipient_path:
                recipient = rule.recipient_path
            else:
                recipient = "رقم العميل تلقائيًا"

            template = rule.template_name or "قالب لم يُحدد بعد"
            once = " · مرة واحدة لكل سجل" if rule.once_per_record else ""
            app_scope = f" داخل {app_label}" if app_label else ""
            rule.human_summary = (
                f"عند {condition_text}{app_scope} ← أرسل «{template}» إلى {recipient}{once}"
            )

            errors = []
            warnings = []
            if not rule.name:
                errors.append("اسم القاعدة")
            if not rule.model_id:
                errors.append("نوع السجل داخل التطبيق")
            if event_type == "field_condition" and not rule.trigger_field_id:
                errors.append("الحقل المراقَب")
            if event_type == "field_condition" and not condition_complete:
                errors.append("القيمة المطلوبة")
            if not rule.template_name:
                errors.append("قالب WATI")
            if not api_ready:
                errors.append("اتصال WATI API")

            unmapped = []
            for line in rule.parameter_ids:
                if not line.param_name:
                    continue
                mapped = (
                    line.source_type in ("record_id", "record_name")
                    or (line.source_type == "static" and bool((line.static_value or "").strip()))
                    or (
                        line.source_type == "field"
                        and bool(line.source_field_id or (line.source_path or "").strip())
                    )
                )
                if not mapped:
                    unmapped.append(line.param_name)
            if unmapped:
                errors.append("متغيرات غير مربوطة: " + ", ".join(unmapped[:6]))
            if rule.template_name and not rule.parameter_ids:
                warnings.append("لم يتم جلب متغيرات القالب بعد؛ إذا كان القالب يحتوي متغيرات اضغط جلب المتغيرات.")
            if not rule.recipient_field_id and not rule.recipient_path:
                warnings.append("سيبحث النظام تلقائيًا عن mobile / phone / رقم العميل المرتبط.")

            rule.readiness_state = "incomplete" if errors else ("warning" if warnings else "ready")
            checklist = [
                "✅ السجل والحدث محددان" if trigger_complete else "❌ حدد السجل والحدث",
                "✅ شرط الحدث مكتمل" if condition_complete else "❌ أكمل شرط الحدث",
                "✅ قالب WATI محدد" if rule.template_name else "❌ اختر قالب WATI",
                "✅ اتصال WATI جاهز" if api_ready else "❌ إعدادات WATI API غير مكتملة",
            ]
            if unmapped:
                checklist.append("❌ اربط: " + ", ".join(unmapped[:6]))
            elif rule.parameter_ids:
                checklist.append(f"✅ {len(rule.parameter_ids)} متغيرات مربوطة")
            elif rule.template_name:
                checklist.append("⚠️ لا توجد متغيرات محملة للقالب")
            checklist.extend("⚠️ " + item for item in warnings)
            rule.readiness_message = "\n".join(checklist)

    def _validate_step(self, step=None):
        self.ensure_one()
        step = step or self.setup_step
        if step != "trigger":
            return super()._validate_step(step)

        missing = []
        if not self.name:
            missing.append("اسم الأتمتة")
        if not self.model_id:
            missing.append("ما تريد مراقبته داخل التطبيق")

        event_type = self.event_type or "field_condition"
        if event_type == "field_condition":
            if not self.trigger_field_id:
                missing.append("الحقل المراقَب")
            if self.condition_operator not in ("is_set", "is_not_set") and not (self.target_value or "").strip():
                missing.append("القيمة المطلوبة")

        if missing:
            raise UserError(_("أكمل الخطوة الأولى: %s", "، ".join(missing)))

    def write(self, vals):
        result = super().write(vals)
        if (
            not self.env.context.get("wati_builder_internal")
            and "event_type" in vals
        ):
            for rule in self:
                rule._sync_odoo_automation()
        return result

    def action_apply_named_preset(self):
        self.ensure_one()
        preset_key = (self.env.context.get("wati_preset_key") or "").strip()
        if not preset_key:
            return self.action_apply_preset()
        self.preset_key = preset_key
        return self.action_apply_preset()

    def action_start_custom_builder(self):
        self.ensure_one()
        self.write({"preset_key": False, "setup_step": "trigger"})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("إعداد مخصص"),
                "message": _("ابدأ باختيار التطبيق، ثم ما تريد مراقبته داخله، ثم نوع الحدث."),
                "type": "info",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }
