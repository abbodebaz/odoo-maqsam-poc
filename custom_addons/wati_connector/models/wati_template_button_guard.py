import json
import re

from odoo import _, api, models

from ..services.template_catalog import clean


_PROVIDER_ERROR_MESSAGE_RE = re.compile(
    r"(?:parameter\s+is\s+null|please\s+check|\binvalid\b|\bfailed\b|\bfailure\b|\berror\b|\bmissing\b|\brequired\b|cannot|can't)",
    re.IGNORECASE,
)


class WatiTemplateButtonGuard(models.Model):
    """Preserve provider-error recovery for the verified button contract.

    Earlier releases used a fail-closed block while the nested WATI button
    object was being verified. The connector now mirrors the exact ``parameter``
    structure returned by WATI's template catalogue, so supported standard
    buttons can use the normal builder validation and lifecycle checks.
    """

    _inherit = "wati.template"

    def _assert_can_submit(self):
        return super()._assert_can_submit()

    @api.model
    def _repair_provider_rejected_template_submissions(self):
        """Migration helper: return explicit WATI creation failures to draft."""
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
                    "last_error": _("WATI rejected template creation: %s") % message,
                }
            )
            repaired += 1
        return repaired
