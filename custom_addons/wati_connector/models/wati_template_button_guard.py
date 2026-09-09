import json
import re

from odoo import _, api, models
from odoo.exceptions import UserError

from ..services.template_catalog import clean


_PROVIDER_ERROR_MESSAGE_RE = re.compile(
    r"(?:parameter\s+is\s+null|please\s+check|\binvalid\b|\bfailed\b|\bfailure\b|\berror\b|\bmissing\b|\brequired\b|cannot|can't)",
    re.IGNORECASE,
)


class WatiTemplateButtonGuard(models.Model):
    """Prevent known-invalid button submissions until WATI's nested schema is verified.

    WATI publicly documents button configuration types, but its create-template
    page does not publish the nested button-object contract. Our first live
    Quick Reply request was explicitly rejected by WATI, so production behavior
    must fail closed instead of guessing another payload shape.
    """

    _inherit = "wati.template"

    def _assert_can_submit(self):
        super()._assert_can_submit()
        self.ensure_one()
        if self.builder_button_type != "NONE":
            raise UserError(
                _(
                    "إرسال القوالب التي تحتوي على أزرار متوقف مؤقتًا للحماية. "
                    "WATI رفض عقد الزر الحالي برسالة تحقق من الخادم، بينما التوثيق العام لا يوضح البنية الداخلية للزر. "
                    "اختر «بدون أزرار» لإرسال القالب الآن. ستبقى خيارات الأزرار متاحة في المسودة والمعاينة إلى أن نثبت عقد WATI الفعلي."
                )
            )

    @api.model
    def _repair_provider_rejected_template_submissions(self):
        """Return explicit WATI creation failures to editable draft state."""
        records = self.sudo().search(
            [
                ("source", "=", "odoo"),
                ("status", "in", ["pending", "pending_internal"]),
                ("wati_template_id", "=", False),
                ("meta_template_id", "=", False),
            ]
        )
        repaired = 0
        for record in records:
            try:
                payload = json.loads(record.provider_response or "{}")
            except (TypeError, ValueError):
                payload = {}
            if not isinstance(payload, dict):
                continue
            message = clean(payload.get("message"))
            if not message or not _PROVIDER_ERROR_MESSAGE_RE.search(message):
                continue
            record.sudo().write(
                {
                    "status": "draft",
                    "last_error": _("رفض WATI إنشاء القالب: %s") % message,
                }
            )
            repaired += 1
        return repaired
