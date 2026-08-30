import logging
import re
import time

import requests

from odoo import fields, models


_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = "crm.lead"

    wati_qualified_template_sent = fields.Boolean(
        string="WATI Qualified Template Sent",
        default=False,
        copy=False,
        readonly=True,
    )
    wati_qualified_template_sent_at = fields.Datetime(
        string="WATI Qualified Template Sent At",
        copy=False,
        readonly=True,
    )
    wati_qualified_template_error = fields.Text(
        string="WATI Qualified Template Error",
        copy=False,
        readonly=True,
    )

    def write(self, vals):
        result = super().write(vals)

        if self.env.context.get("skip_wati_crm_trigger"):
            return result

        # Kanban drag/drop changes stage_id. We only react to an actual move into
        # the Qualified stage, and only once per opportunity.
        if "stage_id" in vals:
            for lead in self:
                if (
                    lead.type == "opportunity"
                    and lead.stage_id
                    and (lead.stage_id.name or "").strip().lower() == "qualified"
                    and not lead.wati_qualified_template_sent
                ):
                    lead._wati_send_qualified_template_safely()

        return result

    def _wati_send_qualified_template_safely(self):
        self.ensure_one()
        try:
            self._wati_send_qualified_template()
        except Exception as exc:  # Never block CRM stage changes because WATI failed.
            _logger.exception("WATI CRM Qualified template failed for lead %s", self.id)
            error = str(exc)[:1500]
            self.with_context(skip_wati_crm_trigger=True).sudo().write(
                {"wati_qualified_template_error": error}
            )
            try:
                self.message_post(
                    body=(
                        "⚠️ لم يتم إرسال قالب WhatsApp <b>cr27_3</b> تلقائيًا "
                        f"عند الوصول إلى Qualified.<br/>{error}"
                    )
                )
            except Exception:
                _logger.exception("Could not post WATI CRM failure note for lead %s", self.id)

    def _wati_send_qualified_template(self):
        self.ensure_one()

        phone = self._wati_crm_phone()
        if not phone:
            raise ValueError("لا يوجد رقم جوال/هاتف على العميل أو فرصة CRM.")

        customer_name = self._wati_crm_customer_name()
        params = self.env["ir.config_parameter"].sudo()
        endpoint = (params.get_param("wati_connector.api_endpoint") or "").strip().rstrip("/")
        token = (params.get_param("wati_connector.api_token") or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        channel = (params.get_param("wati_connector.channel_number") or "").strip()

        if not endpoint or not token:
            raise ValueError("إعدادات WATI API غير مكتملة.")

        custom_params = [
            {"name": "cr_id2", "value": f"CRM-{self.id}"},
            {"name": "cr_clint2", "value": customer_name},
            {"name": "cr_type", "value": "فرصة مبيعات مؤهلة"},
            {"name": "cr_dep", "value": "المبيعات"},
            {"name": "cr_sap", "value": self.name or f"CRM-{self.id}"},
        ]

        body = {
            "template_name": "cr27_3",
            "broadcast_name": f"odoo_cr27_3_qualified_{self.id}_{int(time.time())}",
            "receivers": [
                {
                    "whatsappNumber": phone,
                    "customParams": custom_params,
                }
            ],
        }
        if channel:
            body["channel_number"] = channel

        response = requests.post(
            f"{endpoint}/api/v1/sendTemplateMessages",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=30,
        )

        if not response.ok:
            detail = (response.text or response.reason or "").strip()[:1200]
            raise ValueError(f"WATI رفض إرسال القالب ({response.status_code}): {detail}")

        self.with_context(skip_wati_crm_trigger=True).sudo().write(
            {
                "wati_qualified_template_sent": True,
                "wati_qualified_template_sent_at": fields.Datetime.now(),
                "wati_qualified_template_error": False,
            }
        )
        try:
            self.message_post(
                body=(
                    "✅ تم إرسال قالب WhatsApp <b>cr27_3</b> تلقائيًا "
                    "عند انتقال الفرصة إلى <b>Qualified</b>."
                )
            )
        except Exception:
            _logger.exception("Could not post WATI CRM success note for lead %s", self.id)

    def _wati_crm_phone(self):
        self.ensure_one()
        values = []

        if self.partner_id:
            for field_name in ("mobile", "phone"):
                if field_name in self.partner_id._fields and self.partner_id[field_name]:
                    values.append(self.partner_id[field_name])

        for field_name in ("mobile", "phone"):
            if field_name in self._fields and self[field_name]:
                values.append(self[field_name])

        for value in values:
            normalized = self._wati_normalize_phone(value)
            if normalized:
                return normalized
        return ""

    def _wati_crm_customer_name(self):
        self.ensure_one()
        if self.partner_id:
            return self.partner_id.display_name or self.partner_id.name or self.name
        for field_name in ("contact_name", "partner_name"):
            if field_name in self._fields and self[field_name]:
                return self[field_name]
        return self.name or f"CRM-{self.id}"

    @staticmethod
    def _wati_normalize_phone(value):
        digits = re.sub(r"\D+", "", str(value or ""))
        if digits.startswith("00"):
            digits = digits[2:]
        if not digits:
            return ""
        if digits.startswith("966"):
            return digits
        if digits.startswith("0") and len(digits) >= 9:
            return "966" + digits[1:]
        if len(digits) == 9 and digits.startswith("5"):
            return "966" + digits
        return digits
