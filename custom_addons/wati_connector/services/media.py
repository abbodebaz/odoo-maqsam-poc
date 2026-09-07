import json
import os
from urllib.parse import urljoin, urlparse

import requests

from .config import WatiConfig
from .exceptions import WatiConfigurationError, WatiRequestError


_MEDIA_TYPES = {"image", "video", "audio", "voice", "document", "sticker"}
_MAX_REDIRECTS = 3
_MAX_MEDIA_BYTES = 110 * 1024 * 1024


class WatiMediaNotFound(Exception):
    """Raised when WATI has no retrievable media for a message."""


class WatiMediaTooLarge(Exception):
    """Raised when a WATI media response exceeds the configured safety limit."""


class WatiMediaService:
    """Secure inbound-media retrieval and webhook media metadata parsing."""

    def __init__(self, env):
        self.env = env
        self.config = WatiConfig(env)

    @staticmethod
    def _payload(message):
        try:
            value = json.loads(message.raw_payload or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _first(mapping, keys):
        if not isinstance(mapping, dict):
            return ""
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @classmethod
    def describe(cls, message):
        payload = cls._payload(message)
        data = payload.get("data")
        if isinstance(data, str):
            data_map = {"url": data}
        elif isinstance(data, dict):
            data_map = data
        else:
            data_map = {}

        message_type = str(message.message_type or payload.get("type") or "").strip().lower()
        source_url = cls._first(payload, ("sourceUrl", "mediaUrl", "url", "link")) or cls._first(
            data_map,
            ("sourceUrl", "mediaUrl", "url", "link", "downloadUrl"),
        )
        file_name = cls._first(data_map, ("fileName", "filename", "name", "file_name"))
        media_path = cls._first(data_map, ("path", "filePath", "file", "mediaPath"))

        if not file_name:
            candidate = source_url or media_path
            if candidate:
                try:
                    file_name = os.path.basename(urlparse(candidate).path) or ""
                except Exception:
                    file_name = ""

        payload_record_id = cls._first(payload, ("id", "messageId", "message_id"))
        whatsapp_message_id = str(message.whatsapp_message_id or "").strip()
        local_message_id = str(getattr(message, "local_message_id", "") or "").strip()
        legacy_name = str(message.name or "").strip()
        message_refs = []
        for value in (payload_record_id, whatsapp_message_id, local_message_id, legacy_name):
            if value and value not in message_refs:
                message_refs.append(value)

        has_media = message_type in _MEDIA_TYPES and bool(source_url or media_path or file_name or message_refs)
        return {
            "type": message_type,
            "source_url": source_url,
            "media_path": media_path,
            "file_name": file_name,
            "message_refs": message_refs,
            "has_media": has_media,
        }

    @staticmethod
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

    def _safe_get(self, url, headers, endpoint, *, params=None, timeout=30):
        current_url = url
        current_params = params
        for _index in range(_MAX_REDIRECTS + 1):
            if not self._allowed_source_url(current_url, endpoint):
                return None
            try:
                response = requests.get(
                    current_url,
                    headers=headers,
                    params=current_params,
                    timeout=timeout,
                    allow_redirects=False,
                    stream=True,
                )
            except requests.RequestException as exc:
                raise WatiRequestError(f"Unable to fetch WATI media: {exc}") from exc
            current_params = None
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = response.headers.get("Location") or ""
            response.close()
            if not location:
                return None
            current_url = urljoin(current_url, location)
        return None

    @staticmethod
    def _response_bytes(response):
        try:
            declared = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            declared = 0
        if declared and declared > _MAX_MEDIA_BYTES:
            response.close()
            raise WatiMediaTooLarge()

        chunks = []
        size = 0
        try:
            for chunk in response.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > _MAX_MEDIA_BYTES:
                    raise WatiMediaTooLarge()
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()

    def fetch(self, message):
        descriptor = self.describe(message)
        if not descriptor["has_media"]:
            raise WatiMediaNotFound()

        endpoint, _token = self.config.require_api()
        headers = self.config.authorization_headers()
        headers["Accept"] = "*/*"

        response = None
        for message_ref in descriptor["message_refs"]:
            response = self._safe_get(
                f"{endpoint}/api/ext/v3/conversations/messages/file/{message_ref}",
                headers,
                endpoint,
            )
            if response is not None and response.ok:
                break
            if response is not None:
                response.close()
                response = None

        media_ref = descriptor["media_path"] or descriptor["file_name"]
        if response is None and media_ref:
            response = self._safe_get(
                f"{endpoint}/api/v1/getMedia",
                headers,
                endpoint,
                params={"fileName": media_ref},
            )
            if response is not None and not response.ok:
                response.close()
                response = None

        source_url = descriptor["source_url"]
        if response is None and source_url:
            response = self._safe_get(source_url, headers, endpoint)
            if response is not None and not response.ok:
                response.close()
                response = None

        if response is None:
            raise WatiMediaNotFound()

        content_type = (response.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].strip()
        content = self._response_bytes(response)
        filename = descriptor["file_name"] or f"wati-{message.id}"
        safe_filename = filename.replace('"', "").replace("\r", "").replace("\n", "")
        return {
            "content": content,
            "content_type": content_type,
            "filename": safe_filename,
            "descriptor": descriptor,
        }
