import json
import logging
from datetime import timedelta

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .wati_automation_improvements import (
    _error_summary,
    _find_template_list,
    _template_body,
    _template_name,
    _template_param_names,
)

_logger = logging.getLogger(__name__)

_APPROVED_STATES = {"approved", "active", "enabled", "live"}
_FAILED_DELIVERY_STATES = {
    "failed",
    "error",
    "undelivered",
    "rejected",
    "expired",
}
_DELIVERED_STATES = {"delivered", "read"}
_GENERIC_TEMPLATE_NAMES = {"whatsapp", "wati", "unknown", "none", "null"}
_PREFLIGHT_TTL_MINUTES = 5


def _first_text(mapping, keys):
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for nested_key in ("code", "name", "value", "id"):
                nested = value.get(nested_key)
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    return ""


def _template_status(item):
    return _first_text(
        item,
        ("status", "approvalStatus", "templateStatus", "approval_status", "state"),
    )


def _template_language(item):
    return _first_text(
        item,
        ("language", "languageCode", "language_code", "locale"),
    )


def _template_channel(item):
    return _first_text(
        item,
        (
            "channelPhoneNumber",
            "channel_number",
            "channelNumber",
            "phoneNumber",
            "businessPhoneNumber",
        ),
    )


def _template_category(item):
    return _first_text(item, ("category", "templateCategory", "type"))


def _digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _same_channel(left, right):
    left_digits = _digits(left)
    right_digits = _digits(right)
    if not left_digits or not right_digits:
        return False
    if left_digits == right_digits:
        return True
    return left_digits[-10:] == right_digits[-10:]


def _extract_external_message_id(payload):
    priority_keys = (
        "whatsappMessageId",
        "whatsapp_message_id",
        "messageId",
        "message_id",
        "localMessageId",
    )

    def walk(value):
        if isinstance(value, dict):
            for key in priority_keys:
                candidate = value.get(key)
                if candidate not in (None, "", False):
                    return str(candidate).strip()
            for nested in value.values():
                found = walk(nested)
                if found:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = walk(nested)
                if found:
                    return found
        return ""

    return walk(payload)


