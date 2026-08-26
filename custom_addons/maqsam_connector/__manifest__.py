{
    "name": "Maqsam Connector",
    "version": "19.0.1.0.0",
    "summary": "Embed Maqsam Dialer inside Odoo",
    "category": "Productivity",
    "author": "Abdulrhman Bazarah",
    "license": "LGPL-3",
    "depends": ["base", "base_setup", "web", "contacts", "crm"],
    "data": [
        "views/res_config_settings_views.xml",
        "views/res_users_views.xml",
        "views/maqsam_menu.xml"
    ],
    "assets": {
        "web.assets_backend": [
            "maqsam_connector/static/src/js/dialer_action.js",
            "maqsam_connector/static/src/xml/dialer_action.xml",
            "maqsam_connector/static/src/scss/dialer.scss"
        ]
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
