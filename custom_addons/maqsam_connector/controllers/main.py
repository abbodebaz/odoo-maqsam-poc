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

    @staticmethod
    def _can_use_dialer(agent):
        return (
            agent.get("active") is not False
            and (
                agent.get("incomingEnabled") is True
                or agent.get("outgoingEnabled") is True
            )
        )

    @staticmethod
    def _agent_label(agent):
        name = str(agent.get("name") or "").strip() or "بدون اسم"
        email = str(agent.get("email") or "").strip() or "بدون إيميل"
        incoming = "نعم" if agent.get("incomingEnabled") is True else "لا"
        outgoing = "نعم" if agent.get("outgoingEnabled") is True else "لا"
        state = str(agent.get("state") or "غير معروف")
        return f"{name} <{email}> — استقبال: {incoming}، صادر: {outgoing}، الحالة: {state}"

    def _resolve_agent(self, cfg):
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
            if not self._can_use_dialer(match):
                raise ValueError(
                    "المستخدم المحدد موجود في Maqsam لكنه لا يملك صلاحية Dialer. "
                    f"المستخدم الحالي: {self._agent_label(match)}. "
                    "اختر Agent لديه Incoming أو Outgoing enabled، وليس حساب Admin فقط."
                )
            return match

        dialer_agents = [agent for agent in agents if self._can_use_dialer(agent) and agent.get("email")]
        if len(dialer_agents) == 1:
            return dialer_agents[0]

        if not dialer_agents:
            raise ValueError(
                "لم أجد أي Agent نشط لديه صلاحية Incoming أو Outgoing في Maqsam. "
                "فعّل صلاحيات الاتصال للموظف في Maqsam أولاً."
            )

        preview = " | ".join(self._agent_label(agent) for agent in dialer_agents[:8])
        raise ValueError(
            "يوجد أكثر من Agent لديه صلاحية Dialer. حدد Default Maqsam Agent Email من Settings → Maqsam. "
            f"المتاحون: {preview}"
        )

    def _error_page(self, exc):
        message = html.escape(str(exc))
        return request.make_response(
            "<html dir='rtl'><body style='font-family:Arial,sans-serif;padding:32px;background:#f7f7f8'>"
            "<div style='max-width:900px;margin:auto;background:#fff;padding:28px;border-radius:14px'>"
            "<h2 style='margin-top:0'>تعذر فتح Maqsam Dialer</h2>"
            f"<p style='font-size:16px'>{message}</p>"
            "</div></body></html>",
            headers=[("Content-Type", "text/html; charset=utf-8")],
            status=500,
        )

    @http.route("/maqsam/dialer", type="http", auth="user", methods=["GET"], csrf=False)
    def dialer_status(self, **kwargs):
        try:
            cfg = self._config()
            agent = self._resolve_agent(cfg)
            name = html.escape(str(agent.get("name") or "بدون اسم"))
            email = html.escape(str(agent.get("email") or ""))
            state = html.escape(str(agent.get("state") or "غير معروف"))
            incoming = "مفعّل ✅" if agent.get("incomingEnabled") is True else "غير مفعّل ❌"
            outgoing = "مفعّل ✅" if agent.get("outgoingEnabled") is True else "غير مفعّل ❌"
            base_url = html.escape(cfg["base_url"])

            page = f"""
            <html dir='rtl'>
            <head><meta charset='utf-8'><title>Maqsam Diagnostic</title></head>
            <body style='font-family:Arial,sans-serif;background:#f6f7f9;margin:0;padding:32px'>
              <div style='max-width:820px;margin:auto;background:white;border:1px solid #e5e7eb;border-radius:16px;padding:28px'>
                <h2 style='margin-top:0'>تم الاتصال بـ Maqsam بنجاح ✅</h2>
                <p>هذه هي هوية الـAgent التي سيستخدمها Odoo قبل فتح الـDialer:</p>
                <div style='background:#f8fafc;border-radius:12px;padding:18px;line-height:2'>
                  <b>الاسم:</b> {name}<br>
                  <b>الإيميل:</b> {email}<br>
                  <b>الحالة:</b> {state}<br>
                  <b>استقبال:</b> {incoming}<br>
                  <b>صادر:</b> {outgoing}<br>
                  <b>Base URL:</b> {base_url}
                </div>
                <p style='margin-top:20px'>إذا هذا هو نفس الموظف الذي اشتغل معك في برنامج RTC اضغط الزر:</p>
                <a href='/maqsam/dialer/go' style='display:inline-block;background:#714b67;color:white;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:bold'>فتح Maqsam Dialer</a>
              </div>
            </body>
            </html>
            """
            return request.make_response(
                page,
                headers=[("Content-Type", "text/html; charset=utf-8")],
                status=200,
            )
        except Exception as exc:
            return self._error_page(exc)

    @http.route("/maqsam/dialer/go", type="http", auth="user", methods=["GET"], csrf=False)
    def dialer_go(self, **kwargs):
        try:
            cfg = self._config()
            agent = self._resolve_agent(cfg)
            agent_email = str(agent.get("email") or "").strip().lower()

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
            return self._error_page(exc)
