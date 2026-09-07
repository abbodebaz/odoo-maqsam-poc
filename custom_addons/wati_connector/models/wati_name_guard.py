from odoo import api, models


_GENERIC_NAMES = {
    "",
    "whatsapp",
    "wati",
    "unknown",
    "none",
    "null",
    "-",
    "عميل واتساب",
}


def _is_generic(value):
    return str(value or "").strip().lower() in _GENERIC_NAMES


def _meaningful(value):
    clean = str(value or "").strip()
    return clean if clean and not _is_generic(clean) else ""


class WatiConversationNameGuard(models.Model):
    _inherit = "wati.conversation"

    @api.model_create_multi
    def create(self, vals_list):
        normalized_list = []
        for incoming in vals_list:
            vals = dict(incoming)
            wa_id = str(vals.get("wa_id") or "").strip()
            sender = _meaningful(vals.get("sender_name"))

            if _is_generic(vals.get("sender_name")):
                vals["sender_name"] = wa_id or False

            if _is_generic(vals.get("name")):
                vals["name"] = sender or wa_id or "رقم غير متوفر"

            normalized_list.append(vals)
        return super().create(normalized_list)

    def write(self, vals):
        # Normalize per record so a generic outbound/status webhook can never
        # overwrite a useful customer name that was learned earlier.
        result = True
        for record in self:
            normalized = dict(vals)
            wa_id = str(normalized.get("wa_id") or record.wa_id or "").strip()

            if "sender_name" in normalized:
                incoming_sender = _meaningful(normalized.get("sender_name"))
                current_sender = _meaningful(record.sender_name)
                if not incoming_sender:
                    if current_sender:
                        normalized.pop("sender_name", None)
                    elif wa_id:
                        normalized["sender_name"] = wa_id
                    else:
                        normalized.pop("sender_name", None)
                elif _is_generic(record.name) or str(record.name or "").strip() == str(record.wa_id or "").strip():
                    normalized.setdefault("name", incoming_sender)

            if "name" in normalized and _is_generic(normalized.get("name")):
                sender = _meaningful(normalized.get("sender_name")) or _meaningful(record.sender_name)
                normalized["name"] = sender or wa_id or "رقم غير متوفر"

            result = super(WatiConversationNameGuard, record).write(normalized) and result
        return result
