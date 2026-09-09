from datetime import timedelta

from odoo import api, fields, models


class WatiWorkspaceGateway(models.TransientModel):
    """Read-only gateway for the WhatsApp workspace and in-app help center.

    The dashboard deliberately receives a feature registry instead of hard-coding
    navigation in the client. Future WATI features can extend
    ``_workspace_features`` / ``_workspace_help_sections`` without rebuilding the
    workspace shell.
    """

    _name = "wati.workspace.gateway"
    _description = "WhatsApp Workspace Gateway"

    @api.model
    def _workspace_features(self):
        is_admin = self.env.user.has_group("base.group_system")
        features = [
            {
                "id": "inbox",
                "title": "Inbox",
                "description": "Receive and respond to customer conversations from a single workspace.",
                "icon": "fa-comments",
                "action": "wati_connector.action_wati_inbox",
                "tone": "success",
            },
            {
                "id": "conversations",
                "title": "Conversation Log",
                "description": "See conversations, customers, admins, and the latest activity for each conversation.",
                "icon": "fa-commenting-o",
                "action": "wati_connector.action_wati_conversations",
                "tone": "primary",
            },
            {
                "id": "messages",
                "title": "Message Log",
                "description": "Track incoming and outgoing messages and their status within WhatsApp.",
                "icon": "fa-envelope-o",
                "action": "wati_connector.action_wati_messages",
                "tone": "info",
            },
            {
                "id": "automation",
                "title": "Automation Center",
                "description": "Create scenarios WhatsApp linked to events Odoo Without code.",
                "icon": "fa-bolt",
                "action": "wati_connector.action_wati_automation_studio",
                "tone": "purple",
            },
            {
                "id": "automation_logs",
                "title": "Run Log",
                "description": "Know when your automation ran, what was sent, and the result of each run.",
                "icon": "fa-list-alt",
                "action": "wati_connector.action_wati_automation_logs",
                "tone": "neutral",
            },
            {
                "id": "help",
                "title": "Help Center",
                "description": "Learn to prepare WATI Use conversations, automation, and problem solving.",
                "icon": "fa-book",
                "action": "wati_connector.action_wati_help_center",
                "tone": "help",
            },
        ]
        if is_admin:
            features.extend(
                [
                    {
                        "id": "monitor",
                        "title": "Integration monitoring",
                        "description": "Watch Webhooks Processing cases and events that require attention.",
                        "icon": "fa-heartbeat",
                        "action": "wati_connector.action_wati_webhook_events",
                        "tone": "warning",
                        "admin": True,
                    },
                    {
                        "id": "settings",
                        "title": "Settings",
                        "description": "Contact management WATI And theWebhook and inbox features.",
                        "icon": "fa-cog",
                        "action": "wati_connector.action_wati_settings",
                        "tone": "settings",
                        "admin": True,
                    },
                ]
            )
        return features

    @api.model
    def _workspace_help_sections(self):
        sections = [
            {
                "id": "start",
                "title": "Start here",
                "icon": "fa-rocket",
                "articles": [
                    {
                        "id": "overview",
                        "title": "What is space? WhatsApp?",
                        "summary": "Quick look at your inbox, logs, automation, and integration monitoring.",
                        "steps": [
                            "Use the home page as the entry point for all services WhatsApp inside Odoo.",
                            "The inbox is for daily work and responding to clients.",
                            "Automation Center connects events Odoo With templates WATI Without writing code.",
                            "Integration monitoring is for administrators to check Webhooks and treatment status.",
                        ],
                        "tips": ["Always start from the home page instead of moving between technical screens."],
                    },
                    {
                        "id": "connect-wati",
                        "title": "Preparation WATI For the first time",
                        "summary": "Processing steps API AndWebhook Before starting work.",
                        "steps": [
                            "Open Settings from Home with an administrator account.",
                            "Enter WATI API Endpoint AndAccess Token Then click Test Connection.",
                            "Create Webhook Secret And save the settings.",
                            "Copy Webhook URL apparent in Odoo And add it to Webhooks inside WATI.",
                            "Send a test message and ensure that the message appears in the Message Log and Integration Monitor.",
                        ],
                        "tips": [
                            "Do not use Access Token Same asWebhook Secret.",
                            "If it changes Webhook Secret You must update the link inside WATI Also.",
                        ],
                    },
                ],
            },
            {
                "id": "inbox",
                "title": "Conversations",
                "icon": "fa-comments",
                "articles": [
                    {
                        "id": "use-inbox",
                        "title": "Use your inbox",
                        "summary": "Receiving messages, opening a conversation and responding to the customer.",
                        "steps": [
                            "Open your inbox from Home.",
                            "Select the desired conversation from the list.",
                            "Review the context of the conversation, then write and send your response.",
                            "Use conversation history when you need to do historical research or find out who is responsible for a customer.",
                        ],
                        "tips": ["Message log is convenient for tracking, and inbox is convenient for daily work."],
                    },
                    {
                        "id": "message-statuses",
                        "title": "Understand message statuses",
                        "summary": "The difference between sending, delivering, reading and replying.",
                        "steps": [
                            "Sent: The message went out WATI.",
                            "Delivered: The message has arrived WhatsApp At the recipient.",
                            "Read done: Confirm WhatsApp That the message has been read when receipts are available.",
                            "Customer response: A new reply linked to the conversation has arrived.",
                        ],
                        "tips": ["The Sent status is not considered proof of delivery; Monitor the entire life cycle."],
                    },
                ],
            },
            {
                "id": "automation",
                "title": "Automation",
                "icon": "fa-bolt",
                "articles": [
                    {
                        "id": "first-automation",
                        "title": "Create your first automation",
                        "summary": "From event selection to testing and activation.",
                        "steps": [
                            "Select the application within Odoo Then the type of record you want to monitor.",
                            "Specify when transmission begins and choose the field, condition, and value when needed.",
                            "Select the recipient automatically or choose a number from the record or a linked record.",
                            "Choose a template WATI Link its variables to data Odoo.",
                            "In the Review step, create a preview and then perform a test submission.",
                            "Activate automation only after the ready status is displayed correctly.",
                        ],
                        "tips": ["Use a test submission before your first activation in a real company environment."],
                    },
                    {
                        "id": "automation-logs",
                        "title": "Read playback log",
                        "summary": "How do you know if the automation has been triggered and what happened to the message?.",
                        "steps": [
                            "Open the run log from Home or from the Automation Center.",
                            "Review the automation, the record that triggered it, the recipient number, and the template.",
                            "The status of the request being accepted means that WATI Before requesting transmission.",
                            "Delivery and read cases come later from Webhooks When available.",
                        ],
                        "tips": ["Technical details are provided to the administrator only when needed for investigation."],
                    },
                ],
            },
            {
                "id": "monitoring",
                "title": "Monitoring and problem solving",
                "icon": "fa-heartbeat",
                "articles": [
                    {
                        "id": "webhook-monitor",
                        "title": "Monitor Webhook",
                        "summary": "Use it as a black box to see what has arrived from WATI And what he treated Odoo.",
                        "steps": [
                            "Open Integration Monitoring with an administrator account.",
                            "See the intelligible event such as Sent, Delivered, or Read instead of the raw noun.",
                            "See processing status inside Odoo Separately from case WATI.",
                            "Filter needs attention to find Callback Arrived from WATI It is not associated with a known message or operation.",
                            "Use technical details and...Payload Raw only upon advanced investigation.",
                        ],
                        "tips": ["Callbacks Duplicates are saved for auditing but hidden by default so the page stays clean."],
                    },
                    {
                        "id": "message-not-sent",
                        "title": "The message did not arrive",
                        "summary": "Quick order diagnosis without guesswork.",
                        "steps": [
                            "Start from playback log: Do you? WATI Before requesting transmission?",
                            "Verify the recipient number and template WATI and template variables.",
                            "Review Integration Monitoring to see if events have arrived Sent Or Delivered Or Failed.",
                            "If it doesn’t arrive Webhook Originally, check out Webhook URL And theSecret And preparation WATI.",
                        ],
                        "tips": ["Don’t rely on one interface to judge; Run history and integration monitoring complement each other."],
                    },
                ],
            },
        ]
        return sections

    @api.model
    def get_dashboard_data(self):
        now = fields.Datetime.now()
        since = now - timedelta(hours=24)
        config = self.env["ir.config_parameter"].sudo()

        has_api = bool(
            (config.get_param("wati_connector.api_endpoint") or "").strip()
            and (config.get_param("wati_connector.api_token") or "").strip()
        )
        has_webhook = bool((config.get_param("wati_connector.webhook_token") or "").strip())
        message_count = self.env["wati.message"].sudo().search_count([])
        automation_count = (
            self.env["wati.automation.rule"]
            .sudo()
            .with_context(active_test=False)
            .search_count([])
        )

        onboarding = [
            {
                "id": "api",
                "title": "Link an account WATI",
                "description": "Add Endpoint AndAccess Token And test the connection.",
                "done": has_api,
                "action": "wati_connector.action_wati_settings",
            },
            {
                "id": "webhook",
                "title": "Preparation Webhook",
                "description": "Fasten WATI Titled Webhook The safe forOdoo.",
                "done": has_webhook,
                "action": "wati_connector.action_wati_settings",
            },
            {
                "id": "message",
                "title": "Receiving the first message",
                "description": "Make sure messages reach your inbox and message history.",
                "done": bool(message_count),
                "action": "wati_connector.action_wati_inbox",
            },
            {
                "id": "automation",
                "title": "Create your first automation",
                "description": "Build a scenario and test it before activation.",
                "done": bool(automation_count),
                "action": "wati_connector.action_wati_automation_studio",
            },
        ]

        return {
            "features": self._workspace_features(),
            "connection": {
                "configured": has_api,
                "webhook_configured": has_webhook,
                "ready": has_api and has_webhook,
            },
            "kpis": {
                "unread_conversations": self.env["wati.conversation"].sudo().search_count(
                    [("unread_count", ">", 0)]
                ),
                "messages_24h": self.env["wati.message"].sudo().search_count(
                    [("received_at", ">=", since)]
                ),
                "active_automations": (
                    self.env["wati.automation.rule"]
                    .sudo()
                    .with_context(active_test=False)
                    .search_count([("active", "=", True)])
                ),
                "webhook_attention": self.env["wati.webhook.event"].sudo().search_count(
                    [
                        ("processing_state", "=", "needs_attention"),
                        ("received_at", ">=", since),
                    ]
                ),
            },
            "onboarding": onboarding,
            "onboarding_done": sum(1 for item in onboarding if item["done"]),
            "onboarding_total": len(onboarding),
            "is_admin": self.env.user.has_group("base.group_system"),
        }

    @api.model
    def get_help_content(self):
        return {"sections": self._workspace_help_sections()}
