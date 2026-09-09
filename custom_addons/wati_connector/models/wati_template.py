import json
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.feature_access import ensure_feature_access
from ..services.template_catalog import (
    clean,
    extract_placeholders,
    find_template_list,
    normalize_quality,
    normalize_status,
    normalize_template,
    placeholder_mode,
)


_TEMPLATE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_NAMED_VARIABLE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

_STATUS_SELECTION = [
    ("draft", "مسودة"),
    ("pending", "قيد مراجعة Meta"),
    ("pending_internal", "قيد المعالجة"),
    ("approved", "معتمد"),
    ("rejected", "مرفوض"),
    ("paused", "متوقف مؤقتًا"),
    ("disabled", "معطل"),
    ("deleted", "محذوف"),
    ("unknown", "غير معروف"),
]

_QUALITY_SELECTION = [
    ("unknown", "غير معروف"),
    ("green", "جيد"),
    ("yellow", "متوسط"),
    ("red", "منخفض"),
]

_CATEGORY_SELECTION = [
    ("UTILITY", "خدمي (Utility)"),
    ("MARKETING", "تسويقي (Marketing)"),
    ("AUTHENTICATION", "مصادقة (Authentication)"),
    ("UNKNOWN", "غير معروف"),
]


class WatiTemplate(models.Model):
    _name = "wati.template"
    _description = "WhatsApp Message Template"
    _order = "write_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="اسم القالب",
        required=True,
        index=True,
        help="اسم تقني ثابت بصيغة lowercase مع أرقام وشرطة سفلية فقط.",
    )
    language = fields.Char(
        string="اللغة",
        required=True,
        default="ar",
        index=True,
        help="رمز اللغة المستخدم في WATI/Meta، مثل ar أو en.",
    )
    category = fields.Selection(
        _CATEGORY_SELECTION,
        string="التصنيف",
        required=True,
        default="UTILITY",
        index=True,
    )
    sub_category = fields.Char(
        string="النوع الفرعي",
        default="STANDARD",
        readonly=True,
    )
    status = fields.Selection(
        _STATUS_SELECTION,
        string="الحالة",
        default="draft",
        required=True,
        readonly=True,
        index=True,
    )
    quality = fields.Selection(
        _QUALITY_SELECTION,
        string="جودة القالب",
        default="unknown",
        required=True,
        readonly=True,
        index=True,
    )
    source = fields.Selection(
        [("odoo", "تم إنشاؤه في Odoo"), ("wati", "مستورَد من WATI")],
        string="المصدر",
        default="odoo",
        required=True,
        readonly=True,
        index=True,
    )

    body = fields.Text(
        string="نص الرسالة",
        required=True,
        help="استخدم المتغيرات بصيغة {{name}} أو {{1}}.",
    )
    footer = fields.Char(string="التذييل")
    header_type = fields.Char(string="نوع الترويسة", readonly=True)
    header_text = fields.Char(string="نص الترويسة", readonly=True)
    buttons_json = fields.Text(string="بيانات الأزرار", readonly=True)

    variable_ids = fields.One2many(
        "wati.template.variable",
        "template_id",
        string="متغيرات القالب",
        copy=True,
    )
    variable_count = fields.Integer(
        string="عدد المتغيرات",
        compute="_compute_variable_count",
        store=True,
    )
    preview_text = fields.Text(
        string="معاينة",
        compute="_compute_preview_text",
    )

    wati_template_id = fields.Char(string="WATI Template ID", readonly=True, index=True)
    meta_template_id = fields.Char(string="Meta Template ID", readonly=True, index=True)
    waba_id = fields.Char(string="WABA ID", readonly=True, index=True)
    channel_phone_number = fields.Char(
        string="قناة WhatsApp",
        readonly=True,
        index=True,
    )

    rejection_reason = fields.Text(string="سبب الرفض", readonly=True)
    submitted_at = fields.Datetime(string="تاريخ الإرسال للمراجعة", readonly=True)
    last_synced_at = fields.Datetime(string="آخر مزامنة", readonly=True)
    provider_request = fields.Text(string="آخر طلب إلى WATI", readonly=True)
    provider_response = fields.Text(string="آخر استجابة من WATI", readonly=True)
    last_error = fields.Text(string="آخر خطأ", readonly=True)
    active = fields.Boolean(default=True)

    @api.depends("variable_ids")
    def _compute_variable_count(self):
        for record in self:
            record.variable_count = len(record.variable_ids)

    @api.depends("body", "variable_ids.name", "variable_ids.sample_value")
    def _compute_preview_text(self):
        for record in self:
            preview = record.body or ""
            for line in record.variable_ids.sorted("position"):
                if line.name and line.sample_value:
                    preview = re.sub(
                        r"{{\s*%s\s*}}" % re.escape(line.name),
                        str(line.sample_value),
                        preview,
                    )
            record.preview_text = preview

    @api.onchange("body")
    def _onchange_body(self):
        for record in self:
            record._sync_variable_lines(in_memory=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._sync_variable_lines()
        return records

    def write(self, vals):
        result = super().write(vals)
        if "body" in vals and not self.env.context.get("wati_skip_variable_sync"):
            for record in self:
                record._sync_variable_lines()
        return result

    def copy(self, default=None):
        self.ensure_one()
        base = f"{self.name}_copy"
        candidate = base
        suffix = 2
        while self.search_count([("name", "=", candidate), ("language", "=", self.language)]):
            candidate = f"{base}_{suffix}"
            suffix += 1
        values = {
            "name": candidate,
            "source": "odoo",
            "status": "draft",
            "quality": "unknown",
            "wati_template_id": False,
            "meta_template_id": False,
            "waba_id": False,
            "channel_phone_number": False,
            "rejection_reason": False,
            "submitted_at": False,
            "last_synced_at": False,
            "provider_request": False,
            "provider_response": False,
            "last_error": False,
        }
        values.update(default or {})
        return super().copy(values)

    @api.constrains("name", "language")
    def _check_identity(self):
        for record in self:
            name = clean(record.name)
            if len(name) > 512 or not _TEMPLATE_NAME_RE.fullmatch(name):
                raise ValidationError(
                    _(
                        "اسم القالب يجب أن يبدأ بحرف صغير ويحتوي فقط على أحرف إنجليزية صغيرة وأرقام وشرطة سفلية (_)."
                    )
                )
            duplicate = self.search_count(
                [
                    ("id", "!=", record.id),
                    ("name", "=", name),
                    ("language", "=", clean(record.language)),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    _("يوجد قالب بنفس الاسم واللغة بالفعل. الاسم واللغة يجب أن يكونا فريدين.")
                )

    @api.constrains("body", "footer")
    def _check_content_limits(self):
        for record in self:
            body = record.body or ""
            footer = record.footer or ""
            if not body.strip():
                raise ValidationError(_("نص القالب لا يمكن أن يكون فارغًا."))
            if len(body) > 1024:
                raise ValidationError(_("نص القالب تجاوز 1024 حرفًا."))
            if len(footer) > 60:
                raise ValidationError(_("تذييل القالب تجاوز 60 حرفًا."))

    @api.constrains("body")
    def _check_placeholder_contract(self):
        for record in self:
            tokens = extract_placeholders(record.body)
            mode = placeholder_mode(tokens)
            if mode == "mixed":
                raise ValidationError(
                    _("لا تخلط بين متغيرات مرقمة مثل {{1}} ومتغيرات مسماة مثل {{name}} في القالب نفسه.")
                )
            if mode == "positional":
                expected = [str(index) for index in range(1, len(tokens) + 1)]
                if tokens != expected:
                    raise ValidationError(
                        _("المتغيرات المرقمة يجب أن تكون متسلسلة بالترتيب: {{1}}, {{2}}, {{3}} ...")
                    )
            if mode == "named":
                invalid = [token for token in tokens if not _NAMED_VARIABLE_RE.fullmatch(token)]
                if invalid:
                    raise ValidationError(
                        _("اسم المتغير غير صالح: %s. استخدم أحرفًا إنجليزية وأرقامًا وشرطة سفلية فقط.")
                        % invalid[0]
                    )

    def _sync_variable_lines(self, *, in_memory=False):
        for record in self:
            tokens = extract_placeholders(record.body)
            existing = {line.name: line for line in record.variable_ids if line.name}

            if in_memory:
                samples = {
                    name: line.sample_value or ""
                    for name, line in existing.items()
                }
                record.variable_ids = [(5, 0, 0)] + [
                    (
                        0,
                        0,
                        {
                            "name": token,
                            "position": position,
                            "sample_value": samples.get(token, ""),
                        },
                    )
                    for position, token in enumerate(tokens, start=1)
                ]
                continue

            commands = []
            for position, token in enumerate(tokens, start=1):
                line = existing.pop(token, None)
                if line:
                    if line.position != position:
                        commands.append((1, line.id, {"position": position}))
                else:
                    commands.append(
                        (0, 0, {"name": token, "position": position, "sample_value": ""})
                    )
            for line in existing.values():
                commands.append((2, line.id, 0))

            if commands:
                record.with_context(wati_skip_variable_sync=True).write(
                    {"variable_ids": commands}
                )

    def _assert_can_submit(self):
        self.ensure_one()
        ensure_feature_access(self.env, "templates")
        if self.source != "odoo":
            raise UserError(
                _("القالب المستورَد من WATI مرآة لحالة Meta. أنشئ نسخة قابلة للتعديل أولًا.")
            )
        if self.status != "draft":
            raise UserError(_("يمكن إرسال المسودات فقط إلى Meta للمراجعة."))
        if self.category not in {"UTILITY", "MARKETING"}:
            raise UserError(
                _(
                    "إنشاء قوالب المصادقة والأنواع المتقدمة يحتاج عقدًا مختلفًا مع Meta/WATI. النسخة الحالية تدعم STANDARD Utility وMarketing فقط لتجنب إرسال Payload غير موثوق."
                )
            )
        self._check_identity()
        self._check_content_limits()
        self._check_placeholder_contract()
        self._sync_variable_lines()
        missing = self.variable_ids.filtered(lambda line: not clean(line.sample_value))
        if missing:
            raise UserError(
                _("أدخل قيمة مثال لكل متغير قبل الإرسال للمراجعة. المتغير الناقص: %s")
                % missing[0].name
            )

    def _build_submission_payload(self):
        self.ensure_one()
        return {
            "type": "template",
            "category": self.category,
            "subCategory": "STANDARD",
            "buttonsType": "NONE",
            "buttons": [],
            "footer": self.footer or "",
            "elementName": self.name,
            "language": self.language,
            "header": {},
            "body": self.body,
            "customParams": [
                {"name": line.name, "value": line.sample_value or ""}
                for line in self.variable_ids.sorted("position")
            ],
            "creationMethod": 0,
        }

    def action_submit_for_approval(self):
        self.ensure_one()
        self._assert_can_submit()
        payload = self._build_submission_payload()
        request_snapshot = json.dumps(payload, ensure_ascii=False, indent=2)

        try:
            response = WatiClient(self.env).create_whatsapp_template(payload)
            try:
                response_payload = response.json()
            except ValueError:
                response_payload = {"raw": response.text or ""}
        except (WatiConfigurationError, WatiRequestError) as exc:
            message = (
                getattr(exc, "response_text", "")
                or str(exc)
                or _("تعذر إرسال القالب إلى WATI.")
            )
            self.sudo().write(
                {
                    "provider_request": request_snapshot,
                    "last_error": clean(message)[:3000],
                }
            )
            raise UserError(_("تعذر إرسال القالب إلى WATI: %s") % clean(message)[:1200]) from exc

        status_value = "pending"
        if isinstance(response_payload, dict):
            candidate = response_payload.get("status")
            if candidate is None:
                candidate = response_payload.get("templateStatus")
            normalized = normalize_status(candidate)
            if normalized != "unknown":
                status_value = normalized

        self.sudo().write(
            {
                "status": status_value,
                "submitted_at": fields.Datetime.now(),
                "last_synced_at": fields.Datetime.now(),
                "provider_request": request_snapshot,
                "provider_response": json.dumps(
                    response_payload, ensure_ascii=False, indent=2, default=str
                ),
                "last_error": False,
            }
        )
        self._apply_provider_identifiers(response_payload)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("تم إرسال القالب للمراجعة"),
                "message": _(
                    "أرسل Odoo القالب إلى WATI بنجاح. ستتحدث حالة Meta تلقائيًا عبر Webhook أو يمكنك الضغط على «تحديث الحالة»."
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def _apply_provider_identifiers(self, payload):
        self.ensure_one()
        if not isinstance(payload, dict):
            return
        nested = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        merged = dict(nested)
        merged.update(payload)
        values = {}
        mapping = {
            "wati_template_id": ("watiTemplateId", "_id"),
            "meta_template_id": ("templateId", "metaTemplateId"),
            "waba_id": ("wabaId", "whatsappBusinessAccountId"),
            "channel_phone_number": ("channelPhoneNumber", "channelNumber"),
        }
        for field_name, keys in mapping.items():
            for key in keys:
                value = clean(merged.get(key))
                if value:
                    values[field_name] = value
                    break
        if values:
            self.sudo().write(values)

    @api.model
    def _fetch_remote_templates(self):
        client = WatiClient(self.env)
        all_items = []
        page_size = 200
        for page_number in range(1, 21):
            response = client.get_message_templates(
                page_size=page_size,
                page_number=page_number,
            )
            try:
                payload = response.json()
            except ValueError as exc:
                raise UserError(_("WATI أعاد استجابة غير مفهومة أثناء مزامنة القوالب.")) from exc
            items = find_template_list(payload)
            if not items:
                break
            all_items.extend(items)
            if len(items) < page_size:
                break
        return all_items

    @api.model
    def action_sync_from_wati(self):
        ensure_feature_access(self.env, "templates")
        try:
            items = self._fetch_remote_templates()
        except (WatiConfigurationError, WatiRequestError) as exc:
            detail = clean(getattr(exc, "response_text", "") or str(exc))[:1200]
            raise UserError(_("تعذر مزامنة القوالب من WATI: %s") % detail) from exc

        synced = 0
        now = fields.Datetime.now()
        for item in items:
            normalized = normalize_template(item)
            if not normalized:
                continue

            template = self.sudo().search(
                [
                    ("name", "=", normalized["name"]),
                    ("language", "=", normalized["language"]),
                ],
                limit=1,
            )
            values = self._remote_values(normalized, now)
            if template:
                template.write(values)
            else:
                values.update(
                    {
                        "name": normalized["name"],
                        "language": normalized["language"],
                        "source": "wati",
                    }
                )
                template = self.sudo().create(values)
            template._sync_readonly_variables(normalized["custom_params"])
            synced += 1

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("مزامنة قوالب WhatsApp"),
                "message": _("تمت مزامنة %s قالبًا من WATI.") % synced,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    @api.model
    def _remote_values(self, normalized, now=None):
        category = normalized["category"] or "UNKNOWN"
        if category not in {"UTILITY", "MARKETING", "AUTHENTICATION"}:
            category = "UNKNOWN"
        return {
            "category": category,
            "sub_category": normalized["sub_category"] or "STANDARD",
            "status": normalized["status"],
            "quality": normalized["quality"],
            "body": normalized["body"] or "—",
            "footer": normalized["footer"] or False,
            "header_type": normalized["header_type"] or False,
            "header_text": normalized["header_text"] or False,
            "buttons_json": normalized["buttons_json"] or "[]",
            "wati_template_id": normalized["wati_template_id"] or False,
            "meta_template_id": normalized["meta_template_id"] or False,
            "waba_id": normalized["waba_id"] or False,
            "channel_phone_number": normalized["channel_phone_number"] or False,
            "last_synced_at": now or fields.Datetime.now(),
            "provider_response": json.dumps(
                normalized["raw"], ensure_ascii=False, indent=2, default=str
            ),
            "last_error": False,
        }

    def _sync_readonly_variables(self, names):
        self.ensure_one()
        names = [clean(name) for name in names if clean(name)]
        current_samples = {
            line.name: line.sample_value for line in self.variable_ids if line.name
        }
        commands = [(5, 0, 0)]
        for position, name in enumerate(names, start=1):
            commands.append(
                (
                    0,
                    0,
                    {
                        "position": position,
                        "name": name,
                        "sample_value": current_samples.get(name, ""),
                    },
                )
            )
        self.with_context(wati_skip_variable_sync=True).sudo().write(
            {"variable_ids": commands}
        )

    def action_refresh_status(self):
        ensure_feature_access(self.env, "templates")
        selected = {(record.name, record.language): record for record in self}
        try:
            items = self._fetch_remote_templates()
        except (WatiConfigurationError, WatiRequestError) as exc:
            detail = clean(getattr(exc, "response_text", "") or str(exc))[:1200]
            raise UserError(_("تعذر تحديث حالة القالب من WATI: %s") % detail) from exc

        found = set()
        now = fields.Datetime.now()
        for item in items:
            normalized = normalize_template(item)
            if not normalized:
                continue
            key = (normalized["name"], normalized["language"])
            record = selected.get(key)
            if not record:
                continue
            record.sudo().write(record._remote_values(normalized, now))
            record._sync_readonly_variables(normalized["custom_params"])
            found.add(key)

        missing = set(selected) - found
        for key in missing:
            selected[key].sudo().write(
                {
                    "last_synced_at": now,
                    "last_error": _("لم يظهر هذا القالب في نتيجة WATI الحالية."),
                }
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("تحديث حالة القوالب"),
                "message": _("تم تحديث %s من %s قالبًا.") % (len(found), len(selected)),
                "type": "success" if found else "warning",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def action_delete_remote(self):
        for record in self:
            ensure_feature_access(record.env, "templates")
            if record.status == "draft" and not record.wati_template_id and not record.meta_template_id:
                record.unlink()
                continue
            if not record.waba_id:
                raise UserError(
                    _(
                        "لا يمكن حذف القالب من Meta بدون WABA ID. نفّذ «تحديث الحالة» أو «مزامنة من WATI» أولًا."
                    )
                )
            try:
                response = WatiClient(record.env).delete_whatsapp_template(
                    record.waba_id,
                    record.name,
                    record.language,
                )
                try:
                    payload = response.json()
                except ValueError:
                    payload = {"raw": response.text or ""}
            except (WatiConfigurationError, WatiRequestError) as exc:
                detail = clean(getattr(exc, "response_text", "") or str(exc))[:1200]
                record.sudo().write({"last_error": detail})
                raise UserError(_("تعذر حذف القالب من WATI/Meta: %s") % detail) from exc

            record.sudo().write(
                {
                    "status": "deleted",
                    "last_synced_at": fields.Datetime.now(),
                    "provider_response": json.dumps(
                        payload, ensure_ascii=False, indent=2, default=str
                    ),
                    "last_error": False,
                }
            )
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_duplicate_draft(self):
        self.ensure_one()
        ensure_feature_access(self.env, "templates")
        duplicate = self.copy()
        action = self.env.ref("wati_connector.action_wati_templates").read()[0]
        action.update(
            {
                "view_mode": "form",
                "res_id": duplicate.id,
                "views": [(False, "form")],
            }
        )
        return action

    @api.model
    def apply_template_webhook(self, payload):
        if not isinstance(payload, dict):
            return False
        event_type = clean(payload.get("eventType"))
        if event_type not in {
            "templateReviewed",
            "templateQualityUpdated",
            "templateCategoryUpdated",
        }:
            return False

        meta_id = clean(payload.get("templateId"))
        wati_id = clean(payload.get("watiTemplateId"))
        name = clean(payload.get("templateName"))
        record = self.browse()

        if meta_id:
            record = self.sudo().search([("meta_template_id", "=", meta_id)], limit=1)
        if not record and wati_id:
            record = self.sudo().search([("wati_template_id", "=", wati_id)], limit=1)
        if not record and name:
            candidates = self.sudo().search([("name", "=", name)], limit=2)
            if len(candidates) == 1:
                record = candidates

        if not record:
            return False

        values = {
            "last_synced_at": fields.Datetime.now(),
            "provider_response": json.dumps(
                payload, ensure_ascii=False, indent=2, default=str
            ),
            "last_error": False,
        }
        if meta_id:
            values["meta_template_id"] = meta_id
        if wati_id:
            values["wati_template_id"] = wati_id
        if clean(payload.get("wabaId")):
            values["waba_id"] = clean(payload.get("wabaId"))
        if clean(payload.get("channelPhoneNumber")):
            values["channel_phone_number"] = clean(payload.get("channelPhoneNumber"))

        if event_type == "templateReviewed":
            values["status"] = normalize_status(payload.get("newTemplateStatus"))
            rejection = clean(
                payload.get("rejectionReason")
                or payload.get("reason")
                or payload.get("errorMessage")
            )
            values["rejection_reason"] = rejection or False

        elif event_type == "templateQualityUpdated":
            values["quality"] = normalize_quality(payload.get("newTemplateQuality"))

        elif event_type == "templateCategoryUpdated":
            category = clean(payload.get("newTemplateCategory")).upper()
            values["category"] = (
                category
                if category in {"UTILITY", "MARKETING", "AUTHENTICATION"}
                else "UNKNOWN"
            )

        record.sudo().write(values)
        return True


class WatiTemplateVariable(models.Model):
    _name = "wati.template.variable"
    _description = "WhatsApp Template Variable"
    _order = "position, id"

    template_id = fields.Many2one(
        "wati.template",
        string="القالب",
        required=True,
        ondelete="cascade",
        index=True,
    )
    position = fields.Integer(string="الترتيب", required=True, default=1)
    name = fields.Char(string="المتغير", required=True)
    sample_value = fields.Char(
        string="قيمة المثال",
        help="مثال واقعي ترسله Meta أثناء مراجعة القالب.",
    )

    @api.constrains("name")
    def _check_name(self):
        for record in self:
            if not clean(record.name):
                raise ValidationError(_("اسم المتغير لا يمكن أن يكون فارغًا."))
