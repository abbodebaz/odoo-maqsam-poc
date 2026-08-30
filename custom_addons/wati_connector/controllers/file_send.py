import os
import threading
import time
from urllib.parse import quote

import requests

from odoo import http
from odoo.http import request


_FILE_GUARD = {}
_FILE_GUARD_LOCK = threading.Lock()
_FILE_GUARD_TTL = 120.0

_IMAGE_TYPES = {"image/jpeg", "image/png"}
_VIDEO_TYPES = {"video/mp4", "video/3gpp", "video/3gp"}
_AUDIO_TYPES = {"audio/aac", "audio/mp4", "audio/mpeg", "audio/amr", "audio/ogg"}
_DOCUMENT_TYPES = {
    "text/plain",
    "application/pdf",
    "application/msword",
    "application/vnd.ms-powerpoint",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
_VIDEO_EXTENSIONS = {".mp4", ".3gp", ".3gpp"}
_AUDIO_EXTENSIONS = {".aac", ".m4a", ".mp3", ".amr", ".ogg", ".opus"}
_DOCUMENT_EXTENSIONS = {".txt", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}

_LIMITS = {
    "image": 5 * 1024 * 1024,
    "video": 16 * 1024 * 1024,
    "audio": 16 * 1024 * 1024,
    "document": 100 * 1024 * 1024,
}


def _reserve_guard(user_id, request_id):
    request_id = (request_id or "").strip()
    if not request_id:
        return "", True
    now = time.monotonic()
    key = f"{user_id}:{request_id}"
    with _FILE_GUARD_LOCK:
        expired = [item for item, created in _FILE_GUARD.items() if now - created > _FILE_GUARD_TTL]
        for item in expired:
            _FILE_GUARD.pop(item, None)
        if key in _FILE_GUARD:
            return key, False
        _FILE_GUARD[key] = now
    return key, True


def _release_guard(key):
    if not key:
        return
    with _FILE_GUARD_LOCK:
        _FILE_GUARD.pop(key, None)


def _wati_config():
    params = request.env["ir.config_parameter"].sudo()
    endpoint = (params.get_param("wati_connector.api_endpoint") or "").strip().rstrip("/")
    token = (params.get_param("wati_connector.api_token") or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return endpoint, token


def _file_category(filename, mimetype):
    mimetype = (mimetype or "").split(";", 1)[0].strip().lower()
    extension = os.path.splitext(filename or "")[1].lower()
    if mimetype in _IMAGE_TYPES or extension in _IMAGE_EXTENSIONS:
        return "image"
    if mimetype in _VIDEO_TYPES or extension in _VIDEO_EXTENSIONS:
        return "video"
    if mimetype in _AUDIO_TYPES or extension in _AUDIO_EXTENSIONS:
        return "audio"
    if mimetype in _DOCUMENT_TYPES or extension in _DOCUMENT_EXTENSIONS:
        return "document"
    return ""


def _stream_size(upload):
    stream = upload.stream
    try:
        position = stream.tell()
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(position)
        return size
    except (AttributeError, OSError):
        return int(upload.content_length or 0)


class WatiFileSendController(http.Controller):

    @http.route(
        "/wati/inbox/send-file",
        type="http",
        auth="user",
        methods=["POST"],
    )
    def send_file(self, conversation_id=None, caption=None, request_id=None, **kwargs):
        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0

        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return request.make_json_response({"ok": False, "message": "المحادثة غير موجودة."}, status=404)

        current_user = request.env.user
        if not conversation.assigned_user_id:
            return request.make_json_response(
                {"ok": False, "message": "استلم المحادثة أولًا قبل إرسال مرفق."},
                status=409,
            )
        if conversation.assigned_user_id != current_user and not current_user.has_group("base.group_system"):
            return request.make_json_response(
                {"ok": False, "message": f"المحادثة مستلمة بواسطة {conversation.assigned_user_id.name}. استخدم أخذ المحادثة أولًا."},
                status=409,
            )
        if not conversation.wa_id:
            return request.make_json_response({"ok": False, "message": "لا يوجد رقم WhatsApp لهذه المحادثة."}, status=400)

        upload = request.httprequest.files.get("file")
        if not upload or not upload.filename:
            return request.make_json_response({"ok": False, "message": "اختر ملفًا أولًا."}, status=400)

        filename = os.path.basename(upload.filename).replace('"', "").strip() or "attachment"
        mimetype = (upload.mimetype or "application/octet-stream").strip().lower()
        category = _file_category(filename, mimetype)
        if not category:
            return request.make_json_response(
                {"ok": False, "message": "نوع الملف غير مدعوم في WATI. استخدم صورة JPG/PNG، فيديو MP4/3GP، صوت مدعوم، أو مستند PDF/Office/TXT."},
                status=400,
            )

        size = _stream_size(upload)
        limit = _LIMITS[category]
        if size and size > limit:
            return request.make_json_response(
                {"ok": False, "message": f"حجم الملف أكبر من الحد المسموح لهذا النوع ({limit // (1024 * 1024)} MB)."},
                status=400,
            )

        caption = (caption or "").strip()
        if len(caption) > 1024:
            return request.make_json_response({"ok": False, "message": "تعليق المرفق يجب ألا يتجاوز 1024 حرفًا."}, status=400)

        endpoint, token = _wati_config()
        if not endpoint or not token:
            return request.make_json_response({"ok": False, "message": "إعدادات WATI API غير مكتملة."}, status=503)

        guard_key, reserved = _reserve_guard(current_user.id, request_id)
        if not reserved:
            return request.make_json_response(
                {"ok": True, "message": "تم تجاهل إعادة إرسال مكررة.", "duplicate_suppressed": True},
                status=200,
            )

        try:
            upload.stream.seek(0)
            response = requests.post(
                f"{endpoint}/api/v1/sendSessionFile/{quote(conversation.wa_id, safe='')}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                params={"caption": caption} if caption else None,
                files={"file": (filename, upload.stream, mimetype)},
                timeout=90,
            )
        except requests.RequestException as exc:
            _release_guard(guard_key)
            return request.make_json_response({"ok": False, "message": f"تعذر إرسال المرفق إلى WATI: {exc}"}, status=502)

        if not response.ok:
            _release_guard(guard_key)
            detail = (response.text or response.reason or "").strip()[:600]
            return request.make_json_response(
                {"ok": False, "message": f"WATI رفض إرسال المرفق ({response.status_code}): {detail}"},
                status=400,
            )

        # No database writes after the external API call. The WATI webhook is
        # the authoritative source for the sent file and delivery/read status.
        return request.make_json_response(
            {"ok": True, "message": "تم إرسال المرفق إلى WATI ✅", "filename": filename, "category": category},
            status=200,
        )
