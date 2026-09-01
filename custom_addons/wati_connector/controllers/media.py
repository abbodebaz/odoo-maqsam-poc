import json
import os
from urllib.parse import urljoin, urlparse

import requests

from odoo import http
from odoo.http import request


_MEDIA_TYPES = {"image", "video", "audio", "voice", "document", "sticker"}
_MAX_REDIRECTS = 3
_MAX_MEDIA_BYTES = 110 * 1024 * 1024


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

    # WATI can omit sourceUrl/fileName in webhook callbacks while the media is
    # still available through the official get-file-by-message-id endpoint.
    payload_record_id = _first(payload, ("id", "messageId", "message_id"))
    whatsapp_message_id = str(message.whatsapp_message_id or "").strip()
    local_message_id = str(getattr(message, "local_message_id", "") or "").strip()
    legacy_name = str(message.name or "").strip()
    message_refs = []
    for value in (payload_record_id, whatsapp_message_id, local_message_id, legacy_name):
        if value and value not in message_refs:
            message_refs.append(value)

    has_media = message_type in _MEDIA_TYPES and bool(
        source_url or media_path or file_name or message_refs
    )
    return {
        "type": message_type,
        "source_url": source_url,
        "media_path": media_path,
        "file_name": file_name,
        "message_refs": message_refs,
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
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    endpoint_host = (endpoint_parsed.hostname or "").lower()
    host = (parsed.hostname or "").lower()
    return bool(endpoint_host and (host == endpoint_host or host.endswith(".wati.io")))


def _safe_get(url, headers, endpoint, *, params=None, timeout=30):
    current_url = url
    current_params = params
    for _index in range(_MAX_REDIRECTS + 1):
        if not _allowed_source_url(current_url, endpoint):
            return None
        response = requests.get(
            current_url,
            headers=headers,
            params=current_params,
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        )
        current_params = None
        if response.status_code not in (301, 302, 303, 307, 308):
            return response
        location = response.headers.get("Location") or ""
        response.close()
        if not location:
            return None
        current_url = urljoin(current_url, location)
    return None


def _response_bytes(response):
    if response is None:
        return None
    try:
        declared = int(response.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared and declared > _MAX_MEDIA_BYTES:
        response.close()
        return None

    chunks = []
    size = 0
    try:
        for chunk in response.iter_content(chunk_size=256 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > _MAX_MEDIA_BYTES:
                response.close()
                return None
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        response.close()


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
        try:
            # Preferred modern path: WATI can retrieve a media stream by message id
            # even when the webhook did not include a source URL or file path.
            for message_ref in descriptor["message_refs"]:
                response = _safe_get(
                    f"{endpoint}/api/ext/v3/conversations/messages/file/{message_ref}",
                    headers,
                    endpoint,
                )
                if response is not None and response.ok:
                    break
                if response is not None:
                    response.close()
                    response = None

            # Backward-compatible V1 path for older WATI tenants/webhook payloads.
            media_ref = descriptor["media_path"] or descriptor["file_name"]
            if response is None and media_ref:
                response = _safe_get(
                    f"{endpoint}/api/v1/getMedia",
                    headers,
                    endpoint,
                    params={"fileName": media_ref},
                )
                if response is not None and not response.ok:
                    response.close()
                    response = None

            # Last resort for signed WATI-hosted URLs. Redirects are followed only
            # while every hop remains on the configured WATI host / *.wati.io.
            source_url = descriptor["source_url"]
            if response is None and source_url:
                response = _safe_get(source_url, headers, endpoint)
                if response is not None and not response.ok:
                    response.close()
                    response = None
        except requests.RequestException:
            if response is not None:
                response.close()
            return request.make_response("Unable to fetch WATI media", status=502)

        if response is None:
            return request.make_response("WATI media not available", status=404)

        content_type = (response.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].strip()
        content = _response_bytes(response)
        if content is None:
            return request.make_response("WATI media is too large or unavailable", status=413)

        filename = descriptor["file_name"] or f"wati-{message.id}"
        safe_filename = filename.replace('"', "").replace("\r", "").replace("\n", "")
        return request.make_response(
            content,
            headers=[
                ("Content-Type", content_type),
                ("Content-Disposition", f'inline; filename="{safe_filename}"'),
                ("X-Content-Type-Options", "nosniff"),
                ("Cache-Control", "private, max-age=300"),
            ],
            status=200,
        )
