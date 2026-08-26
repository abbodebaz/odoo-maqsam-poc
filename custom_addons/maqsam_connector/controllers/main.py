import base64
import re
from urllib.parse import urlencode

import requests
from odoo import http
from odoo.http import request


class MaqsamController(http.Controller):
    def _config(self):
        params = request.env["ir.config_parameter"].sudo()
        base_url = (params.get_param("maqsam_connector.base_url") or "").strip()
        access_key_id = (params.get_param("maqsam_connector.access_key_id") or "").strip()
        access_secret = (params.get_param("maqsam_connector.access_secret") or "").strip()

        base_url = re.sub(r"^https?://", "", base_url, flags=re.I)
        base_url = re.sub(r"^(api|portal)\.", "", base_url, flags=re.I).rstrip("/")
        if not re.fullmatch(r"[A-Za-z0-9.-]+", base_url or "") or ".." in base_url:
            raise ValueError("Maqsam Base URL غير صالح")
        if not access_key_id or not access_secret:
            raise ValueError("أكمل Access Key ID و Access Secret من إعدادات Maqsam")

        user = request.env.user
        agent_email = (user.maqsam_agent_email or user.email or user.login or "").strip().lower()
        if not agent_email:
            raise ValueError("لم يتم تحديد Maqsam Agent Email لهذا المستخدم")

        return {
            "base_url": base_url,
            "access_key_id": access_key_id,
            "access_secret": access_secret,
            "agent_email": agent_email,
        }

    @http.route("/maqsam/dialer", type="http", auth="user", methods=["GET"], csrf=False)
    def dialer(self, **kwargs):
        try:
            cfg = self._config()
            auth = base64.b64encode(
                f"{cfg['access_key_id']}:{cfg['access_secret']}".encode("utf-8")
            ).decode("ascii")
            response = requests.post(
                f"https://api.{cfg['base_url']}/v2/token",
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"UserEmail": cfg["agent_email"]},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            token = ((payload or {}).get("result") or {}).get("token")
            if not token:
                raise ValueError("Maqsam لم يرجع Autologin token")

            query = urlencode({
                "auth_token": token,
                "continue_path": "/phone/dialer",
            })
            return request.redirect(
                f"https://portal.{cfg['base_url']}/autologin?{query}",
                code=302,
            )
        except Exception as exc:
            message = str(exc).replace("<", "&lt;").replace(">", "&gt;")
            return request.make_response(
                f"<html dir='rtl'><body style='font-family:sans-serif;padding:24px'>"
                f"<h3>تعذر فتح Maqsam Dialer</h3><p>{message}</p></body></html>",
                headers=[("Content-Type", "text/html; charset=utf-8")],
                status=500,
            )
