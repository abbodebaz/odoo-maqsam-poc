import re

import requests
from odoo import http
from odoo.http import request

from .main import MaqsamController


class MaqsamApiController(MaqsamController):
    def _json(self, payload, status=200):
        response = request.make_json_response(payload, status=status)
        response.headers["Cache-Control"] = "no-store, private, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response

    def _safe_identifier(self, value):
        value = str(value or "").strip()
        if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("المعرّف غير صالح")
        return value

    def _maqsam_json(self, response):
        if not response.ok:
            raise ValueError(
                f"Maqsam API ({response.status_code}): {self._response_message(response)}"
            )
        try:
            return response.json() or {}
        except Exception as exc:
            raise ValueError("استجابة Maqsam ليست JSON صالح") from exc

    @http.route(
        "/maqsam/api/agents",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def agents_index(self, **kwargs):
        try:
            cfg = self._config()
            page = max(int(kwargs.get("page") or 1), 1)
            path = "/v1/agents" if page == 1 else f"/v1/agents/page/{page}"
            response = requests.get(
                f"https://api.{cfg['base_url']}{path}",
                auth=self._auth(cfg),
                timeout=20,
            )
            payload = self._maqsam_json(response)
            agents = payload.get("message") if isinstance(payload.get("message"), list) else []
            return self._json({"ok": True, "page": page, "agents": agents})
        except Exception as exc:
            return self._json({"ok": False, "message": str(exc)}, status=500)

    @http.route(
        "/maqsam/api/calls",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def calls_index(self, **kwargs):
        try:
            cfg = self._config()
            params = {}
            for key in ("phone", "email", "start_time", "end_time"):
                value = str(kwargs.get(key) or "").strip()
                if value:
                    params[key] = value

            page = max(int(kwargs.get("page") or 1), 1)
            params["page"] = page

            if str(kwargs.get("mine") or "").lower() in ("1", "true", "yes"):
                agent = self._resolve_agent(cfg)
                params["email"] = str(agent.get("email") or "").strip().lower()

            response = requests.get(
                f"https://api.{cfg['base_url']}/v3/calls",
                auth=self._auth(cfg),
                params=params,
                timeout=25,
            )
            payload = self._maqsam_json(response)
            calls = payload.get("message") if isinstance(payload.get("message"), list) else []
            return self._json({"ok": True, "page": page, "calls": calls})
        except Exception as exc:
            return self._json({"ok": False, "message": str(exc)}, status=500)

    @http.route(
        "/maqsam/api/calls/<string:lookup>/<string:value>",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def call_show(self, lookup, value, **kwargs):
        try:
            if lookup not in ("id", "reference_id"):
                raise ValueError("نوع البحث يجب أن يكون id أو reference_id")
            value = self._safe_identifier(value)
            cfg = self._config()
            response = requests.get(
                f"https://api.{cfg['base_url']}/v3/calls/{lookup}/{value}",
                auth=self._auth(cfg),
                timeout=25,
            )
            payload = self._maqsam_json(response)
            return self._json({"ok": True, "call": payload.get("message") or {}})
        except Exception as exc:
            return self._json({"ok": False, "message": str(exc)}, status=500)

    @http.route(
        "/maqsam/api/calls",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def call_create(self, **kwargs):
        try:
            cfg = self._config()
            body = request.httprequest.get_json(silent=True) or {}
            phone = re.sub(r"\D", "", str(body.get("phone") or ""))

            params = request.env["ir.config_parameter"].sudo()
            default_caller = params.get_param("maqsam_connector.default_caller") or ""
            caller = re.sub(
                r"\D",
                "",
                str(body.get("caller") or default_caller or ""),
            )

            if not re.fullmatch(r"\d{8,15}", phone):
                raise ValueError("أدخل الرقم بالصيغة الدولية، مثال 9665XXXXXXXX")

            agent = self._resolve_agent(cfg)
            agent_email = str(agent.get("email") or "").strip().lower()
            form = {"email": agent_email, "phone": phone}
            if caller:
                form["caller"] = caller

            response = requests.post(
                f"https://api.{cfg['base_url']}/v3/calls",
                auth=self._auth(cfg),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=form,
                timeout=25,
            )
            payload = self._maqsam_json(response)
            return self._json({"ok": True, "result": payload})
        except Exception as exc:
            return self._json({"ok": False, "message": str(exc)}, status=500)

    @http.route(
        "/maqsam/api/recordings/<string:lookup>/<string:value>",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def recording(self, lookup, value, **kwargs):
        try:
            if lookup not in ("id", "reference_id"):
                raise ValueError("نوع البحث يجب أن يكون id أو reference_id")
            value = self._safe_identifier(value)
            cfg = self._config()
            response = requests.get(
                f"https://api.{cfg['base_url']}/v3/recording/{lookup}/{value}",
                auth=self._auth(cfg),
                timeout=45,
            )
            if not response.ok:
                return self._json(
                    {
                        "ok": False,
                        "message": (
                            "التسجيل غير متوفر بعد" if response.status_code == 404
                            else self._response_message(response)
                        ),
                    },
                    status=response.status_code,
                )

            return request.make_response(
                response.content,
                headers=[
                    ("Content-Type", "audio/mpeg"),
                    ("Content-Disposition", f'inline; filename="maqsam-{value}.mp3"'),
                    ("Cache-Control", "no-store, private, max-age=0"),
                    ("Pragma", "no-cache"),
                ],
                status=200,
            )
        except Exception as exc:
            return self._json({"ok": False, "message": str(exc)}, status=500)

    @http.route(
        "/maqsam/api/contacts",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def contacts_index(self, **kwargs):
        try:
            cfg = self._config()
            page = max(int(kwargs.get("page") or 1), 1)
            params = {"page": page, "include_pagination": "true"}

            search_params = {}
            for key in ("name", "phone", "high_priority"):
                value = str(kwargs.get(key) or "").strip()
                if value:
                    search_params[key] = value

            if search_params:
                params.update(search_params)
                path = "/v2/contacts/search"
            else:
                path = "/v2/contacts"

            response = requests.get(
                f"https://api.{cfg['base_url']}{path}",
                auth=self._auth(cfg),
                params=params,
                timeout=25,
            )
            payload = self._maqsam_json(response)
            contacts = payload.get("contact") if isinstance(payload.get("contact"), list) else []
            return self._json(
                {
                    "ok": True,
                    "page": page,
                    "contacts": contacts,
                    "pagination": payload.get("pagination") or {},
                }
            )
        except Exception as exc:
            return self._json({"ok": False, "message": str(exc)}, status=500)

    @http.route(
        "/maqsam/api/contacts/<string:identifier>",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def contact_show(self, identifier, **kwargs):
        try:
            identifier = self._safe_identifier(identifier)
            cfg = self._config()
            response = requests.get(
                f"https://api.{cfg['base_url']}/v2/contacts/{identifier}",
                auth=self._auth(cfg),
                timeout=25,
            )
            payload = self._maqsam_json(response)
            return self._json({"ok": True, "contact": payload.get("contact") or {}})
        except Exception as exc:
            return self._json({"ok": False, "message": str(exc)}, status=500)

    @http.route(
        "/maqsam/api/contacts",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def contact_create(self, **kwargs):
        try:
            cfg = self._config()
            body = request.httprequest.get_json(silent=True) or {}
            name = str(body.get("name") or "").strip()
            phone = str(body.get("phone") or "").strip()
            if not name or not phone:
                raise ValueError("الاسم ورقم الهاتف مطلوبان")

            data = {
                "name": name,
                "phone": phone,
                "high_priority": bool(body.get("high_priority", False)),
            }
            response = requests.post(
                f"https://api.{cfg['base_url']}/v2/contacts",
                auth=self._auth(cfg),
                json=data,
                timeout=25,
            )
            payload = self._maqsam_json(response)
            return self._json({"ok": True, "contact": payload.get("contact") or {}})
        except Exception as exc:
            return self._json({"ok": False, "message": str(exc)}, status=500)

    @http.route(
        "/maqsam/api/contacts/<string:identifier>",
        type="http",
        auth="user",
        methods=["PATCH"],
        csrf=False,
    )
    def contact_update(self, identifier, **kwargs):
        try:
            identifier = self._safe_identifier(identifier)
            cfg = self._config()
            body = request.httprequest.get_json(silent=True) or {}
            data = {}
            for key in ("name", "phone", "high_priority"):
                if key in body:
                    data[key] = body[key]
            if not data:
                raise ValueError("أرسل حقلًا واحدًا على الأقل للتعديل")

            response = requests.patch(
                f"https://api.{cfg['base_url']}/v2/contacts/{identifier}",
                auth=self._auth(cfg),
                json=data,
                timeout=25,
            )
            payload = self._maqsam_json(response)
            return self._json({"ok": True, "contact": payload.get("contact") or {}})
        except Exception as exc:
            return self._json({"ok": False, "message": str(exc)}, status=500)

    @http.route(
        "/maqsam/api/contacts/<string:identifier>",
        type="http",
        auth="user",
        methods=["DELETE"],
        csrf=False,
    )
    def contact_delete(self, identifier, **kwargs):
        try:
            identifier = self._safe_identifier(identifier)
            cfg = self._config()
            response = requests.delete(
                f"https://api.{cfg['base_url']}/v2/contacts/{identifier}",
                auth=self._auth(cfg),
                timeout=25,
            )
            payload = self._maqsam_json(response)
            return self._json({"ok": True, "result": payload})
        except Exception as exc:
            return self._json({"ok": False, "message": str(exc)}, status=500)
