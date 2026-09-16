import logging


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Schema/data work for 19.0.11.0.5 is handled by normal Odoo module loading.

    Keep an explicit versioned migration boundary so upgrades remain auditable and
    future OTP Flow data migrations have a stable release hook.
    """
    _logger.info("WATI 19.0.11.0.5 migration completed from %s", version or "unknown")
