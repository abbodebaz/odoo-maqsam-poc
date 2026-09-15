from odoo import _, models
from odoo.exceptions import UserError


def _clean(value):
    if value in (None, False):
        return ""
    return str(value).strip()


class WatiOtpFlowCompletionValues(models.Model):
    _inherit = "wati.otp.flow"

    def _coerce_completion_value(self, field_record, value):
        """Turn user-friendly post-action values into native Odoo values.

        The OTP workflow editor intentionally lets administrators type the
        visible value they know from Odoo (for example ``Completed`` or a
        stage name). Selection fields, however, store technical keys, and
        many2one fields store record IDs. Resolve both here so post-actions
        stay portable across custom modules without exposing implementation
        details to the administrator.
        """
        self.ensure_one()
        raw = _clean(value)

        if field_record.ttype == "selection":
            if not raw:
                return False
            field = False
            if self.model_name and self.model_name in self.env:
                field = self.env[self.model_name]._fields.get(field_record.name)
            selection = []
            if field:
                try:
                    selection = field._description_selection(self.env)
                except Exception:
                    if isinstance(getattr(field, "selection", None), (list, tuple)):
                        selection = field.selection
            folded = raw.casefold()
            for key, label in selection:
                if folded in {_clean(key).casefold(), _clean(label).casefold()}:
                    return key
            return raw

        if field_record.ttype == "many2one":
            if not raw:
                return False
            relation = field_record.relation
            if not relation or relation not in self.env:
                raise UserError(_("The related model for this field is unavailable."))

            Target = self.env[relation].sudo()
            if raw.isdigit():
                candidate = Target.browse(int(raw)).exists()
                if candidate:
                    return candidate.id

            rec_name = getattr(Target, "_rec_name", "name") or "name"
            if rec_name not in Target._fields:
                rec_name = "display_name"

            candidate = Target.search([(rec_name, "=", raw)], limit=1)
            if candidate:
                return candidate.id

            candidates = Target.search([(rec_name, "ilike", raw)], limit=2)
            if len(candidates) == 1:
                return candidates.id
            if len(candidates) > 1:
                raise UserError(
                    _(
                        "More than one value matches '%s'. Use the exact visible value or record ID."
                    )
                    % raw
                )
            raise UserError(
                _("No value named '%s' was found for %s.")
                % (raw, field_record.field_description or field_record.name)
            )

        return super()._coerce_completion_value(field_record, value)
