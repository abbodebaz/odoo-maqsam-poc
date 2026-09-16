from odoo import _, fields, models
from odoo.exceptions import UserError


def _clean(value):
    if value in (None, False):
        return ""
    return str(value).strip()


class WatiOtpFlowRelational(models.Model):
    _inherit = "wati.otp.flow"

    completion_field_id = fields.Many2one(
        "ir.model.fields",
        string="Field to update",
        ondelete="set null",
        domain="[('model_id', '=', model_id), ('store', '=', True), ('ttype', 'in', ['char', 'text', 'selection', 'boolean', 'integer', 'float', 'many2one'])]",
        help="For relational fields such as Stage, enter the visible record name as the new value, for example: Closed.",
    )

    def _match_trigger(self, record):
        self.ensure_one()
        if not self.trigger_field_id or self.trigger_field_id.name not in record._fields:
            return False

        field_name = self.trigger_field_id.name
        field = record._fields[field_name]
        value = record[field_name]

        if self.trigger_operator == "true":
            return bool(value)
        if self.trigger_operator != "equals":
            return bool(value)

        expected = _clean(self.trigger_value).casefold()
        if not expected:
            return False

        # Relational fields should match what the user sees in Odoo, not only
        # their internal database id. This is especially important for stages.
        if field.type == "many2one":
            if not value:
                return False
            candidates = {
                _clean(value.id).casefold(),
                _clean(value.display_name).casefold(),
            }
            if "name" in value._fields:
                candidates.add(_clean(value.name).casefold())
            return expected in candidates

        # Selection fields may be configured using either the technical key or
        # the human-readable label shown in Odoo.
        if field.type == "selection":
            raw = _clean(value)
            if raw.casefold() == expected:
                return True
            try:
                selection = field._description_selection(self.env)
            except Exception:
                selection = []
            label = next((label for key, label in selection if _clean(key) == raw), "")
            return _clean(label).casefold() == expected

        return _clean(value).casefold() == expected

    def _coerce_completion_value(self, field_record, value):
        if field_record.ttype != "many2one":
            return super()._coerce_completion_value(field_record, value)

        raw = _clean(value)
        if not raw:
            return False

        relation = field_record.relation
        if not relation or relation not in self.env:
            raise UserError(_("The related model for this completion field is unavailable."))

        Target = self.env[relation].sudo()
        if raw.isdigit():
            candidate = Target.browse(int(raw)).exists()
            if candidate:
                return candidate.id

        rec_name = getattr(Target, "_rec_name", "name") or "name"
        if rec_name not in Target._fields:
            rec_name = "display_name"

        candidate = Target.search([(rec_name, "=", raw)], limit=1)
        if not candidate:
            candidate = Target.search([(rec_name, "ilike", raw)], limit=2)
            if len(candidate) > 1:
                raise UserError(
                    _("More than one related record matches '%s'. Use the exact visible name.")
                    % raw
                )
        if not candidate:
            raise UserError(
                _("No related record named '%s' was found for the completion field.") % raw
            )
        return candidate.id
