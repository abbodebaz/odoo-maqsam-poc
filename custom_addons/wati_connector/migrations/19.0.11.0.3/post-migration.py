import logging

from psycopg2 import errors

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Best-effort reclassification of historical webhook monitor rows.

    Live webhook traffic can update the same audit table while a customer is
    upgrading. Historical reclassification is useful but must never prevent the
    connector itself from upgrading, so serialization contention is isolated in
    a savepoint and safely deferred. New webhook events already use the current
    runtime classification policy.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        with cr.savepoint():
            env["wati.webhook.event"]._repair_webhook_monitor()
    except errors.SerializationFailure:
        _logger.warning(
            "WATI_WEBHOOK_MONITOR_MIGRATION_DEFERRED reason=serialization_contention"
        )
