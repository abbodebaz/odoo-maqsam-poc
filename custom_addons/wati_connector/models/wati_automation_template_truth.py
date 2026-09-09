from odoo import _, models
from odoo.exceptions import UserError

from ..services.client import WatiClient
from ..services.exceptions import WatiError
from .wati_automation_improvements import (
    _find_template_list,
    _template_body,
    _template_body_tokens,
    _template_custom_param_names,
    _template_name,
)


def _canonical_template_param_names(item):
    """Return exactly the variables represented by the selected template body.

    WATI can return customParams metadata that is stale or broader than the
    actual BODY text. The visible template text is therefore authoritative.

    * Named BODY placeholders ({{name}}) are used exactly as written.
    * Positional placeholders ({{1}}, {{2}}, ...) use WATI custom parameter
      names only when there is a strict one-to-one count match. In that safe
      case the friendly names are useful for the send API and UI labels.
    * If counts disagree, positional BODY tokens win and the extra metadata is
      ignored rather than creating phantom mapping rows.
    * Metadata is only a fallback for templates whose BODY exposes no tokens.
    """
    body_tokens = _template_body_tokens(item)
    custom_names = _template_custom_param_names(item)

    if not body_tokens:
        return custom_names

    if all(token.isdigit() for token in body_tokens):
        if custom_names and len(custom_names) == len(body_tokens):
            return custom_names
        return body_tokens

    # Named placeholders are already semantic and should never be supplemented
    # by unrelated customParams metadata.
    return body_tokens


class WatiAutomationRuleTemplateTruth(models.Model):
    _inherit = "wati.automation.rule"

    def action_fetch_template_params(self):
        self.ensure_one()
        if not self.template_name:
            raise UserError(_("Choose a template WATI First."))

        try:
            response = WatiClient(self.env).get_message_templates(page_size=200, page_number=1)
            payload = response.json()
        except WatiError as exc:
            raise UserError(_("Unable to contact WATI To bring the template: %s", exc)) from exc
        except ValueError as exc:
            raise UserError(_("WATI Returned an unintelligible response when fetching templates.")) from exc

        wanted = (self.template_name or "").strip().casefold()
        template = next(
            (item for item in _find_template_list(payload) if _template_name(item).casefold() == wanted),
            None,
        )
        if not template:
            raise UserError(_("I did not find Template In the name of %s Inside an account WATI.", self.template_name))

        body = _template_body(template)
        if "template_body" in self._fields:
            self.template_body = body or False

        param_names = _canonical_template_param_names(template)
        created = self._sync_template_parameters(param_names)

        auto_mapped = 0
        auto_mapper = getattr(self, "_auto_map_parameters", None)
        if callable(auto_mapper) and param_names:
            try:
                auto_mapped = auto_mapper()
            except Exception:
                auto_mapped = 0

        body_count = len(_template_body_tokens(template))
        metadata_count = len(_template_custom_param_names(template))
        metadata_ignored = bool(body_count and metadata_count and body_count != metadata_count)

        if not param_names:
            message = _("The template is synchronized, and there are no variables in the message body.")
            notification_type = "warning"
        else:
            parts = [_("Synchronized %s Variables as they appear in the template text.", len(param_names))]
            if created:
                parts.append(_("has been created %s New link.", created))
            if auto_mapped:
                parts.append(_("been suggested %s Automatic connection.", auto_mapped))
            if metadata_ignored:
                parts.append(_("Data was ignored WATI Extra because it does not match the number of text variables."))
            message = " ".join(parts)
            notification_type = "success"

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Template variables are synchronized"),
                "message": message,
                "type": notification_type,
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }
