import json
import re
import time

from odoo import _, models
from odoo.exceptions import UserError

from ..services.client import WatiClient
from ..services.config import WatiConfig
from ..services.exceptions import WatiError


def _find_template_list(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("messageTemplates", "templates", "items", "results", "result", "data", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _find_template_list(value)
            if nested:
                return nested
    for value in payload.values():
        if isinstance(value, (dict, list)):
            nested = _find_template_list(value)
            if nested:
                return nested
    return []


def _first(mapping, keys):
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _template_name(item):
    return _first(item, ("elementName", "templateName", "template_name", "name"))


def _template_body(item):
    if not isinstance(item, dict):
        return ""
    body = item.get("body")
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        text = _first(body, ("text", "body", "content"))
        if text:
            return text
    components = item.get("components")
    if isinstance(components, list):
        for component in components:
            if not isinstance(component, dict):
                continue
            if str(component.get("type") or "").upper() == "BODY":
                text = _first(component, ("text", "body", "content"))
                if text:
                    return text
    return ""


def _dedupe_names(values):
    result = []
    seen = set()
    for value in values:
        name = str(value or "").strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


def _template_custom_param_names(item):
    names = []
    if not isinstance(item, dict):
        return names
    for key in ("customParams", "params", "parameters"):
        raw = item.get(key)
        if not isinstance(raw, list):
            continue
        for entry in raw:
            if isinstance(entry, dict):
                name = _first(entry, ("name", "paramName", "parameterName", "key", "field"))
            elif isinstance(entry, str):
                name = entry.strip()
            else:
                name = ""
            if name:
                names.append(name)
    return _dedupe_names(names)


def _template_body_tokens(item):
    return _dedupe_names(
        token.strip()
        for token in re.findall(r"{{\s*([^{}]+?)\s*}}", _template_body(item) or "")
    )


def _template_param_names(item):
    """Return the canonical WATI variable names without double counting aliases.

    WATI commonly returns friendly custom parameter names (for example
    ``services``, ``serdate`` and ``sertime``) while the template body itself
    contains positional placeholders (``{{1}}``, ``{{2}}``, ``{{3}}``).  They
    describe the same three variables and must not become six mapping rows.

    Prefer WATI's custom parameter names when positional BODY placeholders are
    present. Named BODY placeholders that are not represented in metadata are
    retained as additional variables.
    """
    if not isinstance(item, dict):
        return []

    custom_names = _template_custom_param_names(item)
    body_tokens = _template_body_tokens(item)
    if not custom_names:
        return body_tokens
    if not body_tokens:
        return custom_names

    positional = [token for token in body_tokens if token.isdigit()]
    named = [token for token in body_tokens if not token.isdigit()]

    # Positional BODY placeholders are aliases for the ordered customParams.
    # Do not append {{1}}, {{2}}, ... as separate variables.
    if positional:
        return _dedupe_names(custom_names + named)

    return _dedupe_names(custom_names + named)


def _error_summary(payload):
    if not isinstance(payload, dict):
        return "WATI It returned an incomprehensible failure result."
    errors = payload.get("errors")
    if isinstance(errors, dict):
        parts = []
        if errors.get("error"):
            parts.append(str(errors["error"]))
        invalid_numbers = errors.get("invalidWhatsappNumbers") or []
        invalid_params = errors.get("invalidCustomParameters") or []
        if invalid_numbers:
            parts.append("Invalid numbers: " + ", ".join(map(str, invalid_numbers)))
        if invalid_params:
            parts.append("Template variables: " + " | ".join(map(str, invalid_params)))
        if parts:
            return " — ".join(parts)
    if errors:
        try:
            return json.dumps(errors, ensure_ascii=False, default=str)[:1000]
        except Exception:
            return str(errors)[:1000]
    return "WATI He repeated result=false; The message was not sent."


class WatiAutomationRuleImprovements(models.Model):
    _inherit = "wati.automation.rule"

    def _parameter_value(self, record, line):
        value = super()._parameter_value(record, line)
        if (value is None or not str(value).strip()) and line.static_value:
            return line.static_value
        return value

    def _sync_template_parameters(self, param_names):
        """Make mapping rows exactly match the selected template variables.

        Existing mappings with the same parameter name are preserved. Stale
        rows from another template, duplicate rows, and the old numeric aliases
        are removed so changing or refreshing a template cannot accumulate
        garbage rows over time.
        """
        self.ensure_one()
        desired = _dedupe_names(param_names)
        desired_keys = {name.casefold() for name in desired}
        existing_by_key = {}
        duplicates = self.env["wati.automation.parameter"]

        for line in self.parameter_ids.sorted("sequence, id"):
            key = (line.param_name or "").strip().casefold()
            if not key or key not in desired_keys or key in existing_by_key:
                duplicates |= line
                continue
            existing_by_key[key] = line

        if duplicates:
            duplicates.unlink()

        created = 0
        for index, name in enumerate(desired, start=1):
            key = name.casefold()
            line = existing_by_key.get(key)
            vals = {"param_name": name, "sequence": index * 10}
            if line:
                line.write(vals)
            else:
                vals.update({
                    "rule_id": self.id,
                    "source_type": "field",
                })
                self.env["wati.automation.parameter"].create(vals)
                created += 1
        return created

    def action_fetch_template_params(self):
        self.ensure_one()
        if not self.template_name:
            raise UserError(_("Type or choose a name WATI Template First."))
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

        param_names = _template_param_names(template)
        created = self._sync_template_parameters(param_names)

        # Run the conservative existing mapper after synchronization. Exact
        # field-name matches and known safe aliases are filled automatically;
        # anything uncertain remains for the user to choose explicitly.
        auto_mapped = 0
        auto_mapper = getattr(self, "_auto_map_parameters", None)
        if callable(auto_mapper) and param_names:
            try:
                auto_mapped = auto_mapper()
            except Exception:
                auto_mapped = 0

        if not param_names:
            message = _("Template found, no variables found BODY Clear in it.")
            notification_type = "warning"
        else:
            details = []
            if created:
                details.append(_("has been created %s Rows matching the template.", created))
            if auto_mapped:
                details.append(_("has been linked %s variables automatically.", auto_mapped))
            suffix = " " + " ".join(details) if details else ""
            message = _("Synchronized %(total)s Variables from the template without duplication.%(suffix)s", total=len(param_names), suffix=suffix)
            notification_type = "success"

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("variables WATI Template"),
                "message": message,
                "type": notification_type,
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def _send_template(self, record, phone, custom_params):
        Log = self.env["wati.automation.log"].sudo()
        empty_params = [
            str(item.get("name") or "").strip()
            for item in custom_params
            if not str(item.get("value") or "").strip()
        ]
        if empty_params:
            Log.create(self._log_values(
                record,
                "failed",
                phone=phone,
                error_message=(
                    "Not called WATI Because the following template variables are worthless: "
                    + ", ".join(filter(None, empty_params))
                    + ". Link it to a field Odoo Or set a reserve value."
                ),
            ))
            return False

        body = {
            "template_name": self.template_name,
            "broadcast_name": f"odoo_auto_{self.id}_{record.id}_{int(time.time())}",
            "receivers": [{"whatsappNumber": phone, "customParams": custom_params}],
        }
        channel = (self.channel_number or WatiConfig(self.env).channel_number or "").strip()
        if channel:
            body["channel_number"] = channel

        try:
            response = WatiClient(self.env).send_template_messages(body)
        except WatiError as exc:
            excerpt = getattr(exc, "response_text", "") or str(exc)
            Log.create(self._log_values(
                record,
                "failed",
                phone=phone,
                error_message=str(exc),
                response_excerpt=excerpt[:1200],
            ))
            return False

        excerpt = (response.text or response.reason or "").strip()[:1200]
        try:
            response_payload = response.json()
        except ValueError:
            response_payload = None

        if isinstance(response_payload, dict) and (
            response_payload.get("result") is False
            or response_payload.get("success") is False
        ):
            Log.create(self._log_values(
                record,
                "failed",
                phone=phone,
                error_message=_error_summary(response_payload),
                response_excerpt=excerpt,
            ))
            return False

        Log.create(self._log_values(record, "sent", phone=phone, response_excerpt=excerpt))
        return True
