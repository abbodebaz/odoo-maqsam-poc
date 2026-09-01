import logging
from datetime import timedelta

from odoo import fields, models


_logger = logging.getLogger(__name__)
_PENDING_TTL_MINUTES = 10


class WatiAutomationDedupFix(models.Model):
    _inherit = "wati.automation.rule"

    def _execute_record(self, record):
        """Execute a rule with delivery-aware de-duplication.

        Legacy `sent` rows from the old automation engine are intentionally NOT
        treated as proof of delivery. Only a confirmed `delivered` row blocks a
        record forever. A recent `accepted` row blocks a duplicate briefly while
        WATI/Meta is still processing it; stale accepted rows are released for a
        safe retry.
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

                    # A request that stayed accepted too long is not proof of
                    # delivery. Release it so the customer can be retried safely.
                    pending.write(
                        {
                            "status": "failed",
                            "delivery_status": "accepted_timeout",
                            "error_message": (
                                "انتهت مهلة انتظار تأكيد التسليم من WATI؛ "
                                "تم السماح بإعادة المحاولة تلقائيًا."
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
