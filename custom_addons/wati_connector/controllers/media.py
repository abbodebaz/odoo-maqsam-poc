from odoo import http
from odoo.http import request

from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.media import WatiMediaNotFound, WatiMediaService, WatiMediaTooLarge


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
            descriptor = WatiMediaService.describe(message)
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

        try:
            result = WatiMediaService(request.env).fetch(message)
        except WatiConfigurationError:
            return request.make_response("WATI API is not configured", status=503)
        except WatiMediaNotFound:
            return request.make_response("WATI media not available", status=404)
        except WatiMediaTooLarge:
            return request.make_response("WATI media is too large or unavailable", status=413)
        except WatiRequestError:
            return request.make_response("Unable to fetch WATI media", status=502)

        return request.make_response(
            result["content"],
            headers=[
                ("Content-Type", result["content_type"]),
                ("Content-Disposition", f'inline; filename="{result["filename"]}"'),
                ("X-Content-Type-Options", "nosniff"),
                ("Cache-Control", "private, max-age=300"),
            ],
            status=200,
        )
