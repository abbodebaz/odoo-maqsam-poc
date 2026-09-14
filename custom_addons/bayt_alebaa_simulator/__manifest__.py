{
    "name": "Bayt Alebaa WATI Simulator",
    "version": "19.0.1.0.0",
    "summary": "QA simulator for Bayt Alebaa business flows used by WATI automation testing",
    "category": "Tools",
    "author": "Abdulrhman Bazarah",
    "license": "LGPL-3",
    "depends": [
        "wati_connector",
        "contacts",
        "crm",
        "sale_management",
        "purchase",
        "account",
        "stock",
        "mrp",
        "project",
        "calendar"
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/simulator_data.xml",
        "views/simulator_views.xml"
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
