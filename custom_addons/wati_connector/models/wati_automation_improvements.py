import json
import re
import time

from odoo import _, models
from odoo.exceptions import UserError

from ..services.client import WatiClient
from ..services.config import WatiConfig
from ..services.exceptions import WatiError


def _find_template_list(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("messageTemplates", "templates", "items", "results", "result", "data", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _find_template_list(value)
            if nested:
                return nested
    for value in payload.values():
        if isinstance(value, (dict, list)):
            nested = _find_template_list(value)
            if nested:
                return nested
    return []


def _first(mapping, keys):
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _template_name(item):
    return _first(item, ("elementName", "templateName", "template_name", "name"))


def _template_body(item):
    if not isinstance(item, dict):
        return ""
    body = item.get("body")
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        text = _first(body, ("text", "body", "content"))
        if text:
            return text
    components = item.get("components")
    if isinstance(components, list):
        for component in components:
            if not isinstance(component, dict):
                continue
            if str(component.get("type") or "").upper() == "BODY":
                text = _first(component, ("text", "body", "content"))
                if text:
                    return text
    return ""


def _template_param_names(item):
    names = []
    if not isinstance(item, dict):
        return names
    for key in ("customParams", "params", "parameters"):
        raw = item.get(key)
        if not isinstance(raw, list):
            continue
        for entry in raw:
            if isinstance(entry, dict):
                name = _first(entry, ("name", "paramName", "parameterName", "key", "field"))
            elif isinstance(entry, str):
                name = entry.strip()
            else:
                name = ""
            if name and name not in names:
                names.append(name)
    for token in re.findall(r"{{\s*([^{}]+?)\s*}}", _template_body(item) or ""):
        token = token.strip()
        if token and token not in names:
            names.append(token)
    return names


def _error_summary(payload):
    if not isinstance(payload, dict):
        return "WATI أعاد نتيجة فشل غير مفهومة."
    errors = payload.get("errors")
    if isinstance(errors, dict):
        parts = []
        if errors.get("error"):
            parts.append(str(errors["error"]))
        invalid_numbers = errors.get("invalidWhatsappNumbers") or []
        invalid_params = errors.get("invalidCustomParameters") or []
        if invalid_numbers:
            parts.append("أرقام غير صالحة: " + ", ".join(map(str, invalid_numbers)))
        if invalid_params:
            parts.append("متغيرات القالب: " + " | ".join(map(str, invalid_params)))
        if parts:
            return " — ".join(parts)
    if errors:
        try:
            return json.dumps(errors, ensure_ascii=False, default=str)[:1000]
        except Exception:
            return str(errors)[:1000]
    return "WATI أعاد result=false؛ لم يتم إرسال الرسالة."


class WatiAutomationRuleImprovements(models.Model):
    _inherit = "wati.automation.rule"

    def _parameter_value(self, record, line):
        value = super()._parameter_value(record, line)
        if (value is None or not str(value).strip()) and line.static_value:
            return line.static_value
        return value

    def action_fetch_template_params(self):
        self.ensure_one()
        if not self.template_name:
            raise UserError(_("اكتب أو اختر اسم WATI Template أولًا."))
        try:
            response = WatiClient(self.env).get_message_templates(page_size=200, page_number=1)
            payload = response.json()
        except WatiError as exc:
            raise UserError(_("تعذر الاتصال بـ WATI لجلب القالب: %s", exc)) from exc
        except ValueError as exc:
            raise UserError(_("WATI أعاد استجابة غير مفهومة عند جلب القوالب.")) from exc

        wanted = (self.template_name or "").strip().casefold()
        template = next(
            (item for item in _find_template_list(payload) if _template_name(item).casefold() == wanted),
            None,
        )
        if not template:
            raise UserError(_("لم أجد Template باسم %s داخل حساب WATI.", self.template_name))

        param_names = _template_param_names(template)
        existing = {
            (line.param_name or "").strip().casefold(): line
            for line in self.parameter_ids
            if line.param_name
        }
        created = 0
        for name in param_names:
            if name.casefold() in existing:
                continue
            self.env["wati.automation.parameter"].create({
                "rule_id": self.id,
                "param_name": name,
                "source_type": "field",
            })
            created += 1

        if not param_names:
            message = _("تم العثور على القالب، ولا توجد متغيرات BODY واضحة فيه.")
            notification_type = "warning"
        elif created:
            message = _(
                "تم جلب %(total)s متغيرًا من WATI وإضافة %(created)s متغير جديد. اربط المتغيرات الجديدة بحقول Odoo.",
                total=len(param_names),
                created=created,
            )
            notification_type = "success"
        else:
            message = _("القالب يحتوي على %s متغيرات، وكلها موجودة بالفعل في القاعدة.", len(param_names))
            notification_type = "success"

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("متغيرات WATI Template"),
                "message": message,
                "type": notification_type,
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def _send_template(self, record, phone, custom_params):
        Log = self.env["wati.automation.log"].sudo()
        empty_params = [
            str(item.get("name") or "").strip()
            for item in custom_params
            if not str(item.get("value") or "").strip()
        ]
        if empty_params:
            Log.create(self._log_values(
                record,
                "failed",
                phone=phone,
                error_message=(
                    "لم يتم استدعاء WATI لأن متغيرات القالب التالية بدون قيمة: "
                    + ", ".join(filter(None, empty_params))
                    + ". اربطها بحقل Odoo أو ضع قيمة احتياطية."
                ),
            ))
            return False

        body = {
            "template_name": self.template_name,
            "broadcast_name": f"odoo_auto_{self.id}_{record.id}_{int(time.time())}",
            "receivers": [{"whatsappNumber": phone, "customParams": custom_params}],
        }
        channel = (self.channel_number or WatiConfig(self.env).channel_number or "").strip()
        if channel:
            body["channel_number"] = channel

        try:
            response = WatiClient(self.env).send_template_messages(body)
        except WatiError as exc:
            excerpt = getattr(exc, "response_text", "") or str(exc)
            Log.create(self._log_values(
                record,
                "failed",
                phone=phone,
                error_message=str(exc),
                response_excerpt=excerpt[:1200],
            ))
            return False

        excerpt = (response.text or response.reason or "").strip()[:1200]
        try:
            response_payload = response.json()
        except ValueError:
            response_payload = None

        if isinstance(response_payload, dict) and (
            response_payload.get("result") is False
            or response_payload.get("success") is False
        ):
            Log.create(self._log_values(
                record,
                "failed",
                phone=phone,
                error_message=_error_summary(response_payload),
                response_excerpt=excerpt,
            ))
            return False

        Log.create(self._log_values(record, "sent", phone=phone, response_excerpt=excerpt))
        return True
