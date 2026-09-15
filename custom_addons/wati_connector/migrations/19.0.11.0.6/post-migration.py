import logging


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Schema work for 19.0.11.0.6 is handled by normal Odoo module loading.

    Keep the release boundary explicit so generated OTP button views and
    post-verification workflow records can evolve through auditable migrations.
    """
    _logger.info("WATI 19.0.11.0.6 migration completed from %s", version or "unknown")
