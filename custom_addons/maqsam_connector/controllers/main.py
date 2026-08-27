import html
import re
from urllib.parse import urlencode

import requests
from requests.auth import HTTPBasicAuth
from odoo import http
from odoo.http import request


class MaqsamController(http.Controller):
    def _config(self):
        params = request.env["ir.config_parameter"].sudo()
        base_url = (params.get_param("maqsam_connector.base_url") or "").strip()
        access_key_id = (params.get_param("maqsam_connector.access_key_id") or "").strip()
        access_secret = (params.get_param("maqsam_connector.access_secret") or "").strip()
        default_agent_email = (
            params.get_param("maqsam_connector.default_agent_email") or ""
        ).strip().lower()

        base_url = re.sub(r"^https?://", "", base_url, flags=re.I)
        base_url = re.sub(r"^(api|portal)\.", "", base_url, flags=re.I).rstrip("/")
        if not re.fullmatch(r"[A-Za-z0-9.-]+", base_url or "") or ".." in base_url:
            raise ValueError("Maqsam Base URL غير صالح")
        if not access_key_id or not access_secret:
            raise ValueError("أكمل Access Key ID و Access Secret من إعدادات Maqsam")

        user = request.env.user
        user_agent_email = (user.maqsam_agent_email or "").strip().lower()
        odoo_email = (user.email or "").strip().lower()

        # Never send an Odoo login such as 'admin' to Maqsam as UserEmail.
        agent_email = user_agent_email or default_agent_email
        if not agent_email and "@" in odoo_email:
            agent_email = odoo_email

        return {
            "base_url": base_url,
            "access_key_id": access_key_id,
            "access_secret": access_secret,
            "agent_email": agent_email,
        }

    def _auth(self, cfg):
        return HTTPBasicAuth(cfg["access_key_id"], cfg["access_secret"])

    def _response_message(self, response):
        try:
            payload = response.json()
            if isinstance(payload, dict):
                value = payload.get("message") or payload.get("error") or payload
                return value if isinstance(value, str) else str(value)
            return str(payload)
        except Exception:
            text = (response.text or "").strip()
            return text or f"HTTP {response.status_code}"

    def _agents(self, cfg):
        response = requests.get(
            f"https://api.{cfg['base_url']}/v1/agents",
            auth=self._auth(cfg),
            timeout=15,
        )
        if not response.ok:
            raise ValueError(
                f"فشل التحقق من Agents في Maqsam ({response.status_code}): "
                f"{self._response_message(response)}"
            )
        payload = response.json() or {}
        return payload.get("message") if isinstance(payload.get("message"), list) else []

    def _resolve_agent_email(self, cfg):
        agents = self._agents(cfg)
        requested = (cfg.get("agent_email") or "").strip().lower()

        if requested:
            match = next(
                (
                    agent
                    for agent in agents
                    if str(agent.get("email") or "").strip().lower() == requested
                ),
                None,
            )
            if not match:
                raise ValueError(
                    f"تم الاتصال بـMaqsam بنجاح، لكن Agent Email ({requested}) غير موجود في الحساب. "
                    "ضع نفس Agent Email الذي استخدمته في برنامج RTC من Settings → Maqsam."
                )
            if match.get("active") is False:
                raise ValueError(f"Agent {requested} موجود لكنه غير نشط في Maqsam")
            return requested

        # Helpful POC fallback: if the account exposes exactly one active agent,
        # use it automatically. For multi-agent accounts require an explicit email.
        active_agents = [
            agent for agent in agents if agent.get("active") is not False and agent.get("email")
        ]
        if len(active_agents) == 1:
            return str(active_agents[0]["email"]).strip().lower()

        raise ValueError(
            "حدد Default Maqsam Agent Email من Settings → Maqsam، "
            "أو Maqsam Agent Email من إعدادات المستخدم."
        )

    @http.route("/maqsam/dialer", type="http", auth="user", methods=["GET"], csrf=False)
    def dialer(self, **kwargs):
        try:
            cfg = self._config()
            agent_email = self._resolve_agent_email(cfg)

            # Same request shape as the RTC Node POC that was proven to work.
            response = requests.post(
                f"https://api.{cfg['base_url']}/v2/token",
                auth=self._auth(cfg),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"UserEmail": agent_email},
                timeout=15,
            )
            if not response.ok:
                raise ValueError(
                    f"Maqsam رفض Autologin Token ({response.status_code}): "
                    f"{self._response_message(response)} — Agent: {agent_email}"
                )

            payload = response.json() or {}
            token = ((payload.get("result") or {}).get("token"))
            if not token:
                raise ValueError("Maqsam لم يرجع Autologin token")

            query = urlencode(
                {
                    "auth_token": token,
                    "continue_path": "/phone/dialer",
                }
            )
            return request.redirect(
                f"https://portal.{cfg['base_url']}/autologin?{query}",
                code=302,
            )
        except Exception as exc:
            message = html.escape(str(exc))
            return request.make_response(
                "<html dir='rtl'><body style='font-family:sans-serif;padding:24px'>"
                "<h3>تعذر فتح Maqsam Dialer</h3>"
                f"<p>{message}</p>"
                "</body></html>",
                headers=[("Content-Type", "text/html; charset=utf-8")],
                status=500,
            )
