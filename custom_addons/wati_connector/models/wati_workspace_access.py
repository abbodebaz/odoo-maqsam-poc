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

        if can_access_feature(self.env, "templates") and "templates" not in by_id:
            templates = {
                "id": "templates",
                "title": "Template Center",
                "description": "Create templates WhatsAppSend it for review and monitor its approval and quality Odoo.",
                "icon": "fa-file-text-o",
                "action": "wati_connector.action_wati_templates",
                "tone": "info",
            }
            # Keep templates close to message tools and before automation.
            automation_index = next(
                (index for index, item in enumerate(features) if item.get("id") == "automation"),
                len(features),
            )
            features.insert(automation_index, templates)
            by_id["templates"] = templates

        # The original workspace exposed the monitor only to Odoo system admins.
        # WATI Administrators are intentionally narrower than Odoo admins, so add
        # the monitor for them when the company policy allows it.
        if can_access_feature(self.env, "monitor") and "monitor" not in by_id:
            monitor = {
                "id": "monitor",
                "title": "Integration monitoring",
                "description": "Watch Webhooks Processing cases and events that require attention.",
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
        sections = list(super()._workspace_help_sections())
        is_system_admin = self.env.user.has_group("base.group_system")
        can_templates = can_access_feature(self.env, "templates")
        can_automation = can_access_feature(self.env, "automation")
        can_logs = can_access_feature(self.env, "automation_logs")
        can_monitor = can_access_feature(self.env, "monitor")

        if can_templates:
            template_section = {
                "id": "templates",
                "title": "Templates",
                "icon": "fa-file-text-o",
                "articles": [
                    {
                        "id": "template-center",
                        "title": "Template management WhatsApp",
                        "summary": "Create templates in Odoo Synchronize and track adoption Meta.",
                        "steps": [
                            "Open the Template Center and click New to create a draft.",
                            "Type a technical name in lower case letters and choose the language and classification.",
                            "Type the text of the message and add variables with a formula {{name}} Or {{1}} Without mixing the two methods.",
                            "Enter a realistic example value for each variable and review the preview before submitting.",
                            "Click Submit to review; The template then becomes a mirror of a situation WATI/Meta The submitted copy is not modified directly.",
                            "Use Update Status or Sync From WATI When needed, approval, quality and rating statuses are automatically communicated via Webhook If template events are enabled in WATI.",
                        ],
                        "tips": [
                            "Create STANDARD Utility AndMarketing Powered by Odoo; Imported advanced templates appear for guesswork-free follow-up Payload Undocumented.",
                            "If you need to modify an approved or imported template, create a new copy and then submit the copy for review.",
                        ],
                    },
                    {
                        "id": "template-statuses",
                        "title": "Understanding template states",
                        "summary": "Meaning Draft AndPending AndApproved AndRejected AndPaused AndDisabled.",
                        "steps": [
                            "Draft: Still inside Odoo And adjustable.",
                            "Under review: Send it WATI To an audit trail Meta.",
                            "Certified: The template can be used for messaging and automation.",
                            "Rejected: Review the reason for rejection, if available, and then create a corrected version.",
                            "Paused or disabled: Do not rely on it to transmit until it is in good condition again.",
                        ],
                        "tips": ["Template quality is separate from certification status and may change after you start using it."],
                    },
                ],
            }
            automation_index = next(
                (index for index, section in enumerate(sections) if section.get("id") == "automation"),
                len(sections),
            )
            sections.insert(automation_index, template_section)

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
