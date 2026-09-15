from odoo import _, api, models

from ..utils.phone import normalize_whatsapp_number


class WatiOtpFlowRecipientPreview(models.Model):
    _inherit = "wati.otp.flow"

    @api.model
    def _mask_phone_for_preview(self, phone):
        digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
        if not digits:
            return ""
        if len(digits) <= 4:
            return digits
        if len(digits) <= 7:
            return f"{digits[:2]}{'•' * (len(digits) - 4)}{digits[-2:]}"
        return f"{digits[:4]}{'•' * max(4, len(digits) - 7)}{digits[-3:]}"

    def _recipient_preview_resolution(self, path):
        self.ensure_one()
        model_name = self.model_name
        path = (path or "").strip()
        if not model_name or model_name not in self.env or not path:
            return "", ""

        try:
            records = self.env[model_name].sudo().search([], order="id desc", limit=20)
        except Exception:
            return "", ""

        for record in records:
            try:
                raw = self._resolve_path(record, path)
                normalized = normalize_whatsapp_number(raw) if raw else ""
            except Exception:
                continue
            if not normalized:
                continue
            label = record.display_name or f"{model_name},{record.id}"
            return self._mask_phone_for_preview(normalized), label
        return "", ""

    @api.depends("model_id", "recipient_mode", "recipient_path")
    def _compute_recipient_state(self):
        for flow in self:
            options = flow._recipient_path_options() if flow.model_id else []
            visible = flow._visible_recipient_options()
            mode = flow.recipient_mode or "auto"

            flow.smart_recipient_metadata = {
                "mode": "select" if visible else "empty",
                "placeholder": (
                    "Select a phone field from this record"
                    if mode == "direct"
                    else "Select a phone field from a related record"
                ),
                "options": [
                    {
                        "value": item["value"],
                        "label": item["label"]
                        + (" — Recommended" if index == 0 and len(visible) > 1 else ""),
                    }
                    for index, item in enumerate(visible)
                ],
            }

            selected = next(
                (
                    item
                    for item in options
                    if item["value"] == (flow.recipient_path or "")
                ),
                None,
            )

            if mode == "auto":
                flow.recipient_summary = _("Customer number automatically")
                resolved = ""
                resolved_label = ""
                resolved_path_label = ""
                for item in options[:12]:
                    masked, record_label = flow._recipient_preview_resolution(item["value"])
                    if masked:
                        resolved = masked
                        resolved_label = record_label
                        resolved_path_label = item["label"]
                        break
                if resolved:
                    flow.recipient_preview_note = _(
                        "Resolved automatically from %(path)s on %(record)s: %(number)s"
                    ) % {
                        "path": resolved_path_label,
                        "record": resolved_label,
                        "number": resolved,
                    }
                elif options:
                    labels = ", ".join(item["label"] for item in options[:3])
                    flow.recipient_preview_note = _(
                        "No recent record resolved to a usable number yet. At send time Odoo will check: %s"
                    ) % labels
                else:
                    flow.recipient_preview_note = _(
                        "No clear phone field was detected on this record type."
                    )
            elif selected:
                masked, record_label = flow._recipient_preview_resolution(selected["value"])
                flow.recipient_summary = selected["label"]
                if masked:
                    flow.recipient_preview_note = _(
                        "Resolved from %(record)s via %(path)s: %(number)s"
                    ) % {
                        "record": record_label,
                        "path": selected["label"],
                        "number": masked,
                    }
                else:
                    flow.recipient_preview_note = _(
                        "This phone path is valid, but no recent record currently resolves to a usable number."
                    )
            else:
                flow.recipient_summary = _("Choose a phone field")
                flow.recipient_preview_note = _(
                    "Select one of the phone fields detected from Odoo."
                )
