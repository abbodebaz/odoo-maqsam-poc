from odoo import api, models

from ..services.feature_access import (
    FEATURE_ACCESS_REGISTRY,
    can_access_feature,
    get_feature_mode,
    is_wati_admin,
)


class WatiWorkspaceAccess(models.TransientModel):
    _inherit = "wati.workspace.gateway"

    @api.model
    def _workspace_features(self):
        features = list(super()._workspace_features())
        by_id = {feature["id"]: feature for feature in features}

        # The original workspace exposed the monitor only to Odoo system admins.
        # WATI Administrators are intentionally narrower than Odoo admins, so add
        # the monitor for them when the company policy allows it.
        if can_access_feature(self.env, "monitor") and "monitor" not in by_id:
            monitor = {
                "id": "monitor",
                "title": "مراقبة التكامل",
                "description": "راقب Webhooks وحالات المعالجة والأحداث التي تحتاج انتباه.",
                "icon": "fa-heartbeat",
                "action": "wati_connector.action_wati_webhook_events",
                "tone": "warning",
            }
            features.append(monitor)
            by_id["monitor"] = monitor

        visible = []
        for feature in features:
            feature_id = feature.get("id")
            if feature_id in FEATURE_ACCESS_REGISTRY:
                if not can_access_feature(self.env, feature_id):
                    continue
                feature = dict(feature)
                feature["admin"] = get_feature_mode(self.env, feature_id) == "admin"
            visible.append(feature)
        return visible

    @api.model
    def _workspace_help_sections(self):
        sections = super()._workspace_help_sections()
        is_system_admin = self.env.user.has_group("base.group_system")
        can_automation = can_access_feature(self.env, "automation")
        can_logs = can_access_feature(self.env, "automation_logs")
        can_monitor = can_access_feature(self.env, "monitor")

        filtered = []
        for section in sections:
            section = dict(section)
            articles = list(section.get("articles") or [])

            if section.get("id") == "start":
                articles = [
                    article
                    for article in articles
                    if article.get("id") != "connect-wati" or is_system_admin
                ]
            elif section.get("id") == "automation":
                articles = [
                    article
                    for article in articles
                    if (
                        article.get("id") == "first-automation" and can_automation
                    )
                    or (
                        article.get("id") == "automation-logs" and can_logs
                    )
                ]
            elif section.get("id") == "monitoring":
                articles = [
                    article
                    for article in articles
                    if (
                        article.get("id") == "webhook-monitor" and can_monitor
                    )
                    or (
                        article.get("id") == "message-not-sent"
                        and (can_logs or can_monitor)
                    )
                ]

            if articles:
                section["articles"] = articles
                filtered.append(section)
        return filtered

    @api.model
    def get_dashboard_data(self):
        data = super().get_dashboard_data()
        is_system_admin = self.env.user.has_group("base.group_system")
        permissions = {
            feature_id: can_access_feature(self.env, feature_id)
            for feature_id in FEATURE_ACCESS_REGISTRY
        }
        permissions.update(
            {
                "inbox": self.env.user.has_group("wati_connector.group_wati_user")
                or is_wati_admin(self.env),
                "help": self.env.user.has_group("wati_connector.group_wati_user")
                or is_wati_admin(self.env),
                "settings": is_system_admin,
            }
        )

        onboarding = []
        for item in data.get("onboarding", []):
            item_id = item.get("id")
            if item_id in {"api", "webhook"} and not is_system_admin:
                continue
            if item_id == "automation" and not permissions["automation"]:
                continue
            onboarding.append(item)

        data["onboarding"] = onboarding
        data["onboarding_done"] = sum(1 for item in onboarding if item.get("done"))
        data["onboarding_total"] = len(onboarding)
        data["permissions"] = permissions
        data["is_admin"] = is_wati_admin(self.env)
        return data
