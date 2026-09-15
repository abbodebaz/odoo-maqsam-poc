from odoo import _, api, fields, models

from ..utils.phone import normalize_whatsapp_number


def _clean(value):
    if value in (None, False):
        return ""
    return str(value).strip()


class WatiSmartButtonAppPolicy(models.Model):
    _name = "wati.smart.button.app.policy"
    _description = "WATI Smart Button Application Policy"
    _order = "sequence, app_name, id"

    sequence = fields.Integer(default=10)
    active = fields.Boolean(string="WhatsApp enabled", default=True)
    app_menu_id = fields.Many2one("ir.ui.menu", string="Application", required=True, ondelete="cascade", index=True)
    app_name = fields.Char(related="app_menu_id.name", string="Application", store=True, readonly=True)
    model_names = fields.Text(string="Detected record types", readonly=True)
    model_count = fields.Integer(string="Record types", compute="_compute_model_count")

    _app_unique = models.Constraint("UNIQUE(app_menu_id)", "A WhatsApp policy already exists for this application.")

    @api.depends("model_names")
    def _compute_model_count(self):
        for policy in self:
            policy.model_count = len(policy._models())

    def _models(self):
        self.ensure_one()
        return [item for item in _clean(self.model_names).split("\n") if item]

    @api.model
    def _menu_action_model(self, menu):
        action = menu.action
        if action and action._name == "ir.actions.act_window":
            model_name = _clean(action.res_model)
            if model_name and model_name in self.env:
                model = self.env["ir.model"].sudo().search([("model", "=", model_name)], limit=1)
                if model and not model.transient and not model.abstract:
                    return model_name
        return False

    @api.model
    def _discover_apps(self):
        Menu = self.env["ir.ui.menu"].sudo().with_context(active_test=False)
        roots = Menu.search([("parent_id", "=", False), ("active", "=", True)], order="sequence, id")
        result = []
        for root in roots:
            menus = Menu.search([("id", "child_of", root.id), ("active", "=", True)])
            models_found = {model_name for menu in menus if (model_name := self._menu_action_model(menu))}
            if models_found:
                result.append((root, sorted(models_found)))
        return result

    @api.model
    def _disable_legacy_generated_buttons(self):
        """The chatter controls are the single global UI; old generated header buttons must never coexist."""
        Location = self.env["wati.smart.button.location"].sudo().with_context(active_test=False)
        locations = Location.search([])
        generated = locations.mapped("generated_view_id").sudo().with_context(active_test=False).exists()
        if generated:
            generated.write({"active": False})
        # Also catch orphaned generated extensions left by older records/releases.
        orphaned = self.env["ir.ui.view"].sudo().with_context(active_test=False).search([
            ("name", "like", "WATI Smart Button ·%"),
            ("active", "=", True),
        ])
        if orphaned:
            orphaned.write({"active": False})
        return True

    @api.model
    def sync_discovered_apps(self):
        Policy = self.sudo().with_context(active_test=False)
        discovered_ids = set()
        for root, model_names in self._discover_apps():
            discovered_ids.add(root.id)
            policy = Policy.search([("app_menu_id", "=", root.id)], limit=1)
            vals = {"model_names": "\n".join(model_names), "sequence": root.sequence or 10}
            if policy:
                policy.write(vals)
            else:
                vals.update({"app_menu_id": root.id, "active": True})
                Policy.create(vals)

        # Keep the screen truthful: policies for removed/non-application roots are archived,
        # while a user's explicit ON/OFF choice is preserved for every discovered app.
        stale = Policy.search([("app_menu_id", "not in", sorted(discovered_ids))]) if discovered_ids else Policy.search([])
        if stale:
            stale.write({"active": False})
        self._disable_legacy_generated_buttons()
        return True

    @api.model
    def action_refresh_applications(self):
        self.sync_discovered_apps()
        return {
            "type": "ir.actions.act_window",
            "name": _("Smart Buttons & Customer Timeline"),
            "res_model": "wati.smart.button.app.policy",
            "view_mode": "list",
            "target": "current",
            "context": {"active_test": False},
        }

    @api.model
    def policy_for_model(self, model_name):
        model_name = _clean(model_name)
        if not model_name or model_name not in self.env:
            return self.browse()
        self.sync_discovered_apps()
        for policy in self.sudo().with_context(active_test=False).search([]):
            if model_name in policy._models():
                return policy
        return self.browse()

    @api.model
    def smart_button_state(self, model_name):
        policy = self.policy_for_model(model_name)
        return {"enabled": bool(policy and policy.active), "app_id": policy.app_menu_id.id if policy else False, "app_name": policy.app_name if policy else False}