def _payload_error_text(payload):
    if not isinstance(payload, dict):
        return ""
    parts = []
    for key in (
        "error",
        "errorMessage",
        "error_message",
        "message",
        "reason",
        "statusString",
    ):
        value = payload.get(key)
        if value and str(value).strip():
            parts.append(str(value).strip())
    errors = payload.get("errors")
    if errors:
        try:
            parts.append(json.dumps(errors, ensure_ascii=False, default=str))
        except Exception:
            parts.append(str(errors))
    for key in ("result", "data"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested = _payload_error_text(value)
            if nested:
                parts.append(nested)
    return " | ".join(dict.fromkeys(parts))[:1500]


def _payload_broadcast_name(payload):
    if not isinstance(payload, dict):
        return ""
    for key in (
        "broadcastName",
        "broadcast_name",
        "campaignName",
        "campaign_name",
    ):
        value = payload.get(key)
        if value:
            return str(value).strip()
    for key in ("data", "result"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            value = _payload_broadcast_name(nested)
            if value:
                return value
    return ""


def _payload_template_name(payload):
    if not isinstance(payload, dict):
        return ""
    for key in ("templateName", "template_name", "elementName"):
        value = payload.get(key)
        if value:
            return str(value).strip()
    for key in ("data", "result"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            value = _payload_template_name(nested)
            if value:
                return value
    return ""


class WatiAutomationRuleGuard(models.Model):
    _inherit = "wati.automation.rule"

    template_status = fields.Char(string="حالة القالب", readonly=True, copy=False)
    template_language = fields.Char(string="لغة القالب", readonly=True, copy=False)
    template_channel_number = fields.Char(string="قناة القالب", readonly=True, copy=False)
    template_validation_state = fields.Selection(
        [
            ("unverified", "غير مفحوص"),
            ("valid", "متحقق"),
            ("invalid", "غير صالح"),
        ],
        string="تحقق القالب",
        default="unverified",
        readonly=True,
        copy=False,
        index=True,
    )
    template_validation_message = fields.Text(
        string="نتيجة فحص القالب",
        readonly=True,
        copy=False,
    )
    template_verified_at = fields.Datetime(
        string="آخر فحص للقالب",
        readonly=True,
        copy=False,
    )
    accepted_count = fields.Integer(
        string="قيد الإرسال",
        compute="_compute_counts",
    )

    @api.depends("log_ids", "log_ids.status", "log_ids.is_test")
    def _compute_counts(self):
        Log = self.env["wati.automation.log"]
        for rule in self:
            common = [("rule_id", "=", rule.id), ("is_test", "=", False)]
            rule.run_count = Log.search_count(common)
            rule.success_count = Log.search_count(common + [("status", "=", "delivered")])
            rule.failure_count = Log.search_count(common + [("status", "=", "failed")])
            rule.accepted_count = Log.search_count(common + [("status", "in", ("accepted", "sent"))])

    @api.depends(
        "name",
        "model_id",
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
        "template_validation_state",
        "template_validation_message",
        "template_status",
        "template_language",
        "template_channel_number",
        "template_verified_at",
    )
    def _compute_ux_state(self):
        super()._compute_ux_state()
        for rule in self:
            if not rule.template_name:
                continue
            current = rule.readiness_message or ""
            if rule.template_validation_state == "valid":
                details = ["✅ القالب متحقق Live من WATI"]
                if rule.template_status:
                    details.append(f"الحالة: {rule.template_status}")
                if rule.template_language:
                    details.append(f"اللغة: {rule.template_language}")
                if rule.template_channel_number:
                    details.append(f"القناة: {rule.template_channel_number}")
                line = " · ".join(details)
                if line not in current:
                    rule.readiness_message = (current + "\n" + line).strip()
            elif rule.template_validation_state == "invalid":
                rule.readiness_state = "incomplete"
                line = "❌ " + (
                    rule.template_validation_message
                    or "القالب غير صالح للإرسال من قناة WATI الحالية."
                )
                if line not in current:
                    rule.readiness_message = (current + "\n" + line).strip()
            else:
                if rule.readiness_state == "ready":
                    rule.readiness_state = "warning"
                line = "⚠️ القالب لم يُفحص Live من WATI بعد."
                if line not in current:
                    rule.readiness_message = (current + "\n" + line).strip()

    def write(self, vals):
        guarded_fields = {"template_name", "channel_number"}
        if (
            not self.env.context.get("wati_guard_internal")
            and guarded_fields.intersection(vals)
        ):
            vals = dict(vals)
            vals.update(
                {
                    "template_status": False,
                    "template_language": False,
                    "template_channel_number": False,
                    "template_validation_state": "unverified",
                    "template_validation_message": False,
                    "template_verified_at": False,
                }
            )
        return super().write(vals)

    def _effective_channel(self):
        self.ensure_one()
        _endpoint, _token, configured_channel = self._wati_config()
        return (self.channel_number or configured_channel or "").strip()

    def _fetch_wati_templates_guarded(self):
        self.ensure_one()
        endpoint, token, _configured_channel = self._wati_config()
        if not endpoint or not token:
            raise UserError(
                _("إعدادات WATI API غير مكتملة. راجع Settings → WATI WhatsApp.")
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        rows = []
        page_size = 200
        for page_number in range(1, 11):
            try:
                response = requests.get(
                    f"{endpoint}/api/v1/getMessageTemplates",
                    headers=headers,
                    params={
                        "pageSize": page_size,
                        "pageNumber": page_number,
                    },
                    timeout=25,
                )
            except requests.RequestException as exc:
                raise UserError(_("تعذر الاتصال بـ WATI للتحقق من القالب: %s") % exc) from exc

            if not response.ok:
                detail = (response.text or response.reason or "").strip()[:900]
                raise UserError(
                    _("WATI رفض فحص القوالب (%(status)s): %(detail)s")
                    % {"status": response.status_code, "detail": detail}
                )
            try:
                page_rows = _find_template_list(response.json())
            except ValueError as exc:
                raise UserError(
                    _("WATI أعاد استجابة غير مفهومة أثناء فحص القوالب.")
                ) from exc

            if not page_rows:
                break
            rows.extend(page_rows)
            if len(page_rows) < page_size:
                break

        return rows

    def _select_live_template(self, templates=None):
        self.ensure_one()
        wanted = (self.template_name or "").strip()
        if not wanted:
            return None, _("اختر قالب WATI أولًا.")

        effective_channel = self._effective_channel()
        if not effective_channel:
            return None, _(
                "لا يوجد رقم قناة WATI. حدده في إعدادات WATI أو داخل الأتمتة قبل التفعيل."
            )

        templates = templates if templates is not None else self._fetch_wati_templates_guarded()
        candidates = [
            item
            for item in templates
            if _template_name(item).strip().casefold() == wanted.casefold()
        ]
        if not candidates:
            return None, _(
                "القالب «%s» غير موجود في حساب WATI المتصل حاليًا." % wanted
            )

        channel_aware = [item for item in candidates if _template_channel(item)]
        if channel_aware:
            matching_channel = [
                item
                for item in channel_aware
                if _same_channel(_template_channel(item), effective_channel)
            ]
            if not matching_channel:
                channels = ", ".join(
                    sorted({_template_channel(item) for item in channel_aware if _template_channel(item)})
                )
                return None, _(
                    "القالب «%(name)s» موجود، لكنه ليس على قناة WATI الحالية %(channel)s. "
                    "القنوات الموجودة للقالب: %(available)s"
                ) % {
                    "name": wanted,
                    "channel": effective_channel,
                    "available": channels or "—",
                }
            candidates = matching_channel

        statuses = [_template_status(item).strip() for item in candidates]
        approved = [
            item
            for item in candidates
            if _template_status(item).strip().casefold() in _APPROVED_STATES
        ]
        if approved:
            candidates = approved
        elif any(statuses):
            visible = ", ".join(sorted({status for status in statuses if status}))
            return None, _(
                "القالب «%(name)s» موجود لكن حالته غير معتمدة للإرسال: %(status)s"
            ) % {"name": wanted, "status": visible or "Unknown"}
        else:
            return None, _(
                "WATI لم يُرجع حالة اعتماد للقالب «%s»، لذلك تم منع التفعيل احترازيًا."
                % wanted
            )

        candidates.sort(
            key=lambda item: (
                0 if _same_channel(_template_channel(item), effective_channel) else 1,
                _template_language(item).casefold(),
                _template_name(item).casefold(),
            )
        )
        return candidates[0], ""

    def _validation_cache_fresh(self):
        self.ensure_one()
        if self.template_validation_state != "valid" or not self.template_verified_at:
            return False
        if not _same_channel(self.template_channel_number, self._effective_channel()):
            return False
        cutoff = fields.Datetime.now() - timedelta(minutes=_PREFLIGHT_TTL_MINUTES)
        return self.template_verified_at >= cutoff

    def _store_template_validation(self, item=None, error=""):
        self.ensure_one()
        if item:
            message = _("القالب موجود ومعتمد على قناة WATI الحالية.")
            vals = {
                "template_status": _template_status(item) or "APPROVED",
                "template_language": _template_language(item) or False,
                "template_channel_number": _template_channel(item) or self._effective_channel(),
                "template_validation_state": "valid",
                "template_validation_message": message,
                "template_verified_at": fields.Datetime.now(),
                "template_body": _template_body(item) or self.template_body or False,
            }
        else:
            vals = {
                "template_validation_state": "invalid",
                "template_validation_message": error or _("تعذر التحقق من القالب."),
                "template_verified_at": fields.Datetime.now(),
            }
        self.with_context(wati_guard_internal=True).write(vals)

    def _validate_template_live(self, force=False, raise_error=True):
        self.ensure_one()
        if not force and self._validation_cache_fresh():
            return True

        try:
            templates = self._fetch_wati_templates_guarded()
            item, error = self._select_live_template(templates)
        except UserError as exc:
            item = None
            error = str(exc)

        if not item:
            self._store_template_validation(error=error)
            if raise_error:
                raise ValidationError(
                    _("لا يمكن تفعيل/إرسال الأتمتة:\n%s") % (error or _("القالب غير صالح."))
                )
            return False

        self._store_template_validation(item=item)
        return True

    def action_validate_template(self):
        self.ensure_one()
        self._validate_template_live(force=True, raise_error=True)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("فحص القالب"),
                "message": self.template_validation_message,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def _validate_activation(self):
        self._validate_template_live(force=True, raise_error=True)
        super()._validate_activation()

    def action_next_step(self):
        self.ensure_one()
        if self.setup_step == "message":
            self._validate_template_live(force=True, raise_error=True)
        return super().action_next_step()

    def action_pick_template(self):
        self.ensure_one()
        effective_channel = self._effective_channel()
        if not effective_channel:
            raise UserError(
                _(
                    "حدد رقم قناة WATI في الإعدادات أولًا. "
                    "لن نعرض قوالب قبل معرفة القناة التي سترسل الرسالة."
                )
            )

        templates = self._fetch_wati_templates_guarded()
        Choice = self.env["wati.automation.template.choice"]
        Choice.search([("rule_id", "=", self.id)]).unlink()

        values = []
        for item in templates:
            name = _template_name(item).strip()
            if not name or name.casefold() in _GENERIC_TEMPLATE_NAMES:
                continue
            status = _template_status(item).strip()
            channel = _template_channel(item).strip()
            if status.casefold() not in _APPROVED_STATES:
                continue
            if channel and not _same_channel(channel, effective_channel):
                continue

            values.append(
                {
                    "rule_id": self.id,
                    "name": name,
                    "status": status,
                    "category": _template_category(item),
                    "body": _template_body(item),
                    "language": _template_language(item),
                    "channel_number": channel or effective_channel,
                }
            )

        if not values:
            raise UserError(
                _(
                    "لم أجد أي قالب Approved صالح للقناة %s. "
                    "راجع القوالب في WATI ثم حدّث الصفحة."
                )
                % effective_channel
            )

        unique = {}
        for vals in values:
            key = (
                vals["name"].casefold(),
                (vals["language"] or "").casefold(),
                _digits(vals["channel_number"]),
            )
            unique[key] = vals
        Choice.create(list(unique.values()))

        return {
            "type": "ir.actions.act_window",
            "name": _("اختر قالب WATI المعتمد"),
            "res_model": "wati.automation.template.choice",
            "view_mode": "list",
            "views": [
                (
                    self.env.ref(
                        "wati_connector.view_wati_automation_template_choice_list"
                    ).id,
                    "list",
                )
            ],
            "domain": [("rule_id", "=", self.id)],
            "target": "new",
        }

    def action_fetch_template_params(self):
        self.ensure_one()
        self._validate_template_live(force=True, raise_error=True)
        templates = self._fetch_wati_templates_guarded()
        item, error = self._select_live_template(templates)
        if not item:
            raise UserError(error)

        param_names = _template_param_names(item)
        existing = {
            (line.param_name or "").strip().casefold(): line
            for line in self.parameter_ids
            if line.param_name
        }
        created = 0
        for name in param_names:
            if name.casefold() in existing:
                continue
            self.env["wati.automation.parameter"].create(
                {
                    "rule_id": self.id,
                    "param_name": name,
                    "source_type": "field",
                }
            )
            created += 1

        self.with_context(wati_guard_internal=True).write(
            {"template_body": _template_body(item) or self.template_body or False}
        )
        self._auto_map_parameters()

        if not param_names:
            message = _("تم التحقق من القالب ولا توجد متغيرات BODY واضحة فيه.")
            notification_type = "success"
        elif created:
            message = _(
                "تم التحقق من القالب وجلب %(total)s متغيرًا، وإضافة %(created)s جديد."
            ) % {"total": len(param_names), "created": created}
            notification_type = "success"
        else:
            message = _(
                "القالب متحقق وكل متغيراته (%s) موجودة بالفعل."
            ) % len(param_names)
            notification_type = "success"

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("قالب WATI"),
                "message": message,
                "type": notification_type,
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def _execute_record(self, record):
        self.ensure_one()
        if not self.active or not record or record._name != self.model_name:
            return False
        try:
            if not self._condition_matches(record):
                return False

            Log = self.env["wati.automation.log"].sudo()
            if self.once_per_record and Log.search_count(
                [
                    ("rule_id", "=", self.id),
                    ("model_name", "=", record._name),
                    ("res_id", "=", record.id),
                    ("is_test", "=", False),
                    ("status", "in", ("accepted", "sent", "delivered")),
                ],
                limit=1,
            ):
                return False

            phone = self._recipient_phone(record)
            if not phone:
                Log.create(
                    self._log_values(
                        record,
                        "failed",
                        phone="",
                        error_message="لم يتم العثور على رقم WhatsApp في السجل.",
                    )
                )
                return False

            custom_params = [
                {
                    "name": line.param_name,
                    "value": self._parameter_value(record, line),
                }
                for line in self.parameter_ids.sorted("sequence")
                if line.param_name
            ]
            return self._send_template(record, phone, custom_params)
        except Exception as exc:
            _logger.exception("Hardened WATI automation rule %s failed", self.id)
            try:
                self.env["wati.automation.log"].sudo().create(
                    self._log_values(
                        record,
                        "failed",
                        error_message=str(exc)[:1000],
                    )
                )
            except Exception:
                _logger.exception("Could not write WATI automation failure log")
            return False

    def _send_template(self, record, phone, custom_params):
        Log = self.env["wati.automation.log"].sudo()

        if not self._validate_template_live(force=False, raise_error=False):
            Log.create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message=self.template_validation_message
                    or "القالب غير صالح للإرسال.",
                )
            )
            return False

        endpoint, token, configured_channel = self._wati_config()
        effective_channel = (
            self.channel_number or configured_channel or ""
        ).strip()
        if not endpoint or not token or not effective_channel:
            Log.create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message="إعدادات WATI API أو رقم القناة غير مكتملة.",
                )
            )
            return False

        empty_params = [
            str(item.get("name") or "").strip()
            for item in custom_params
            if not str(item.get("value") or "").strip()
        ]
        if empty_params:
            Log.create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message=(
                        "لم يتم استدعاء WATI لأن متغيرات القالب التالية بدون قيمة: "
                        + ", ".join(filter(None, empty_params))
                        + ". اربطها بحقل Odoo أو ضع قيمة احتياطية."
                    ),
                )
            )
            return False

        now_token = fields.Datetime.now().strftime("%Y%m%d%H%M%S%f")
        broadcast_name = f"odoo_auto_{self.id}_{record.id}_{now_token}"
        body = {
            "template_name": self.template_name,
            "broadcast_name": broadcast_name,
            "receivers": [
                {
                    "whatsappNumber": phone,
                    "customParams": custom_params,
                }
            ],
            "channel_number": effective_channel,
        }

        try:
            response = requests.post(
                f"{endpoint}/api/v1/sendTemplateMessages",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=25,
            )
        except requests.RequestException as exc:
            Log.create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message=f"تعذر الاتصال بـ WATI: {exc}",
                )
            )
            return False

        excerpt = (response.text or response.reason or "").strip()[:2000]
        if not response.ok:
            Log.create(
                {
                    **self._log_values(
                        record,
                        "failed",
                        phone=phone,
                        error_message=f"WATI رفض الإرسال ({response.status_code}).",
                        response_excerpt=excerpt,
                    ),
                    "broadcast_name": broadcast_name,
                    "delivery_status": "api_rejected",
                }
            )
            return False

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict) and (
            payload.get("result") is False
            or payload.get("success") is False
            or bool(payload.get("errors"))
        ):
            Log.create(
                {
                    **self._log_values(
                        record,
                        "failed",
                        phone=phone,
                        error_message=_error_summary(payload),
                        response_excerpt=excerpt,
                    ),
                    "broadcast_name": broadcast_name,
                    "delivery_status": "api_failed",
                }
            )
            return False

        external_message_id = _extract_external_message_id(payload)
        Log.create(
            {
                **self._log_values(
                    record,
                    "accepted",
                    phone=phone,
                    response_excerpt=excerpt,
                ),
                "broadcast_name": broadcast_name,
                "external_message_id": external_message_id or False,
                "delivery_status": "accepted",
            }
        )
        return True


