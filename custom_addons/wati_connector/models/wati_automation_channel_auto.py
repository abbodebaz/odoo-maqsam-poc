from odoo import _, fields, models
from odoo.exceptions import UserError

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from .wati_automation_guard import (
    _APPROVED_STATES,
    _GENERIC_TEMPLATE_NAMES,
    _digits,
    _extract_external_message_id,
    _same_channel,
    _template_category,
    _template_channel,
    _template_language,
    _template_status,
)
from .wati_automation_improvements import (
    _error_summary,
    _template_body,
    _template_name,
)


class WatiAutomationRuleChannelAuto(models.Model):
    _inherit = "wati.automation.rule"

    def _configured_channel(self):
        self.ensure_one()
        _endpoint, _token, configured_channel = self._wati_config()
        return (self.channel_number or configured_channel or "").strip()

    def _effective_channel(self):
        self.ensure_one()
        return self._configured_channel() or (self.template_channel_number or "").strip()

    def _select_live_template(self, templates=None):
        self.ensure_one()
        wanted = (self.template_name or "").strip()
        if not wanted:
            return None, _("Choose a template WATI First.")

        templates = templates if templates is not None else self._fetch_wati_templates_guarded()
        candidates = [
            item
            for item in templates
            if _template_name(item).strip().casefold() == wanted.casefold()
        ]
        if not candidates:
            return None, _("Template «%s» Not found in account WATI Currently online.") % wanted

        statuses = [_template_status(item).strip() for item in candidates]
        approved = [
            item
            for item in candidates
            if _template_status(item).strip().casefold() in _APPROVED_STATES
        ]
        if approved:
            candidates = approved
        elif any(statuses):
            visible = ", ".join(sorted({status for status in statuses if status}))
            return None, _(
                "Template «%(name)s» Exists but its status is not approved for sending: %(status)s"
            ) % {"name": wanted, "status": visible or "Unknown"}
        else:
            return None, _(
                "WATI No approval status was returned for the template «%s»Therefore, activation has been prevented as a precaution."
            ) % wanted

        effective_channel = self._effective_channel()
        channel_aware = [item for item in candidates if _template_channel(item)]
        if effective_channel and channel_aware:
            matching_channel = [
                item
                for item in channel_aware
                if _same_channel(_template_channel(item), effective_channel)
            ]
            if not matching_channel:
                channels = ", ".join(
                    sorted({_template_channel(item) for item in channel_aware if _template_channel(item)})
                )
                return None, _(
                    "Template «%(name)s» It exists, but it is not on a channel WATI current %(channel)s. "
                    "Existing channels of the template: %(available)s"
                ) % {
                    "name": wanted,
                    "channel": effective_channel,
                    "available": channels or "—",
                }
            candidates = matching_channel

        if not effective_channel:
            channels = sorted({_template_channel(item) for item in candidates if _template_channel(item)})
            if len(channels) > 1:
                return None, _(
                    "Template «%(name)s» Available on more than one channel WATI (%(channels)s). "
                    "Select template from button «Choose from WATI» To select the correct channel."
                ) % {"name": wanted, "channels": ", ".join(channels)}
            if len(channels) == 1:
                candidates = [
                    item for item in candidates
                    if not _template_channel(item)
                    or _same_channel(_template_channel(item), channels[0])
                ]

        stored_language = (self.template_language or "").strip().casefold()
        if stored_language:
            language_matches = [
                item for item in candidates
                if not _template_language(item)
                or _template_language(item).strip().casefold() == stored_language
            ]
            if language_matches:
                candidates = language_matches
        else:
            languages = sorted({_template_language(item) for item in candidates if _template_language(item)})
            if len(languages) > 1:
                return None, _(
                    "Template «%(name)s» Has more than one supported language (%(languages)s). "
                    "Select the desired version from the button «Choose from WATI» So as not to send a wrong translation."
                ) % {"name": wanted, "languages": ", ".join(languages)}

        candidates.sort(
            key=lambda item: (
                0 if effective_channel and _same_channel(_template_channel(item), effective_channel) else 1,
                _template_language(item).casefold(),
                _template_name(item).casefold(),
            )
        )
        return candidates[0], ""

    def _validation_cache_fresh(self):
        self.ensure_one()
        if self.template_validation_state != "valid" or not self.template_verified_at:
            return False
        effective_channel = self._effective_channel()
        verified_channel = (self.template_channel_number or "").strip()
        if effective_channel and verified_channel and not _same_channel(verified_channel, effective_channel):
            return False
        cutoff = fields.Datetime.now() - __import__("datetime").timedelta(minutes=5)
        return self.template_verified_at >= cutoff

    def action_pick_template(self):
        self.ensure_one()
        templates = self._fetch_wati_templates_guarded()
        effective_channel = self._effective_channel()
        Choice = self.env["wati.automation.template.choice"]
        Choice.search([("rule_id", "=", self.id)]).unlink()

        values = []
        for item in templates:
            name = _template_name(item).strip()
            if not name or name.casefold() in _GENERIC_TEMPLATE_NAMES:
                continue
            status = _template_status(item).strip()
            channel = _template_channel(item).strip()
            if status.casefold() not in _APPROVED_STATES:
                continue
            if effective_channel and channel and not _same_channel(channel, effective_channel):
                continue
            values.append(
                {
                    "rule_id": self.id,
                    "name": name,
                    "status": status,
                    "category": _template_category(item),
                    "body": _template_body(item),
                    "language": _template_language(item),
                    "channel_number": channel or effective_channel,
                }
            )

        if not values:
            message = (
                _("I couldn’t find any template Approved Valid for the channel %s.") % effective_channel
                if effective_channel
                else _("I couldn’t find any template Approved In an account WATI Currently online.")
            )
            raise UserError(message)

        unique = {}
        for vals in values:
            key = (
                vals["name"].casefold(),
                (vals["language"] or "").casefold(),
                _digits(vals["channel_number"]),
            )
            unique[key] = vals
        Choice.create(list(unique.values()))
        return {
            "type": "ir.actions.act_window",
            "name": _("Choose a template WATI Approved"),
            "res_model": "wati.automation.template.choice",
            "view_mode": "list",
            "views": [(self.env.ref("wati_connector.view_wati_automation_template_choice_list").id, "list")],
            "domain": [("rule_id", "=", self.id)],
            "target": "new",
        }

    def _send_template(self, record, phone, custom_params):
        Log = self.env["wati.automation.log"].sudo()
        if not self._validate_template_live(force=False, raise_error=False):
            Log.create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message=self.template_validation_message or "The template is not valid for submission.",
                )
            )
            return False

        effective_channel = self._effective_channel()
        empty_params = [
            str(item.get("name") or "").strip()
            for item in custom_params
            if not str(item.get("value") or "").strip()
        ]
        if empty_params:
            Log.create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message=(
                        "Not called WATI Because the following template variables are worthless: "
                        + ", ".join(filter(None, empty_params))
                        + ". Link it to a field Odoo Or set a reserve value."
                    ),
                )
            )
            return False

        now_token = fields.Datetime.now().strftime("%Y%m%d%H%M%S%f")
        broadcast_name = f"odoo_auto_{self.id}_{record.id}_{now_token}"
        body = {
            "template_name": self.template_name,
            "broadcast_name": broadcast_name,
            "receivers": [{"whatsappNumber": phone, "customParams": custom_params}],
        }
        if effective_channel:
            body["channel_number"] = effective_channel

        try:
            response = WatiClient(self.env).send_template_messages(body)
        except WatiConfigurationError:
            Log.create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message="Settings WATI API Incomplete.",
                )
            )
            return False
        except WatiRequestError as exc:
            detail = (exc.response_text or str(exc) or "").strip()[:2000]
            Log.create(
                {
                    **self._log_values(
                        record,
                        "failed",
                        phone=phone,
                        error_message=str(exc),
                        response_excerpt=detail,
                    ),
                    "broadcast_name": broadcast_name,
                    "delivery_status": "api_rejected",
                }
            )
            return False

        excerpt = (response.text or response.reason or "").strip()[:2000]
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict) and (
            payload.get("result") is False
            or payload.get("success") is False
            or bool(payload.get("errors"))
        ):
            Log.create(
                {
                    **self._log_values(
                        record,
                        "failed",
                        phone=phone,
                        error_message=_error_summary(payload),
                        response_excerpt=excerpt,
                    ),
                    "broadcast_name": broadcast_name,
                    "delivery_status": "api_failed",
                }
            )
            return False

        external_message_id = _extract_external_message_id(payload)
        Log.create(
            {
                **self._log_values(record, "accepted", phone=phone, response_excerpt=excerpt),
                "broadcast_name": broadcast_name,
                "external_message_id": external_message_id or False,
                "delivery_status": "accepted",
            }
        )
        return True
