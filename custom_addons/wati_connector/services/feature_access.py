from odoo.exceptions import AccessError


ACCESS_ALL = "all"
ACCESS_ADMIN = "admin"
VALID_ACCESS_MODES = {ACCESS_ALL, ACCESS_ADMIN}


FEATURE_ACCESS_REGISTRY = {
    "conversations": {
        "label": "سجل المحادثات",
        "parameter": "wati_connector.access_conversations",
        "default": ACCESS_ALL,
        "menu_xmlids": ["wati_connector.menu_wati_conversations"],
        "acl_xmlids": [],
    },
    "messages": {
        "label": "سجل الرسائل",
        "parameter": "wati_connector.access_messages",
        "default": ACCESS_ALL,
        "menu_xmlids": ["wati_connector.menu_wati_messages"],
        "acl_xmlids": [],
    },
    "automation": {
        "label": "مركز الأتمتة",
        "parameter": "wati_connector.access_automation",
        "default": ACCESS_ADMIN,
        "menu_xmlids": ["wati_connector.menu_wati_automation_rules"],
        "acl_xmlids": [
            "wati_connector.access_wati_automation_rule_admin",
            "wati_connector.access_wati_automation_condition_admin",
            "wati_connector.access_wati_automation_parameter_admin",
            "wati_connector.access_wati_automation_value_choice_admin",
            "wati_connector.access_wati_automation_template_choice_admin",
        ],
    },
    "automation_logs": {
        "label": "سجل التشغيل",
        "parameter": "wati_connector.access_automation_logs",
        "default": ACCESS_ADMIN,
        "menu_xmlids": ["wati_connector.menu_wati_automation_logs"],
        "acl_xmlids": ["wati_connector.access_wati_automation_log_supervisor"],
    },
    "monitor": {
        "label": "مراقبة Webhook",
        "parameter": "wati_connector.access_monitor",
        "default": ACCESS_ADMIN,
        "menu_xmlids": ["wati_connector.menu_wati_webhook_events"],
        "acl_xmlids": ["wati_connector.access_wati_webhook_event_admin"],
    },
}


def feature_definition(feature_id):
    return FEATURE_ACCESS_REGISTRY.get(feature_id) or {}


def get_feature_mode(env, feature_id):
    definition = feature_definition(feature_id)
    if not definition:
        return ACCESS_ALL
    raw = env["ir.config_parameter"].sudo().get_param(
        definition["parameter"], definition["default"]
    )
    value = str(raw or "").strip().lower()
    return value if value in VALID_ACCESS_MODES else definition["default"]


def is_wati_admin(env, user=None):
    user = user or env.user
    return bool(
        user.id == env.ref("base.user_root", raise_if_not_found=False).id
        if env.ref("base.user_root", raise_if_not_found=False)
        else False
    ) or user.has_group("base.group_system") or user.has_group(
        "wati_connector.group_wati_admin"
    )


def can_access_feature(env, feature_id, user=None):
    user = user or env.user
    if is_wati_admin(env, user=user):
        return True
    if not user.has_group("wati_connector.group_wati_user"):
        return False
    return get_feature_mode(env, feature_id) == ACCESS_ALL


def ensure_feature_access(env, feature_id, user=None):
    if can_access_feature(env, feature_id, user=user):
        return True
    label = feature_definition(feature_id).get("label") or "هذه الميزة"
    raise AccessError(
        f"لا تملك صلاحية الوصول إلى {label}. تواصل مع مشرف WhatsApp إذا كنت تحتاج هذه الصلاحية."
    )


def sync_feature_access_controls(env, feature_ids=None):
    """Synchronize menu visibility and dedicated-model ACLs from feature policy.

    Menus are gated at the Odoo navigation layer. Features with dedicated models
    (automation, run logs, webhook monitor) also move their ACL between the base
    WATI user role and the WATI administrator role, so a hidden admin-only feature
    cannot be opened by guessing its URL/action id.

    Conversation/message history share the operational inbox models, so their
    feature policy controls the history screens without revoking the underlying
    inbox data access that agents need to do their job.
    """

    registry = FEATURE_ACCESS_REGISTRY
    wanted = set(feature_ids or registry.keys())
    user_group = env.ref("wati_connector.group_wati_user")
    admin_group = env.ref("wati_connector.group_wati_admin")
    system_group = env.ref("base.group_system")

    result = {}
    for feature_id, definition in registry.items():
        if feature_id not in wanted:
            continue

        mode = get_feature_mode(env, feature_id)
        target_group = user_group if mode == ACCESS_ALL else admin_group

        menu_group_ids = [target_group.id, system_group.id]
        for xmlid in definition.get("menu_xmlids", []):
            menu = env.ref(xmlid, raise_if_not_found=False)
            if menu:
                menu.sudo().write({"groups_id": [(6, 0, menu_group_ids)]})

        for xmlid in definition.get("acl_xmlids", []):
            access = env.ref(xmlid, raise_if_not_found=False)
            if access:
                access.sudo().write({"group_id": target_group.id})

        result[feature_id] = mode

    env.registry.clear_cache()
    return result