class WatiAutomationLogGuard(models.Model):
    _inherit = "wati.automation.log"

    status = fields.Selection(
        selection_add=[
            ("accepted", "تم قبول الطلب"),
            ("delivered", "تم التسليم"),
        ],
        ondelete={
            "accepted": "cascade",
            "delivered": "cascade",
        },
    )
    broadcast_name = fields.Char(
        string="Broadcast",
        readonly=True,
        index=True,
    )
    external_message_id = fields.Char(
        string="WhatsApp Message ID",
        readonly=True,
        index=True,
    )
    delivery_status = fields.Char(
        string="حالة التسليم",
        readonly=True,
        index=True,
    )


class WatiAutomationTemplateChoiceGuard(models.TransientModel):
    _inherit = "wati.automation.template.choice"

    language = fields.Char(string="اللغة", readonly=True)
    channel_number = fields.Char(string="قناة WATI", readonly=True)

    def action_select(self):
        self.ensure_one()
        rule = self.rule_id
        rule.with_context(wati_guard_internal=True).write(
            {
                "template_name": self.name,
                "template_body": self.body or False,
                "template_status": self.status or False,
                "template_language": self.language or False,
                "template_channel_number": self.channel_number or rule._effective_channel(),
                "template_validation_state": "unverified",
                "template_validation_message": False,
                "template_verified_at": False,
            }
        )
        rule.action_fetch_template_params()
        return {
            "type": "ir.actions.act_window",
            "name": rule.name,
            "res_model": "wati.automation.rule",
            "res_id": rule.id,
            "view_mode": "form",
            "target": "current",
        }


