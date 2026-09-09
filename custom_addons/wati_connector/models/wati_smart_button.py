import time
import uuid
from xml.sax.saxutils import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.idempotency import WatiIdempotency
from ..utils.phone import normalize_whatsapp_number


def _clean(value):
    if value in (None, False):
        return ""
    return str(value).strip()


class WatiSmartButtonLocation(models.Model):
    _name = "wati.smart.button.location"
    _description = "WATI Smart Button Location"
    _order = "sequence, id"

    name = fields.Char(string="اسم المكان", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(string="مفعّل", default=False)
    button_label = fields.Char(string="اسم الزر", default="WhatsApp", required=True)

    app_menu_id = fields.Many2one(
        "ir.ui.menu",
        string="التطبيق",
        ondelete="set null",
        help="اختر التطبيق أولًا لتقليل قائمة الموديلات المعروضة.",
    )
    available_app_menu_ids = fields.Many2many(
        "ir.ui.menu",
        compute="_compute_available_app_menu_ids",
        string="التطبيقات المتاحة",
    )
    model_id = fields.Many2one(
        "ir.model",
        string="الموديل / نوع السجل",
        ondelete="cascade",
        domain=[("transient", "=", False)],
        required=True,
    )
    model_name = fields.Char(related="model_id.model", store=True, readonly=True)
    available_model_ids = fields.Many2many(
        "ir.model",
        compute="_compute_available_model_ids",
        string="الموديلات المتاحة",
    )
    view_id = fields.Many2one(
        "ir.ui.view",
        string="نموذج الشاشة",
        ondelete="cascade",
        domain="[('model', '=', model_name), ('type', '=', 'form')]",
        help="يتم اختياره تلقائيًا. غيّره فقط إذا كان للموديل أكثر من شاشة Form.",
    )

    phone_field_id = fields.Many2one(
        "ir.model.fields",
        string="حقل رقم الجوال",
        ondelete="set null",
        domain="[('model_id', '=', model_id), ('ttype', 'in', ['char', 'text'])]",
    )
    phone_path = fields.Char(
        string="مسار رقم الجوال",
        help="عند وجود الرقم داخل علاقة، مثال: partner_id.mobile أو customer_id.phone.",
    )
    partner_path = fields.Char(
        string="مسار العميل",
        help="اختياري لربط المحادثة ببطاقة العميل، مثال: partner_id.",
    )
    generated_view_id = fields.Many2one(
        "ir.ui.view",
        string="الواجهة المولدة",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    mapping_state = fields.Selection(
        [("incomplete", "غير مكتمل"), ("ready", "جاهز")],
        compute="_compute_mapping_state",
        string="الحالة",
    )
    mapping_summary = fields.Char(compute="_compute_mapping_state", string="ملخص")

    @api.depends_context("uid")
    def _compute_available_app_menu_ids(self):
        roots = self.env["ir.ui.menu"].get_user_roots()
        for record in self:
            record.available_app_menu_ids = roots

    @api.depends("app_menu_id")
    def _compute_available_model_ids(self):
        Menu = self.env["ir.ui.menu"]
        IrModel = self.env["ir.model"].sudo()
        Access = self.env["ir.model.access"]
        for record in self:
            record.available_model_ids = IrModel.browse()
            if not record.app_menu_id:
                continue
            menus = Menu.search([("id", "child_of", record.app_menu_id.id)])
            try:
                menus = menus._filter_visible_menus()
            except Exception:
                pass
            model_names = set()
            for action in menus.mapped("action"):
                if action and action._name == "ir.actions.act_window":
                    model_name = _clean(action.res_model)
                    if model_name and model_name in self.env:
                        model_names.add(model_name)
            if not model_names:
                continue
            candidates = IrModel.search(
                [
                    ("model", "in", sorted(model_names)),
                    ("transient", "=", False),
                    ("abstract", "=", False),
                ]
            )
            record.available_model_ids = candidates.filtered(
                lambda item: Access.check(item.model, "read", False)
            )

    @api.depends("active", "model_id", "view_id", "phone_field_id", "phone_path")
    def _compute_mapping_state(self):
        for record in self:
            missing = []
            if not record.model_id:
                missing.append("الموديل")
            if not record.view_id:
                missing.append("الشاشة")
            if not record.phone_field_id and not _clean(record.phone_path):
                missing.append("رقم الجوال")
            record.mapping_state = "incomplete" if missing else "ready"
            if missing:
                record.mapping_summary = "أكمل: " + "، ".join(missing)
            else:
                source = record.phone_path or record.phone_field_id.field_description or record.phone_field_id.name
                record.mapping_summary = f"سيظهر زر {record.button_label} في {record.model_id.name} ويقرأ الرقم من {source}."

    @api.onchange("app_menu_id")
    def _onchange_app_menu_id(self):
        for record in self:
            record.model_id = False
            record.view_id = False
            record.phone_field_id = False
            record.phone_path = False
            record.partner_path = False

    @api.onchange("model_id")
    def _onchange_model_id(self):
        for record in self:
            record.view_id = record._suggest_form_view()
            record.phone_field_id = False
            record.phone_path = False
            record.partner_path = False
            record._auto_detect_phone_and_partner()

    @api.constrains("model_id", "view_id", "phone_field_id")
    def _check_model_fields(self):
        for record in self:
            if record.view_id and record.view_id.model != record.model_name:
                raise ValidationError(_("شاشة Form لا تنتمي إلى الموديل المختار."))
            if record.phone_field_id and record.phone_field_id.model_id != record.model_id:
                raise ValidationError(_("حقل الجوال لا ينتمي إلى الموديل المختار."))

    @api.constrains("active", "model_id", "view_id", "phone_field_id", "phone_path")
    def _check_active_mapping(self):
        for record in self:
            if record.active and (
                not record.model_id
                or not record.view_id
                or (not record.phone_field_id and not _clean(record.phone_path))
            ):
                raise ValidationError(_("أكمل الموديل والشاشة ومصدر رقم الجوال قبل تفعيل الزر."))

    def _suggest_form_view(self):
        self.ensure_one()
        if not self.model_id:
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

    def _auto_detect_phone_and_partner(self):
        self.ensure_one()
        if not self.model_id:
            return
        Fields = self.env["ir.model.fields"].sudo()
        for field_name in ("mobile", "whatsapp", "wa_id", "phone"):
            candidate = Fields.search(
                [
                    ("model_id", "=", self.model_id.id),
                    ("name", "=", field_name),
                    ("ttype", "in", ["char", "text"]),
                ],
                limit=1,
            )
            if candidate:
                self.phone_field_id = candidate
                break

        if self.model_name == "res.partner":
            self.partner_path = "self"
            return

        partner_field = Fields.search(
            [
                ("model_id", "=", self.model_id.id),
                ("ttype", "=", "many2one"),
                ("relation", "=", "res.partner"),
                ("name", "in", ["partner_id", "commercial_partner_id", "customer_id"]),
            ],
            order="id asc",
            limit=1,
        )
        if partner_field:
            self.partner_path = partner_field.name
            if not self.phone_field_id:
                self.phone_path = f"{partner_field.name}.mobile"

    def action_auto_detect(self):
        for record in self:
            if not record.model_id:
                raise UserError(_("اختر التطبيق والموديل أولًا."))
            if not record.view_id:
                record.view_id = record._suggest_form_view()
            record.phone_field_id = False
            record.phone_path = False
            record.partner_path = False
            record._auto_detect_phone_and_partner()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("زر WhatsApp الذكي"),
                "message": _("تم اكتشاف الشاشة ومصدر رقم الجوال قدر الإمكان. راجع القيم ثم فعّل المكان."),
                "type": "success",
                "sticky": False,
            },
        }

    def _resolve_path(self, record, path):
        if _clean(path) == "self":
            return record
        current = record
        for part in [item.strip() for item in _clean(path).split(".") if item.strip()]:
            if not hasattr(current, "_fields") or part not in current._fields:
                return False
            current = current[part]
            if not current:
                return False
        return current

    def resolve_phone(self, record):
        self.ensure_one()
        value = False
        if _clean(self.phone_path):
            value = self._resolve_path(record, self.phone_path)
        if not value and self.phone_field_id and self.phone_field_id.name in record._fields:
            value = record[self.phone_field_id.name]
        if not value:
            for fallback in ("mobile", "phone", "partner_id.mobile", "partner_id.phone"):
                value = self._resolve_path(record, fallback)
                if value:
                    break
        return normalize_whatsapp_number(value)

    def resolve_partner(self, record):
        self.ensure_one()
        if record._name == "res.partner":
            return record
        if _clean(self.partner_path):
            partner = self._resolve_path(record, self.partner_path)
            if getattr(partner, "_name", "") == "res.partner" and len(partner) == 1:
                return partner
        for field_name in ("partner_id", "commercial_partner_id", "customer_id"):
            if field_name in record._fields:
                partner = record[field_name]
                if getattr(partner, "_name", "") == "res.partner" and len(partner) == 1:
                    return partner
        return self.env["res.partner"].browse()

    def _combined_form_arch(self):
        self.ensure_one()
        if not self.view_id or not self.model_name or self.model_name not in self.env:
            return ""
        try:
            payload = self.env[self.model_name].sudo().get_view(
                view_id=self.view_id.id,
                view_type="form",
            )
            return _clean(payload.get("arch")) if isinstance(payload, dict) else ""
        except Exception:
            return _clean(self.view_id.arch_db)

    def _generated_arch(self):
        self.ensure_one()
        action = self.env.ref("wati_connector.action_wati_universal_compose")
        label = escape(_clean(self.button_label) or "WhatsApp", {'"': '&quot;'})
        button = (
            f'<button name="{action.id}" type="action" string="{label}" '
            'icon="fa-whatsapp" class="btn-primary" '
            'groups="wati_connector.group_wati_agent" '
            f'context="{{\'wati_button_rule_id\': {self.id}}}"/>'
        )
        arch = self._combined_form_arch()
        if "<header" in arch:
            return f'<data><xpath expr="//form/header" position="inside">{button}</xpath></data>'
        if "<sheet" in arch:
            return f'<data><xpath expr="//form/sheet" position="before"><header>{button}</header></xpath></data>'
        raise ValidationError(
            _("تعذر تركيب زر WhatsApp على هذه الشاشة لأنها لا تحتوي Header أو Sheet. اختر Form View آخر.")
        )

    def _sync_generated_view(self):
        self.ensure_one()
        current = self.generated_view_id.sudo().exists()
        if not self.active:
            if current:
                current.active = False
            return
        if self.mapping_state != "ready":
            raise ValidationError(_("أكمل إعداد مكان زر WhatsApp قبل التفعيل."))
        vals = {
            "name": f"WATI Smart Button · {self.model_name} · {self.id}",
            "model": self.model_name,
            "inherit_id": self.view_id.id,
            "mode": "extension",
            "priority": 95,
            "active": True,
            "arch_db": self._generated_arch(),
        }
        if current:
            current.write(vals)
        else:
            generated = self.env["ir.ui.view"].sudo().create(vals)
            super(WatiSmartButtonLocation, self.with_context(wati_smart_internal=True)).write(
                {"generated_view_id": generated.id}
            )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            changed = {}
            if record.model_id and not record.view_id:
                view = record._suggest_form_view()
                if view:
                    changed["view_id"] = view.id
            if changed:
                super(WatiSmartButtonLocation, record.with_context(wati_smart_internal=True)).write(changed)
            if record.model_id and not record.phone_field_id and not _clean(record.phone_path):
                record._auto_detect_phone_and_partner()
            record._sync_generated_view()
        return records

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("wati_smart_internal") and set(vals) & {
            "name",
            "active",
            "button_label",
            "model_id",
            "view_id",
            "phone_field_id",
            "phone_path",
            "partner_path",
        }:
            for record in self:
                record._sync_generated_view()
        return result

    def unlink(self):
        generated = self.mapped("generated_view_id").sudo()
        result = super().unlink()
        if generated:
            generated.unlink()
        return result

    def action_sync_view(self):
        for record in self:
            record._sync_generated_view()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("زر WhatsApp الذكي"),
                "message": _("تم تحديث ظهور الزر في شاشات Odoo."),
                "type": "success",
                "sticky": False,
            },
        }


