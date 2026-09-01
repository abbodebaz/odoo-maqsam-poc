import logging

from odoo import models


_logger = logging.getLogger(__name__)


class WatiAutomationLogRepair(models.Model):
    _inherit = "wati.automation.log"

    def init(self):
        """Repair only the known WATI false-negative response pattern.

        Older code treated `result:false` as an API failure even when WATI
        returned HTTP 200, an empty error string, no invalid WhatsApp numbers,
        and no invalid custom parameters. Those rows are not proof of delivery,
        but they are also not API failures; reclassify them as accepted so the
        history reflects what actually happened at the API boundary.
        """
        self.env.cr.execute(
            """
            UPDATE wati_automation_log
               SET status = 'accepted',
                   delivery_status = 'accepted_http_200_reclassified',
                   error_message = NULL
             WHERE status = 'failed'
               AND delivery_status = 'api_failed'
               AND (
                    COALESCE(response_excerpt, '') || ' ' || COALESCE(error_message, '')
                   ) LIKE '%%"invalidWhatsappNumbers": []%%'
               AND (
                    COALESCE(response_excerpt, '') || ' ' || COALESCE(error_message, '')
                   ) LIKE '%%"invalidCustomParameters": []%%'
               AND (
                    COALESCE(response_excerpt, '') || ' ' || COALESCE(error_message, '')
                   ) LIKE '%%"error": ""%%'
            """
        )
        if self.env.cr.rowcount:
            _logger.info(
                "Reclassified %s historical WATI automation false-negative log(s) as accepted",
                self.env.cr.rowcount,
            )
