import json
import os
from urllib.parse import urlparse

import requests

from odoo import http
from odoo.http import request


_MEDIA_TYPES = {"image", "video", "audio", "voice", "document", "sticker"}


def _payload(message):
    try:
        value = json.loads(message.raw_payload or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _first(mapping, keys):
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _media_descriptor(message):
    payload = _payload(message)
    data = payload.get("data")
    if isinstance(data, str):
        data_map = {"url": data}
    elif isinstance(data, dict):
        data_map = data
    else:
        data_map = {}

    message_type = str(message.message_type or payload.get("type") or "").strip().lower()
    source_url = _first(payload, ("sourceUrl", "mediaUrl", "url", "link")) or _first(
        data_map,
        ("sourceUrl", "mediaUrl", "url", "link", "downloadUrl"),
    )
    file_name = _first(data_map, ("fileName", "filename", "name", "file_name"))
    media_path = _first(data_map, ("path", "filePath", "file", "mediaPath"))

    if not file_name:
        candidate = source_url or media_path
        if candidate:
            try:
                file_name = os.path.basename(urlparse(candidate).path) or ""
            except Exception:
                file_name = ""

    has_media = message_type in _MEDIA_TYPES and bool(source_url or media_path or file_name)
    return {
        "type": message_type,
        "source_url": source_url,
        "media_path": media_path,
        "file_name": file_name,
        "has_media": has_media,
    }


def _wati_config():
    params = request.env["ir.config_parameter"].sudo()
    endpoint = (params.get_param("wati_connector.api_endpoint") or "").strip().rstrip("/")
    token = (params.get_param("wati_connector.api_token") or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return endpoint, token


def _allowed_source_url(url, endpoint):
    try:
        parsed = urlparse(url)
        endpoint_parsed = urlparse(endpoint)
    except Exception:
        return False
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        return False
    endpoint_host = (endpoint_parsed.hostname or "").lower()
    host = (parsed.hostname or "").lower()
    return bool(endpoint_host and (host == endpoint_host or host.endswith(".wati.io")))


class WatiMediaController(http.Controller):

    @http.route(
        "/wati/inbox/media-meta",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def media_meta(self, conversation_id=None, **kwargs):
        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0

        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return request.make_json_response({"ok": False, "message": "المحادثة غير موجودة."}, status=404)

        latest = request.env["wati.message"].search(
            [("conversation_id", "=", conversation.id)],
            order="received_at desc, id desc",
            limit=250,
        )
        messages = latest.sorted(key=lambda item: (item.received_at, item.id))
        rows = []
        for message in messages:
            descriptor = _media_descriptor(message)
            rows.append(
                {
                    "id": message.id,
                    "type": descriptor["type"],
                    "has_media": descriptor["has_media"],
                    "file_name": descriptor["file_name"],
                    "media_url": f"/wati/inbox/media/{message.id}" if descriptor["has_media"] else "",
                }
            )
        return request.make_json_response({"ok": True, "messages": rows}, status=200)

    @http.route(
        "/wati/inbox/media/<int:message_id>",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def media(self, message_id, **kwargs):
        message = request.env["wati.message"].browse(message_id).exists()
        if not message:
            return request.not_found()

        descriptor = _media_descriptor(message)
        if not descriptor["has_media"]:
            return request.not_found()

        endpoint, token = _wati_config()
        if not endpoint or not token:
            return request.make_response("WATI API is not configured", status=503)

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "*/*",
        }

        response = None
        source_url = descriptor["source_url"]
        media_ref = descriptor["media_path"] or descriptor["file_name"]
        try:
            if source_url and _allowed_source_url(source_url, endpoint):
                response = requests.get(source_url, headers=headers, timeout=20)
            if (response is None or not response.ok) and media_ref:
                response = requests.get(
                    f"{endpoint}/api/v1/getMedia",
                    headers=headers,
                    params={"fileName": media_ref},
                    timeout=20,
                )
        except requests.RequestException:
            return request.make_response("Unable to fetch WATI media", status=502)

        if response is None or not response.ok:
            return request.make_response("WATI media not available", status=404)

        content_type = response.headers.get("Content-Type") or "application/octet-stream"
        filename = descriptor["file_name"] or f"wati-{message.id}"
        safe_filename = filename.replace('"', "")
        return request.make_response(
            response.content,
            headers=[
                ("Content-Type", content_type),
                ("Content-Disposition", f'inline; filename="{safe_filename}"'),
                ("Cache-Control", "private, max-age=300"),
            ],
            status=200,
        )
