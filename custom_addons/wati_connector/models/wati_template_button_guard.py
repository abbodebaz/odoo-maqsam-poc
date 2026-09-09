import json
import re

from odoo import _, api, models

from ..services.template_catalog import clean


_PROVIDER_ERROR_MESSAGE_RE = re.compile(
    r"(?:parameter\s+is\s+null|please\s+check|\binvalid\b|\bfailed\b|\bfailure\b|\berror\b|\bmissing\b|\brequired\b|cannot|can't)",
    re.IGNORECASE,
)


class WatiTemplateButtonGuard(models.Model):
    """Keep provider-error recovery while button authoring uses a verified contract.

    The temporary fail-closed block was needed while the nested WATI button
    object was unknown. We now mirror the exact ``parameter`` structure returned
    by WATI's own template catalogue, so supported Standard buttons can proceed
    through the normal builder validation and lifecycle checks.
    """

    _inherit = "wati.template"

    def _assert_can_submit(self):
        return super()._assert_can_submit()

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
