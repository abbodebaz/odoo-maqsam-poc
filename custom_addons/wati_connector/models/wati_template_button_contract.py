import json
import re
from urllib.parse import urlparse

from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError

from ..services.template_catalog import clean


_BUTTON_FIELDS = {
    "builder_button_type",
    "builder_button_text",
    "builder_button_url",
    "builder_button_phone",
}
_PHONE_RE = re.compile(r"^\+?[1-9]\d{6,14}$")


class WatiTemplateButtonContract(models.Model):
    """Use the button contract returned by WATI itself as source of truth.

    WATI's create-template reference exposes ``buttons`` and ``buttonsType``
    but does not expand the nested button object. The provider's own
    ``getMessageTemplates`` response does: every button carries a ``parameter``
    object. Keeping authoring and import on that same shape avoids guessing and
    makes round-tripping deterministic.
    """

    _inherit = "wati.template"

    @api.model
    def _normalize_button_url(self, value, *, required=False):
        url = clean(value)
        if not url:
            if required:
                raise UserError(_("أدخل رابط زر زيارة الموقع."))
            return ""
        if "://" not in url:
            url = "https://%s" % url
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValidationError(
                _("رابط الزر غير صالح. استخدم رابطًا كاملًا مثل https://example.com")
            )
        return url

    @api.model
    def _normalize_button_phone(self, value, *, required=False):
        phone = re.sub(r"[\s\-()]+", "", clean(value))
        if not phone:
            if required:
                raise UserError(_("أدخل رقم الهاتف الخاص بزر الاتصال."))
            return ""
        if not _PHONE_RE.fullmatch(phone):
            raise ValidationError(
                _("رقم الاتصال غير صالح. استخدم رقمًا دوليًا مثل +966500000000.")
            )
        return phone

    @api.model
    def _provider_button_parameter(self, *, text, url=None, phone=None, url_type="none"):
        """Mirror the parameter object observed in live WATI templates."""
        return {
            "text": clean(text),
            "phoneNumber": phone,
            "url": url,
            "urlOriginal": None,
            "urlType": url_type,
            "buttonParamMapping": None,
            "copyOfferCode": None,
            "orderDetails": None,
            "signatureHash": None,
            "packageName": None,
            "flowId": None,
            "flowAction": None,
            "navigateScreen": None,
        }

    @api.model
    def _button_payload_from_values(self, values):
        values = dict(values or {})
        button_type = values.get("builder_button_type") or "NONE"
        text = clean(values.get("builder_button_text"))

        if button_type == "NONE":
            return []
        if button_type == "QUICK_REPLY":
            return [
                {
                    "type": "quick_reply",
                    "parameter": self._provider_button_parameter(
                        text=text,
                        url=None,
                        phone=None,
                        url_type="none",
                    ),
                }
            ]
        if button_type == "URL":
            url = self._normalize_button_url(values.get("builder_button_url"))
            return [
                {
                    "type": "url",
                    "parameter": self._provider_button_parameter(
                        text=text,
                        url=url,
                        phone="",
                        url_type="static",
                    ),
                }
            ]
        if button_type == "PHONE":
            phone = self._normalize_button_phone(values.get("builder_button_phone"))
            return [
                {
                    "type": "call",
                    "parameter": self._provider_button_parameter(
                        text=text,
                        url=None,
                        phone=phone,
                        url_type="none",
                    ),
                }
            ]
        return []

    def _button_payload(self):
        self.ensure_one()
        return self._button_payload_from_values(
            {
                "builder_button_type": self.builder_button_type,
                "builder_button_text": self.builder_button_text,
                "builder_button_url": self.builder_button_url,
                "builder_button_phone": self.builder_button_phone,
            }
        )

    @api.model
    def _prepare_button_contract_vals(self, values, record=None):
        prepared = dict(values or {})
        if prepared.get("source") == "wati" or (record and record.source == "wati"):
            return prepared

        if record:
            effective = {
                "builder_button_type": record.builder_button_type or "NONE",
                "builder_button_text": record.builder_button_text or "",
                "builder_button_url": record.builder_button_url or "",
                "builder_button_phone": record.builder_button_phone or "",
            }
        else:
            effective = {
                "builder_button_type": "NONE",
                "builder_button_text": "",
                "builder_button_url": "",
                "builder_button_phone": "",
            }

        for field_name in _BUTTON_FIELDS:
            if field_name in prepared:
                effective[field_name] = prepared.get(field_name) or ""

        button_type = effective["builder_button_type"] or "NONE"
        if button_type == "URL" and effective["builder_button_url"]:
            effective["builder_button_url"] = self._normalize_button_url(
                effective["builder_button_url"]
            )
        elif button_type == "PHONE" and effective["builder_button_phone"]:
            effective["builder_button_phone"] = self._normalize_button_phone(
                effective["builder_button_phone"]
            )

        # Keep the user-facing fields and the technical snapshot atomically in sync.
        prepared.update(effective)
        prepared["buttons_json"] = json.dumps(
            self._button_payload_from_values(effective),
            ensure_ascii=False,
        )
        return prepared

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for values in vals_list:
            if _BUTTON_FIELDS.intersection(values):
                values = self._prepare_button_contract_vals(values)
            prepared.append(values)
        return super().create(prepared)

    def write(self, vals):
        if self.env.context.get("wati_button_contract_prepared"):
            return super().write(vals)
        if not _BUTTON_FIELDS.intersection(vals):
            return super().write(vals)

        result = True
        for record in self:
            prepared = self._prepare_button_contract_vals(vals, record=record)
            result = (
                super(WatiTemplateButtonContract, record)
                .with_context(wati_button_contract_prepared=True)
                .write(prepared)
                and result
            )
        return result

    def _assert_can_submit(self):
        super()._assert_can_submit()
        self.ensure_one()
        if self.builder_button_type == "URL":
            self._normalize_button_url(self.builder_button_url, required=True)
        elif self.builder_button_type == "PHONE":
            self._normalize_button_phone(self.builder_button_phone, required=True)

    @api.model
    def _remote_values(self, normalized, now=None):
        values = super()._remote_values(normalized, now=now)
        buttons = normalized.get("buttons") or []
        if not buttons or not isinstance(buttons[0], dict):
            return values

        button = buttons[0]
        parameter = button.get("parameter") if isinstance(button.get("parameter"), dict) else {}
        button_type = clean(button.get("type")).casefold()
        if button_type in {"quick_reply", "quickreply"}:
            values["builder_button_type"] = "QUICK_REPLY"
        elif button_type in {"url", "website"}:
            values["builder_button_type"] = "URL"
        elif button_type in {"call", "phone_number", "phone"}:
            values["builder_button_type"] = "PHONE"
        else:
            return values

        values["builder_button_text"] = clean(
            parameter.get("text") or button.get("text")
        ) or False
        values["builder_button_url"] = clean(
            parameter.get("url")
            or parameter.get("urlOriginal")
            or button.get("url")
            or button.get("targetUrl")
            or button.get("originalUrl")
        ) or False
        values["builder_button_phone"] = clean(
            parameter.get("phoneNumber")
            or button.get("phoneNumber")
            or button.get("phone_number")
        ) or False
        return values

    @api.model
    def _repair_button_contracts(self):
        records = self.sudo().search(
            [
                ("source", "=", "odoo"),
                ("status", "=", "draft"),
                ("builder_button_type", "!=", "NONE"),
            ]
        )
        repaired = 0
        for record in records:
            values = self._prepare_button_contract_vals({}, record=record)
            record.with_context(wati_button_contract_prepared=True).sudo().write(values)
            repaired += 1
        return repaired