class WatiUniversalComposeWizard(models.TransientModel):
    _name = "wati.universal.compose.wizard"
    _description = "Universal WhatsApp Composer"

    rule_id = fields.Many2one("wati.smart.button.location", string="مكان الزر", readonly=True)
    source_model = fields.Char(string="الموديل", readonly=True)
    source_res_id = fields.Integer(string="رقم السجل", readonly=True)
    record_name = fields.Char(string="السجل", readonly=True)
    partner_id = fields.Many2one("res.partner", string="العميل", readonly=True)
    phone = fields.Char(string="رقم WhatsApp", required=True)
    send_mode = fields.Selection(
        [("session", "رسالة عادية"), ("template", "قالب WhatsApp")],
        string="طريقة الإرسال",
        required=True,
        default="session",
    )
    message = fields.Text(string="الرسالة")
    template_id = fields.Many2one(
        "wati.template",
        string="القالب",
        domain="[('status', '=', 'approved'), ('active', '=', True)]",
    )
    parameter_ids = fields.One2many(
        "wati.universal.compose.parameter",
        "wizard_id",
        string="متغيرات القالب",
    )
    request_key = fields.Char(default=lambda self: uuid.uuid4().hex, readonly=True)

    @api.model
    def default_get(self, field_list):
        values = super().default_get(field_list)
        context = self.env.context
        rule = self.env["wati.smart.button.location"].sudo().browse(
            int(context.get("wati_button_rule_id") or 0)
        ).exists()
        model_name = _clean(context.get("active_model"))
        res_id = int(context.get("active_id") or 0)
        if not rule or not model_name or not res_id or rule.model_name != model_name:
            return values
        record = self.env[model_name].browse(res_id).exists()
        if not record:
            return values
        partner = rule.resolve_partner(record)
        values.update(
            {
                "rule_id": rule.id,
                "source_model": model_name,
                "source_res_id": res_id,
                "record_name": record.display_name,
                "phone": rule.resolve_phone(record),
                "partner_id": partner.id if partner else False,
            }
        )
        return values

    def _source_record(self):
        self.ensure_one()
        if not self.source_model or self.source_model not in self.env or not self.source_res_id:
            return self.env["res.partner"].browse()
        return self.env[self.source_model].browse(self.source_res_id).exists()

    @api.onchange("template_id")
    def _onchange_template_id(self):
        for wizard in self:
            wizard.parameter_ids = [(5, 0, 0)]
            if not wizard.template_id:
                continue
            record = wizard._source_record()
            partner = wizard.partner_id
            lines = []
            for variable in wizard.template_id.variable_ids.sorted("position"):
                value = wizard._smart_parameter_default(variable.name, record, partner)
                lines.append(
                    (0, 0, {"param_name": variable.name, "value": value})
                )
            wizard.parameter_ids = lines

    def _smart_parameter_default(self, name, record, partner):
        token = _clean(name).casefold()
        if token in {"name", "customer_name", "client_name"}:
            return partner.display_name if partner else (record.display_name if record else "")
        if token in {"record", "record_name", "order", "order_name", "lead", "lead_name"}:
            return record.display_name if record else ""
        if token in {"id", "record_id"}:
            return str(record.id) if record else ""
        if token in {"phone", "mobile", "whatsapp", "whatsapp_number"}:
            return self.phone or ""
        return ""

    def _conversation(self, phone):
        self.ensure_one()
        Conversation = self.env["wati.conversation"].sudo()
        conversation = Conversation.search([("wa_id", "=", phone)], order="id desc", limit=1)
        if conversation:
            if self.partner_id and not conversation.partner_id:
                conversation.partner_id = self.partner_id
            return conversation
        return Conversation.create(
            {
                "name": self.partner_id.display_name or self.record_name or phone,
                "wa_id": phone,
                "partner_id": self.partner_id.id if self.partner_id else False,
                "status": "",
                "last_message_at": fields.Datetime.now(),
                "unread_count": 0,
            }
        )

    def action_send(self):
        self.ensure_one()
        phone = normalize_whatsapp_number(self.phone)
        if not phone:
            raise UserError(_("لم يتم العثور على رقم WhatsApp صالح لهذا السجل."))
        idem = WatiIdempotency(self.env)
        scope = "universal_whatsapp_send"
        key = _clean(self.request_key) or uuid.uuid4().hex
        if not idem.acquire_durable(scope, key, ttl_seconds=3600):
            raise UserError(_("تم تنفيذ هذا الإرسال مسبقًا. لن نرسل الرسالة مرتين."))

        conversation = self._conversation(phone)
        try:
            if self.send_mode == "session":
                text = _clean(self.message)
                if not text:
                    raise UserError(_("اكتب الرسالة أولًا."))
                conversation.with_user(self.env.user).send_session_message(text)
                success_message = _("تم قبول الرسالة في WATI ✅")
            else:
                if not self.template_id or self.template_id.status != "approved":
                    raise UserError(_("اختر قالب WhatsApp معتمدًا."))
                missing = self.parameter_ids.filtered(lambda line: not _clean(line.value))
                if missing:
                    raise UserError(
                        _("أكمل قيم متغيرات القالب: %s")
                        % ", ".join(missing.mapped("param_name"))
                    )
                custom_params = [
                    {"name": line.param_name, "value": _clean(line.value)}
                    for line in self.parameter_ids.sorted("id")
                    if _clean(line.param_name)
                ]
                client = WatiClient(self.env)
                payload = {
                    "template_name": self.template_id.name,
                    "broadcast_name": f"odoo_smart_{self.source_model.replace('.', '_')}_{self.source_res_id}_{int(time.time())}",
                    "receivers": [
                        {"whatsappNumber": phone, "customParams": custom_params}
                    ],
                }
                channel = _clean(self.template_id.channel_phone_number or client.config.channel_number)
                if channel:
                    payload["channel_number"] = channel
                client.send_template_messages(payload)
                conversation.write(
                    {
                        "last_message": f"📨 {self.template_id.name}",
                        "last_message_at": fields.Datetime.now(),
                        "unread_count": 0,
                    }
                )
                success_message = _("تم قبول القالب في WATI ✅")
        except (UserError, WatiConfigurationError, WatiRequestError) as exc:
            idem.release_durable(scope, key)
            if isinstance(exc, UserError):
                raise
            detail = _clean(getattr(exc, "response_text", "") or str(exc))[:800]
            raise UserError(_("تعذر إرسال WhatsApp: %s") % detail) from exc
        except Exception:
            # Unknown failures are not released automatically: WATI may already
            # have accepted the external side effect before Odoo failed locally.
            raise

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WhatsApp"),
                "message": success_message,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }


