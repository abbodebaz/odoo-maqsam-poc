import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)

# Historical corrections that used to run from data XML on every module upgrade.
# Keep them here so upgrades into 19.0.11 execute each correction exactly once.
_REPAIRS = (
    ("wati.message", "_wati_repair_duplicate_identities"),
    ("wati.automation.rule", "_repair_template_parameter_invariants"),
    ("wati.smart.button.location", "_repair_admin_visibility"),
    ("wati.smart.button.location", "_repair_timeline_buttons"),
    ("wati.automation.rule", "_repair_template_integrity_final"),
    ("wati.automation.rule", "_repair_live_template_contracts"),
    ("wati.automation.log", "_repair_false_negative_logs"),
    ("wati.webhook.event", "_repair_webhook_monitor"),
    ("wati.template", "_repair_unverified_submissions"),
    ("wati.template", "_repair_provider_rejected_template_submissions"),
    ("wati.template", "_repair_button_contracts"),
    ("wati.template", "_repair_pending_template_lifecycle"),
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"lang": "en_US"})
    for model_name, method_name in _REPAIRS:
        _logger.info("WATI migration 19.0.11: %s.%s", model_name, method_name)
        getattr(env[model_name], method_name)()
