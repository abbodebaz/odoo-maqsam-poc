from odoo import api, models

from ..services.template_catalog import clean, extract_placeholders


class WatiTemplateVariableSave(models.Model):
    _inherit = "wati.template"

    @api.model
    def _repair_variable_create_commands(self, body, commands):
        """Rebuild incomplete x2many create commands coming from the web client.

        Odoo may omit readonly values from a freshly generated one2many row when
        the parent form is saved. The template editor intentionally owns the
        variable name/position, so they must always be derived from the body,
        never trusted from the browser payload.
        """
        tokens = extract_placeholders(body or "")
        if not tokens:
            return []

        samples_by_name = {}
        samples_by_position = {}
        ordered_samples = []

        for command in commands or []:
            if not isinstance(command, (list, tuple)) or not command:
                continue
            operation = command[0]
            values = (
                command[2]
                if len(command) > 2 and isinstance(command[2], dict)
                else {}
            )
            if operation != 0:
                continue

            sample = values.get("sample_value") or ""
            ordered_samples.append(sample)

            name = clean(values.get("name"))
            if name:
                samples_by_name[name] = sample

            position = values.get("position")
            try:
                position = int(position) if position not in (None, False, "") else None
            except (TypeError, ValueError):
                position = None
            if position:
                samples_by_position[position] = sample

        rebuilt = []
        for position, token in enumerate(tokens, start=1):
            sample = samples_by_name.get(token)
            if sample is None:
                sample = samples_by_position.get(position)
            if sample is None and position <= len(ordered_samples):
                sample = ordered_samples[position - 1]
            rebuilt.append(
                (
                    0,
                    0,
                    {
                        "name": token,
                        "position": position,
                        "sample_value": sample or "",
                    },
                )
            )
        return rebuilt

    @api.model
    def _has_incomplete_variable_create(self, commands):
        for command in commands or []:
            if not isinstance(command, (list, tuple)) or not command:
                continue
            if command[0] != 0:
                continue
            values = (
                command[2]
                if len(command) > 2 and isinstance(command[2], dict)
                else {}
            )
            if not clean(values.get("name")) or not values.get("position"):
                return True
        return False

    @api.model_create_multi
    def create(self, vals_list):
        prepared_list = []
        for vals in vals_list:
            prepared = dict(vals or {})
            commands = prepared.get("variable_ids")
            if commands is not None and self._has_incomplete_variable_create(commands):
                prepared["variable_ids"] = self._repair_variable_create_commands(
                    prepared.get("body") or "",
                    commands,
                )
            prepared_list.append(prepared)
        return super().create(prepared_list)

    def write(self, vals):
        commands = (vals or {}).get("variable_ids")
        if not commands or not self._has_incomplete_variable_create(commands):
            return super().write(vals)

        # A normal form write targets one template. Keep multi-record writes safe
        # by rebuilding the body contract independently for every record.
        result = True
        for record in self:
            prepared = dict(vals)
            prepared["variable_ids"] = record._repair_variable_create_commands(
                prepared.get("body", record.body) or "",
                commands,
            )
            result = super(WatiTemplateVariableSave, record).write(prepared) and result
        return result
