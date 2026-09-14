from odoo import api, models


_TECHNICAL_MODEL_PREFIXES = (
    "ir.",
    "mail.",
    "bus.",
    "base.",
    "web.",
    "auth.",
    "digest.",
    "rating.",
)

_TECHNICAL_RELATION_FIELDS = {
    "create_uid",
    "write_uid",
    "company_id",
    "message_follower_ids",
    "message_ids",
    "message_partner_ids",
    "activity_ids",
    "rating_ids",
    "website_message_ids",
}

_BUSINESS_RELATION_HINTS = (
    "answer",
    "appointment",
    "case",
    "contact",
    "customer",
    "delivery",
    "event",
    "form",
    "invoice",
    "lead",
    "line",
    "manufactur",
    "move",
    "operation",
    "opportunit",
    "order",
    "partner",
    "payment",
    "picking",
    "production",
    "project",
    "purchase",
    "question",
    "receipt",
    "sale",
    "service",
    "stock",
    "task",
    "ticket",
    "transfer",
    "vendor",
    "workflow",
)


class WatiAutomationModelDiscovery(models.Model):
    _inherit = "wati.automation.rule"

    @api.model
    def _wati_model_is_readable(self, model_name):
        if not model_name or model_name not in self.env:
            return False
        if model_name.startswith(_TECHNICAL_MODEL_PREFIXES):
            return False
        try:
            return bool(self.env["ir.model.access"].check(model_name, "read", False))
        except Exception:
            return False

    @api.model
    def _wati_related_model_is_business_relevant(self, source_model, field):
        relation = getattr(field, "comodel_name", False)
        if not relation or relation not in self.env:
            return False
        if relation.startswith(_TECHNICAL_MODEL_PREFIXES):
            return False
        if field.name in _TECHNICAL_RELATION_FIELDS:
            return False

        source_namespace = (source_model or "").split(".", 1)[0]
        relation_namespace = relation.split(".", 1)[0]
        if source_namespace and source_namespace == relation_namespace:
            return True

        haystack = f"{field.name} {getattr(field, 'string', '')} {relation}".casefold()
        return any(token in haystack for token in _BUSINESS_RELATION_HINTS)

    @api.model
    def _wati_expand_business_models(self, direct_model_names, limit=120):
        """Expand app models with useful embedded/related business records.

        Odoo applications often expose important records only inside another form,
        so they do not have their own menu action. Examples include questionnaire
        answers, operation sub-records and custom form lines. The automation
        builder should still be able to monitor those models without hard-coding
        customer-specific module names.
        """
        discovered = set(direct_model_names or ())
        for model_name in sorted(direct_model_names or ()):
            if len(discovered) >= limit or model_name not in self.env:
                break
            Model = self.env[model_name]
            for field in Model._fields.values():
                if len(discovered) >= limit:
                    break
                if getattr(field, "type", "") not in ("many2one", "one2many", "many2many"):
                    continue
                if not self._wati_related_model_is_business_relevant(model_name, field):
                    continue
                relation = getattr(field, "comodel_name", False)
                if self._wati_model_is_readable(relation):
                    discovered.add(relation)
        return discovered

    @api.depends("app_menu_id")
    def _compute_available_model_ids(self):
        Menu = self.env["ir.ui.menu"]
        IrModel = self.env["ir.model"].sudo()

        for rule in self:
            rule.available_model_ids = IrModel.browse()
            if not rule.app_menu_id:
                continue

            menus = Menu.search([("id", "child_of", rule.app_menu_id.id)])
            try:
                menus = menus._filter_visible_menus()
            except Exception:
                pass

            direct_model_names = set()
            for action in menus.mapped("action"):
                if not action or action._name != "ir.actions.act_window":
                    continue
                model_name = (action.res_model or "").strip()
                if self._wati_model_is_readable(model_name):
                    direct_model_names.add(model_name)

            if not direct_model_names:
                continue

            model_names = rule._wati_expand_business_models(direct_model_names)
            candidates = IrModel.search([
                ("model", "in", sorted(model_names)),
                ("transient", "=", False),
                ("abstract", "=", False),
            ])
            rule.available_model_ids = candidates.filtered(
                lambda model: rule._wati_model_is_readable(model.model)
            )
