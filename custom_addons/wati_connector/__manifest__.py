{
    "name": "WATI WhatsApp Connector",
    "version": "19.0.3.0.0",
    "summary": "WATI WhatsApp inbox, guided no-code automation engine, webhooks and API integration for Odoo",
    "category": "Productivity",
    "author": "Abdulrhman Bazarah",
    "license": "LGPL-3",
    "depends": ["base", "base_setup", "web", "contacts", "crm", "base_automation"],
    "data": [
        "security/ir.model.access.csv",
        "data/wati_ticket_sequence.xml",
        "views/res_config_settings_views.xml",
        "views/res_users_views.xml",
        "views/wati_inbox_templates.xml",
        "views/wati_views.xml",
        "views/wati_ticket_views.xml",
        "views/wati_automation_views.xml",
        "views/wati_automation_improvements_views.xml",
        "views/wati_automation_ux_views.xml",
        "data/wati_automation_demo.xml",
        "data/wati_automation_upgrade.xml"
    ],
    "assets": {
        "web.assets_backend": [
            "wati_connector/static/src/css/wati_automation_ux.css"
        ]
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
