{
    "name": "WATI WhatsApp Connector",
    "version": "19.0.1.3.0",
    "summary": "WATI WhatsApp inbox foundation, webhooks and API integration for Odoo",
    "category": "Productivity",
    "author": "Abdulrhman Bazarah",
    "license": "LGPL-3",
    "depends": ["base", "base_setup", "web", "contacts", "crm"],
    "data": [
        "security/ir.model.access.csv",
        "data/wati_ticket_sequence.xml",
        "views/res_config_settings_views.xml",
        "views/res_users_views.xml",
        "views/wati_inbox_templates.xml",
        "views/wati_views.xml",
        "views/wati_ticket_views.xml"
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
