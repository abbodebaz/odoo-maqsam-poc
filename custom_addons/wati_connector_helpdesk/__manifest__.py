{
    "name": "WATI Connector - Odoo Helpdesk",
    "version": "19.0.1.0.0",
    "summary": "Optional WATI WhatsApp integration for Odoo Enterprise Helpdesk tickets and stages",
    "category": "Services/Helpdesk",
    "author": "Abdulrhman Bazarah",
    "license": "LGPL-3",
    "depends": ["wati_connector", "helpdesk"],
    "data": [
        "views/helpdesk_wati_views.xml"
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