class WatiUniversalComposeParameter(models.TransientModel):
    _name = "wati.universal.compose.parameter"
    _description = "Universal WhatsApp Template Parameter"
    _order = "id"

    wizard_id = fields.Many2one(
        "wati.universal.compose.wizard",
        required=True,
        ondelete="cascade",
    )
    param_name = fields.Char(string="المتغير", required=True, readonly=True)
    value = fields.Char(string="القيمة")


class ResPartnerWatiTimeline(models.Model):
    _inherit = "res.partner"

    wati_timeline_message_ids = fields.Many2many(
        "wati.message",
        string="WhatsApp Timeline",
        compute="_compute_wati_timeline",
    )
    wati_message_count = fields.Integer(
        string="رسائل WhatsApp",
        compute="_compute_wati_timeline",
    )
    wati_last_message_at = fields.Datetime(
        string="آخر تواصل WhatsApp",
        compute="_compute_wati_timeline",
    )

    def _wati_timeline_domain(self):
        self.ensure_one()
        phones = {
            phone
            for phone in (
                normalize_whatsapp_number(self.mobile),
                normalize_whatsapp_number(self.phone),
            )
            if phone
        }
        linked = [("conversation_id.partner_id", "=", self.id)]
        if not phones:
            return linked
        return ["|", ("conversation_id.partner_id", "=", self.id), ("wa_id", "in", sorted(phones))]

    @api.depends("mobile", "phone")
    def _compute_wati_timeline(self):
        Message = self.env["wati.message"].sudo()
        for partner in self:
            messages = Message.search(partner._wati_timeline_domain(), order="received_at desc, id desc")
            partner.wati_timeline_message_ids = messages
            partner.wati_message_count = len(messages)
            partner.wati_last_message_at = messages[:1].received_at if messages else False

    def action_open_wati_timeline(self):
        self.ensure_one()
        action = self.env.ref("wati_connector.action_wati_messages").read()[0]
        action["name"] = _("WhatsApp · %s") % self.display_name
        action["domain"] = self._wati_timeline_domain()
        return action


class ResConfigSettingsSmartButton(models.TransientModel):
    _inherit = "res.config.settings"

    def action_wati_manage_smart_buttons(self):
        return self.env.ref("wati_connector.action_wati_smart_button_locations").read()[0]