class WatiWebhookEventAutomationGuard(models.Model):
    _inherit = "wati.webhook.event"

    @api.model
    def ingest(self, payload):
        result = super().ingest(payload)
        try:
            self._update_automation_delivery(payload)
        except Exception:
            _logger.exception("Could not correlate WATI webhook with automation log")
        return result

    @api.model
    def _update_automation_delivery(self, payload):
        if not isinstance(payload, dict):
            return

        status_raw = str(
            payload.get("statusString")
            or payload.get("status")
            or payload.get("eventType")
            or payload.get("type")
            or ""
        ).strip()
        status = status_raw.casefold()
        if not status:
            return

        is_delivered = any(token in status for token in _DELIVERED_STATES)
        is_failed = any(token in status for token in _FAILED_DELIVERY_STATES)
        is_sent = "sent" in status
        if not (is_delivered or is_failed or is_sent):
            return

        external_id = str(
            payload.get("whatsappMessageId")
            or payload.get("id")
            or _extract_external_message_id(payload)
            or ""
        ).strip()
        broadcast_name = _payload_broadcast_name(payload)
        template_name = _payload_template_name(payload)
        wa_id = str(
            payload.get("waId")
            or payload.get("whatsappNumber")
            or payload.get("phoneNumber")
            or ""
        ).strip()
        phone = ""
        if wa_id:
            digits = _digits(wa_id)
            if digits.startswith("00"):
                digits = digits[2:]
            if digits.startswith("0") and len(digits) >= 9:
                digits = "966" + digits[1:]
            elif len(digits) == 9 and digits.startswith("5"):
                digits = "966" + digits
            phone = digits

        Log = self.env["wati.automation.log"].sudo()
        log = Log.browse()

        if external_id:
            log = Log.search(
                [
                    ("external_message_id", "=", external_id),
                    ("status", "in", ("accepted", "sent", "delivered")),
                ],
                order="create_date desc, id desc",
                limit=1,
            )
        if not log and broadcast_name:
            log = Log.search(
                [
                    ("broadcast_name", "=", broadcast_name),
                    ("status", "in", ("accepted", "sent", "delivered")),
                ],
                order="create_date desc, id desc",
                limit=1,
            )
        if not log and external_id:
            log = Log.search(
                [
                    ("response_excerpt", "ilike", external_id),
                    ("status", "in", ("accepted", "sent", "delivered")),
                ],
                order="create_date desc, id desc",
                limit=1,
            )
        if not log and phone:
            cutoff = fields.Datetime.now() - timedelta(minutes=30)
            domain = [
                ("phone", "=", phone),
                ("status", "in", ("accepted", "sent", "delivered")),
                ("create_date", ">=", cutoff),
            ]
            if template_name:
                domain.append(("template_name", "=", template_name))
            candidates = Log.search(
                domain,
                order="create_date desc, id desc",
                limit=2,
            )
            if len(candidates) == 1:
                log = candidates

        if not log:
            return

        values = {
            "delivery_status": status_raw[:255],
        }
        if external_id and not log.external_message_id:
            values["external_message_id"] = external_id

        if is_delivered:
            values.update(
                {
                    "status": "delivered",
                    "error_message": False,
                }
            )
        elif is_failed:
            error_text = _payload_error_text(payload) or (
                "فشل تسليم الرسالة في WATI/WhatsApp: " + status_raw
            )
            values.update(
                {
                    "status": "failed",
                    "error_message": error_text[:1500],
                }
            )
        else:
            if log.status == "sent":
                values["status"] = "accepted"

        log.write(values)

        if not is_failed or not log.rule_id:
            return

        error_text = (values.get("error_message") or "").casefold()
        template_failure = (
            "132001" in error_text
            or "template name does not exist" in error_text
            or ("template" in error_text and "translation" in error_text)
        )
        if template_failure:
            message = (
                "تم إيقاف الأتمتة تلقائيًا لأن WhatsApp/WATI رفض القالب "
                f"«{log.template_name}». السبب: {values.get('error_message') or status_raw}"
            )[:1500]
            log.rule_id.with_context(wati_guard_internal=True).write(
                {
                    "active": False,
                    "template_validation_state": "invalid",
                    "template_validation_message": message,
                    "template_verified_at": fields.Datetime.now(),
                }
            )
