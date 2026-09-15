{
    "name": "WATI Service Completion",
    "version": "19.0.11.0.6",
    "summary": "Standalone service-completion portal used to prove reusable WATI OTP workflows across custom Odoo modules",
    "category": "Services",
    "author": "Abdulrhman Bazarah",
    "license": "LGPL-3",
    "depends": ["wati_connector", "mail", "portal", "website"],
    "data": [
        "security/service_completion_security.xml",
        "security/ir.model.access.csv",
        "data/service_completion_sequence.xml",
        "views/service_completion_views.xml",
        "views/service_completion_portal_templates.xml"
    ],
    "assets": {
        "web.assets_frontend": [
            "wati_connector_service_completion/static/src/css/service_completion_portal.css"
        ]
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
