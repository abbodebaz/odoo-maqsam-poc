import json
import re


STATUS_BY_CODE = {
    0: "draft",
    1: "pending",
    2: "approved",
    3: "rejected",
    4: "deleted",
    5: "pending_internal",
    6: "disabled",
    7: "paused",
}

QUALITY_BY_CODE = {
    0: "unknown",
    1: "green",
    2: "red",
    3: "yellow",
}

KNOWN_STATUSES = {
    "draft",
    "pending",
    "approved",
    "rejected",
    "deleted",
    "pending_internal",
    "disabled",
    "paused",
    "unknown",
}

KNOWN_QUALITIES = {"unknown", "green", "yellow", "red"}


def clean(value):
    if value in (None, False):
        return ""
    return str(value).strip()


def first(mapping, keys):
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return ""


def find_template_list(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in (
        "messageTemplates",
        "templates",
        "items",
        "results",
        "result",
        "data",
        "records",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = find_template_list(value)
            if nested:
                return nested
    for value in payload.values():
        if isinstance(value, (dict, list)):
            nested = find_template_list(value)
            if nested:
                return nested
    return []


def extract_placeholders(body):
    result = []
    for token in re.findall(r"{{\s*([^{}]+?)\s*}}", clean(body)):
        token = token.strip()
        if token and token not in result:
            result.append(token)
    return result


def placeholder_mode(tokens):
    tokens = list(tokens or [])
    if not tokens:
        return "none"
    numeric = [token.isdigit() for token in tokens]
    if all(numeric):
        return "positional"
    if not any(numeric):
        return "named"
    return "mixed"


def normalize_status(value):
    if isinstance(value, bool):
        return "unknown"
    if isinstance(value, int):
        return STATUS_BY_CODE.get(value, "unknown")
    raw = clean(value).casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "pendinginternal": "pending_internal",
        "pending_internal": "pending_internal",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in KNOWN_STATUSES else "unknown"


def normalize_quality(value):
    if isinstance(value, bool):
        return "unknown"
    if isinstance(value, int):
        return QUALITY_BY_CODE.get(value, "unknown")
    raw = clean(value).casefold().replace("-", "_").replace(" ", "_")
    return raw if raw in KNOWN_QUALITIES else "unknown"


def template_name(item):
    return first(item, ("elementName", "templateName", "template_name", "name"))


def template_language(item):
    if not isinstance(item, dict):
        return ""
    raw = item.get("language")
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        return first(raw, ("code", "languageCode", "locale", "name"))
    return first(item, ("languageCode", "locale"))


def _component(item, component_type):
    components = item.get("components") if isinstance(item, dict) else None
    if not isinstance(components, list):
        return {}
    target = clean(component_type).upper()
    for component in components:
        if (
            isinstance(component, dict)
            and clean(component.get("type")).upper() == target
        ):
            return component
    return {}


def template_body(item):
    if not isinstance(item, dict):
        return ""
    raw = item.get("body")
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        value = first(raw, ("text", "body", "content"))
        if value:
            return value
    component = _component(item, "BODY")
    return first(component, ("text", "body", "content"))


def template_header(item):
    if not isinstance(item, dict):
        return {"type": "", "text": ""}
    raw = item.get("header")
    if isinstance(raw, str):
        return {"type": "TEXT", "text": raw.strip()}
    if isinstance(raw, dict):
        return {
            "type": first(raw, ("type", "format", "headerType")).upper(),
            "text": first(raw, ("text", "content", "body")),
        }
    component = _component(item, "HEADER")
    return {
        "type": first(component, ("format", "type", "headerType")).upper(),
        "text": first(component, ("text", "content", "body")),
    }


def template_footer(item):
    if not isinstance(item, dict):
        return ""
    raw = item.get("footer")
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        value = first(raw, ("text", "content", "body"))
        if value:
            return value
    component = _component(item, "FOOTER")
    return first(component, ("text", "content", "body"))


def template_buttons(item):
    if not isinstance(item, dict):
        return []
    raw = item.get("buttons")
    if isinstance(raw, list):
        return raw
    component = _component(item, "BUTTONS")
    raw = component.get("buttons") if isinstance(component, dict) else None
    return raw if isinstance(raw, list) else []


def custom_param_names(item, body=""):
    result = []
    raw = item.get("customParams") if isinstance(item, dict) else None
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                name = first(entry, ("name", "paramName", "key", "field"))
            elif isinstance(entry, str):
                name = entry.strip()
            else:
                name = ""
            if name and name not in result:
                result.append(name)
    if result:
        return result
    return extract_placeholders(body)


def normalize_template(item):
    if not isinstance(item, dict):
        return None
    name = template_name(item)
    if not name:
        return None

    body = template_body(item)
    header = template_header(item)
    buttons = template_buttons(item)

    raw_status = (
        item.get("status")
        if "status" in item
        else item.get("approvalStatus", item.get("templateStatus"))
    )
    raw_quality = (
        item.get("quality")
        if "quality" in item
        else item.get("qualityScore", item.get("templateQuality"))
    )

    category = first(item, ("category", "templateCategory")).upper()
    sub_category = first(item, ("subCategory", "subcategory", "templateSubCategory")).upper()

    return {
        "name": name,
        "language": template_language(item) or "en",
        "category": category,
        "sub_category": sub_category or "STANDARD",
        "status": normalize_status(raw_status),
        "quality": normalize_quality(raw_quality),
        "body": body,
        "footer": template_footer(item),
        "header_type": header["type"],
        "header_text": header["text"],
        "buttons": buttons,
        "buttons_json": json.dumps(buttons, ensure_ascii=False, default=str),
        "custom_params": custom_param_names(item, body),
        "wati_template_id": first(
            item, ("watiTemplateId", "wati_template_id", "_id", "id")
        ),
        "meta_template_id": first(
            item, ("templateId", "metaTemplateId", "meta_template_id")
        ),
        "waba_id": first(item, ("wabaId", "waba_id", "whatsappBusinessAccountId")),
        "channel_phone_number": first(
            item,
            (
                "channelPhoneNumber",
                "channel_number",
                "channelNumber",
                "phoneNumber",
            ),
        ),
        "raw": item,
    }
