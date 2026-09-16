"""Release marker for inbox identity and access-control improvements."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """New user approval fields are created by the Odoo registry; no data rewrite.

    In particular, do not alter existing OTP flows, automation definitions, or
    conversation ownership during a customer upgrade.
    """
    _logger.info("WATI 19.0.11.0.9 migration completed from %s", version or "unknown")
