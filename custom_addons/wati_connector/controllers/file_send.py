import os

from odoo import http
from odoo.http import request

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.idempotency import WatiIdempotency


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


def _safe_filename(value):
    name = (
        os.path.basename(value or "")
        .replace('"', "")
        .replace("\r", "")
        .replace("\n", "")
        .replace("\x00", "")
        .strip()
    )
    return name[:180] or "attachment"


class WatiFileSendController(http.Controller):

    @http.route("/wati/inbox/send-file", type="http", auth="user", methods=["POST"])
    def send_file(self, conversation_id=None, caption=None, request_id=None, **kwargs):
        try:
            conversation_id = int(conversation_id or 0)
        except (TypeError, ValueError):
            conversation_id = 0

        conversation = request.env["wati.conversation"].browse(conversation_id).exists()
        if not conversation:
            return request.make_json_response(
                {"ok": False, "message": "المحادثة غير موجودة."}, status=404
            )

        current_user = request.env.user
        if not conversation.assigned_user_id:
            return request.make_json_response(
                {"ok": False, "message": "استلم المحادثة أولًا قبل إرسال مرفق."},
                status=409,
            )
        if conversation.assigned_user_id != current_user:
            return request.make_json_response(
                {
                    "ok": False,
                    "message": (
                        f"المحادثة مستلمة بواسطة {conversation.assigned_user_id.name}. "
                        "انقل المحادثة إليك أولًا."
                    ),
                },
                status=409,
            )
        if not conversation.wa_id:
            return request.make_json_response(
                {"ok": False, "message": "لا يوجد رقم WhatsApp لهذه المحادثة."},
                status=400,
            )

        upload = request.httprequest.files.get("file")
        if not upload or not upload.filename:
            return request.make_json_response(
                {"ok": False, "message": "اختر ملفًا أولًا."}, status=400
            )

        filename = _safe_filename(upload.filename)
        mimetype = (upload.mimetype or "application/octet-stream").split(";", 1)[0].strip().lower()
        category = _file_category(filename, mimetype)
        if not category:
            return request.make_json_response(
                {
                    "ok": False,
                    "message": (
                        "نوع الملف غير مدعوم في WhatsApp. استخدم صورة JPG/PNG، "
                        "فيديو MP4/3GP، صوت مدعوم، أو مستند PDF/Office/TXT."
                    ),
                },
                status=400,
            )

        size = _stream_size(upload)
        if size == 0:
            return request.make_json_response(
                {"ok": False, "message": "الملف فارغ ولا يمكن إرساله."}, status=400
            )
        limit = _LIMITS[category]
        if size > limit:
            return request.make_json_response(
                {
                    "ok": False,
                    "message": (
                        "حجم الملف أكبر من الحد المسموح لهذا النوع "
                        f"({limit // (1024 * 1024)} MB)."
                    ),
                },
                status=400,
            )

        caption = (caption or "").strip()
        if len(caption) > 1024:
            return request.make_json_response(
                {"ok": False, "message": "تعليق المرفق يجب ألا يتجاوز 1024 حرفًا."},
                status=400,
            )

        idem = WatiIdempotency(request.env)
        scope = f"outbound:file:user:{current_user.id}"
        key = (request_id or "").strip() or idem.digest(
            conversation.id, filename, size, caption
        )
        if not idem.acquire(scope, key, ttl_seconds=120):
            return request.make_json_response(
                {
                    "ok": True,
                    "message": "تم تجاهل إعادة إرسال مكررة.",
                    "duplicate_suppressed": True,
                },
                status=200,
            )

        try:
            upload.stream.seek(0)
            WatiClient(request.env).send_session_file(
                conversation.wa_id,
                filename=filename,
                stream=upload.stream,
                mimetype=mimetype,
                caption=caption,
            )
        except WatiConfigurationError:
            idem.release(scope, key)
            return request.make_json_response(
                {"ok": False, "message": "إعدادات WATI API غير مكتملة."}, status=503
            )
        except WatiRequestError as exc:
            idem.release(scope, key)
            detail = (exc.response_text or str(exc) or "").strip()[:600]
            status = exc.status_code or 502
            return request.make_json_response(
                {"ok": False, "message": f"WATI رفض قبول المرفق ({status}): {detail}"},
                status=status,
            )

        return request.make_json_response(
            {
                "ok": True,
                "message": "تم قبول المرفق في WATI ✅",
                "filename": filename,
                "category": category,
                "accepted": True,
            },
            status=200,
        )