class WatiSmartButtonLocationGlobalOnly(models.Model):
    _inherit = "wati.smart.button.location"

    def _sync_generated_view(self):
        """Legacy per-form header buttons are retired; always keep their generated views disabled."""
        for record in self:
            current = record.generated_view_id.sudo().with_context(active_test=False).exists()
            if current and current.active:
                current.write({"active": False})
        return True


class ResConfigSettingsWatiSmartButtons(models.TransientModel):
    _inherit = "res.config.settings"

    def action_wati_manage_smart_buttons(self):
        self.env["wati.smart.button.app.policy"].sync_discovered_apps()
        return self.env.ref("wati_connector.action_wati_smart_button_app_policies").read()[0]


class WatiGlobalRecordResolver(models.AbstractModel):
    _name = "wati.global.record.resolver"
    _description = "WATI Global Record Resolver"

    @api.model
    def _resolve_path(self, record, path):
        current = record
        for part in path.split("."):
            if not current or not hasattr(current, "_fields") or part not in current._fields:
                return False
            current = current[part]
        return current

    @api.model
    def resolve_record(self, record):
        partner = record if record._name == "res.partner" else self.env["res.partner"].browse()
        if not partner:
            for path in ("partner_id", "commercial_partner_id", "customer_id", "contact_id"):
                candidate = self._resolve_path(record, path)
                if getattr(candidate, "_name", "") == "res.partner" and len(candidate) == 1:
                    partner = candidate
                    break
        candidates = []
        for path in ("mobile", "phone", "customer_mobile", "partner_id.mobile", "partner_id.phone", "commercial_partner_id.mobile", "commercial_partner_id.phone", "customer_id.mobile", "customer_id.phone"):
            value = self._resolve_path(record, path)
            if value:
                candidates.append(value)
        if partner:
            for field_name in ("mobile", "phone"):
                if field_name in partner._fields and partner[field_name]:
                    candidates.append(partner[field_name])
        phone = False
        for value in candidates:
            phone = normalize_whatsapp_number(value)
            if phone:
                break
        return partner, phone


class WatiUniversalComposeGlobal(models.TransientModel):
    _inherit = "wati.universal.compose.wizard"

    @api.model
    def default_get(self, field_list):
        values = super().default_get(field_list)
        context = self.env.context
        if values.get("source_res_id") or not context.get("wati_global_button"):
            return values
        model_name = _clean(context.get("active_model"))
        res_id = int(context.get("active_id") or 0)
        policy = self.env["wati.smart.button.app.policy"].policy_for_model(model_name)
        if not policy or not policy.active or not model_name or not res_id:
            return values
        record = self.env[model_name].browse(res_id).exists()
        if not record:
            return values
        partner, phone = self.env["wati.global.record.resolver"].resolve_record(record)
        values.update({"source_model": model_name, "source_res_id": res_id, "record_name": record.display_name, "partner_id": partner.id if partner else False, "phone": phone or ""})
        return values


class WatiUniversalTimelineGlobal(models.TransientModel):
    _inherit = "wati.universal.timeline.wizard"

    @api.model
    def default_get(self, field_list):
        values = super().default_get(field_list)
        context = self.env.context
        if values.get("source_res_id") or not context.get("wati_global_button"):
            return values
        model_name = _clean(context.get("active_model"))
        res_id = int(context.get("active_id") or 0)
        policy = self.env["wati.smart.button.app.policy"].policy_for_model(model_name)
        if not policy or not policy.active or not model_name or not res_id:
            return values
        record = self.env[model_name].browse(res_id).exists()
        if not record:
            return values
        partner, phone = self.env["wati.global.record.resolver"].resolve_record(record)
        values.update({"source_model": model_name, "source_res_id": res_id, "record_name": record.display_name, "partner_id": partner.id if partner else False, "phone": phone or ""})
        return values
