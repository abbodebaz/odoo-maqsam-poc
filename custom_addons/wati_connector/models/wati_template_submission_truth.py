import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.template_catalog import clean, normalize_template


_logger = logging.getLogger(__name__)


class WatiTemplateSubmissionTruth(models.Model):
    """Keep Odoo template lifecycle aligned with the provider's actual state.

    A successful HTTP response from WATI means the creation request reached the
    provider. It does *not* prove that the template exists in WATI/Meta yet.
    We therefore use a two-phase lifecycle:

    1. POST the creation request.
    2. Verify the exact template identity against WATI's template catalogue.

    Until step 2 succeeds, the record stays ``pending_internal`` and the UI must
    not claim that Meta is already reviewing it.
    """

    _inherit = "wati.template"

    def _remote_identity_match(self, normalized):
        self.ensure_one()
        if not normalized:
            return False
        return (
            clean(normalized.get("name")) == clean(self.name)
            and clean(normalized.get("language")) == clean(self.language)
        )

    def _find_remote_submission(self):
        self.ensure_one()
        for item in self._fetch_remote_templates():
            normalized = normalize_template(item)
            if self._remote_identity_match(normalized):
                return normalized
        return None

    def _mark_submission_unverified(self, message=None):
        self.ensure_one()
        detail = message or _(
            "Send Odoo Request to create template to WATI, but the template has not yet appeared in the source WATI. "
            "We have not considered it under review Meta Until it is actually verified."
        )
        self.sudo().write(
            {
                "status": "pending_internal",
                "last_synced_at": fields.Datetime.now(),
                "last_error": detail,
            }
        )
        return False

    def _apply_verified_remote_template(self, normalized):
        self.ensure_one()
        now = fields.Datetime.now()
        self.sudo().write(self._remote_values(normalized, now=now))
        self._sync_readonly_variables(normalized.get("custom_params") or [])
        return True

    def _verify_submission_with_wati(self):
        self.ensure_one()
        try:
            normalized = self._find_remote_submission()
        except (WatiConfigurationError, WatiRequestError, UserError) as exc:
            detail = clean(getattr(exc, "response_text", "") or str(exc))[:1200]
            return self._mark_submission_unverified(
                _("The create request was sent, but could not be verified WATI Now: %s") % detail
            )

        if not normalized:
            return self._mark_submission_unverified()
        return self._apply_verified_remote_template(normalized)

    def action_submit_for_approval(self):
        self.ensure_one()
        result = super().action_submit_for_approval()

        # Super has completed the provider POST successfully. Do not expose the
        # optimistic ``pending`` state until the exact template can be observed
        # from WATI's own catalogue.
        verified = self._verify_submission_with_wati()
        if verified:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("The template has been verified in WATI"),
                    "message": _(
                        "The template has been created and appears in WATI. The status shown now is the real status coming from WATI/Meta."
                    ),
                    "type": "success",
                    "sticky": False,
                    "next": {"type": "ir.actions.client", "tag": "soft_reload"},
                },
            }

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Waiting for confirmation WATI"),
                "message": _(
                    "Received WATI Requested to create, but the template does not appear in the list WATI After. We will not consider it under review Meta Until it is verified. Use «Status update» Later."
                ),
                "type": "warning",
                "sticky": True,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def action_refresh_status(self):
        result = super().action_refresh_status()
        for record in self:
            # Base refresh keeps the previous state when WATI does not return a
            # template. Correct any optimistic legacy state after that refresh.
            if (
                record.source == "odoo"
                and record.status == "pending"
                and clean(record.last_error).startswith("This template did not appear")
            ):
                record._mark_submission_unverified(
                    _(
                        "This template did not appear in a result WATI current. So we brought the case back to «Under verification» Display allowance «Under review Meta» Without proof."
                    )
                )
        return result

    @api.model
    def _repair_unverified_submissions(self):
        records = self.sudo().search(
            [
                ("source", "=", "odoo"),
                ("status", "=", "pending"),
                ("wati_template_id", "=", False),
                ("meta_template_id", "=", False),
                ("last_error", "ilike", "This template did not appear"),
            ]
        )
        for record in records:
            response_summary = {}
            try:
                payload = json.loads(record.provider_response or "{}")
            except (TypeError, ValueError):
                payload = {}
            if isinstance(payload, dict):
                for key in (
                    "success",
                    "result",
                    "status",
                    "templateStatus",
                    "templateId",
                    "watiTemplateId",
                    "message",
                    "error",
                ):
                    if key in payload:
                        response_summary[key] = payload.get(key)
            _logger.warning(
                "WATI_TEMPLATE_SUBMISSION_UNVERIFIED_REPAIR id=%s name=%r response=%s",
                record.id,
                record.name,
                response_summary,
            )
            record._mark_submission_unverified(
                _(
                    "The template did not appear WATI After the previous creation request. The condition has been corrected to «Under verification» So no review appears Meta Uncertainly."
                )
            )
        if records:
            _logger.warning(
                "WATI_TEMPLATE_SUBMISSION_UNVERIFIED_REPAIR_DONE count=%s ids=%s",
                len(records),
                records.ids,
            )
        return True
