import logging
from datetime import timedelta

from odoo import _, fields, models


_logger = logging.getLogger(__name__)
_PENDING_TTL_MINUTES = 10


class WatiAutomationDeduplication(models.Model):
    _inherit = "wati.automation.rule"

    def _execute_record(self, record):
        """Execute a rule with delivery-aware de-duplication.

        Legacy ``sent`` rows are not treated as proof of delivery. Only a
        confirmed ``delivered`` row permanently blocks the record. A recent
        ``accepted`` row blocks a duplicate briefly while WATI/Meta processes the
        request; stale accepted rows are released for a safe retry.
        """
        self.ensure_one()
        if not self.active or not record or record._name != self.model_name:
            return False

        try:
            if not self._condition_matches(record):
                return False

            Log = self.env["wati.automation.log"].sudo()
            base_domain = [
                ("rule_id", "=", self.id),
                ("model_name", "=", record._name),
                ("res_id", "=", record.id),
                ("is_test", "=", False),
            ]

            if self.once_per_record:
                delivered = Log.search_count(
                    base_domain + [("status", "=", "delivered")],
                    limit=1,
                )
                if delivered:
                    _logger.info(
                        "WATI automation rule %s skipped record %s:%s because it was already delivered",
                        self.id,
                        record._name,
                        record.id,
                    )
                    return False

                pending = Log.search(
                    base_domain + [("status", "=", "accepted")],
                    order="create_date desc, id desc",
                    limit=1,
                )
                if pending:
                    cutoff = fields.Datetime.now() - timedelta(minutes=_PENDING_TTL_MINUTES)
                    if pending.create_date and pending.create_date >= cutoff:
                        _logger.info(
                            "WATI automation rule %s skipped record %s:%s because request %s is still pending",
                            self.id,
                            record._name,
                            record.id,
                            pending.id,
                        )
                        return False

                    pending.write(
                        {
                            "status": "failed",
                            "delivery_status": "accepted_timeout",
                            "error_message": _(
                                "The WATI delivery-confirmation timeout expired; the record is eligible for retry."
                            ),
                        }
                    )

            phone = self._recipient_phone(record)
            if not phone:
                Log.create(
                    self._log_values(
                        record,
                        "failed",
                        phone="",
                        error_message=_("No WhatsApp number was found on the record."),
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
            _logger.exception("WATI automation rule %s failed", self.id)
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
