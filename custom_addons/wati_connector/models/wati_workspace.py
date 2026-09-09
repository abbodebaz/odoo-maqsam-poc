from datetime import timedelta

from odoo import api, fields, models


class WatiWorkspaceGateway(models.TransientModel):
    """Read-only gateway for the WhatsApp workspace and in-app help center.

    The dashboard deliberately receives a feature registry instead of hard-coding
    navigation in the client. Future WATI features can extend
    ``_workspace_features`` / ``_workspace_help_sections`` without rebuilding the
    workspace shell.
    """

    _name = "wati.workspace.gateway"
    _description = "WhatsApp Workspace Gateway"

    @api.model
    def _workspace_features(self):
        is_admin = self.env.user.has_group("base.group_system")
        features = [
            {
                "id": "inbox",
                "title": "صندوق الوارد",
                "description": "استقبل محادثات العملاء ورد عليها من مساحة عمل واحدة.",
                "icon": "fa-comments",
                "action": "wati_connector.action_wati_inbox",
                "tone": "success",
            },
            {
                "id": "conversations",
                "title": "سجل المحادثات",
                "description": "راجع المحادثات والعملاء والمسؤولين وآخر نشاط لكل محادثة.",
                "icon": "fa-commenting-o",
                "action": "wati_connector.action_wati_conversations",
                "tone": "primary",
            },
            {
                "id": "messages",
                "title": "سجل الرسائل",
                "description": "تتبع الرسائل الواردة والصادرة وحالتها داخل WhatsApp.",
                "icon": "fa-envelope-o",
                "action": "wati_connector.action_wati_messages",
                "tone": "info",
            },
            {
                "id": "automation",
                "title": "مركز الأتمتة",
                "description": "أنشئ سيناريوهات WhatsApp مرتبطة بأحداث Odoo بدون كود.",
                "icon": "fa-bolt",
                "action": "wati_connector.action_wati_automation_studio",
                "tone": "purple",
            },
            {
                "id": "automation_logs",
                "title": "سجل التشغيل",
                "description": "اعرف متى اشتغلت الأتمتة وما الذي تم إرساله ونتيجة كل تشغيل.",
                "icon": "fa-list-alt",
                "action": "wati_connector.action_wati_automation_logs",
                "tone": "neutral",
            },
            {
                "id": "help",
                "title": "مركز المساعدة",
                "description": "تعلم إعداد WATI واستخدام المحادثات والأتمتة وحل المشاكل.",
                "icon": "fa-book",
                "action": "wati_connector.action_wati_help_center",
                "tone": "help",
            },
        ]
        if is_admin:
            features.extend(
                [
                    {
                        "id": "monitor",
                        "title": "مراقبة التكامل",
                        "description": "راقب Webhooks وحالات المعالجة والأحداث التي تحتاج انتباه.",
                        "icon": "fa-heartbeat",
                        "action": "wati_connector.action_wati_webhook_events",
                        "tone": "warning",
                        "admin": True,
                    },
                    {
                        "id": "settings",
                        "title": "الإعدادات",
                        "description": "إدارة اتصال WATI والـWebhook وميزات صندوق الوارد.",
                        "icon": "fa-cog",
                        "action": "wati_connector.action_wati_settings",
                        "tone": "settings",
                        "admin": True,
                    },
                ]
            )
        return features

    @api.model
    def _workspace_help_sections(self):
        sections = [
            {
                "id": "start",
                "title": "ابدأ من هنا",
                "icon": "fa-rocket",
                "articles": [
                    {
                        "id": "overview",
                        "title": "ما هي مساحة WhatsApp؟",
                        "summary": "نظرة سريعة على صندوق الوارد والسجلات والأتمتة ومراقبة التكامل.",
                        "steps": [
                            "استخدم الرئيسية كنقطة دخول لكل خدمات WhatsApp داخل Odoo.",
                            "صندوق الوارد مخصص للعمل اليومي والرد على العملاء.",
                            "مركز الأتمتة يربط أحداث Odoo بقوالب WATI بدون كتابة كود.",
                            "مراقبة التكامل مخصصة للمسؤولين للتحقق من Webhooks وحالة المعالجة.",
                        ],
                        "tips": ["ابدأ دائمًا من الرئيسية بدل التنقل بين الشاشات التقنية."],
                    },
                    {
                        "id": "connect-wati",
                        "title": "إعداد WATI لأول مرة",
                        "summary": "خطوات تجهيز API وWebhook قبل بدء العمل.",
                        "steps": [
                            "افتح الإعدادات من الرئيسية بحساب مسؤول.",
                            "أدخل WATI API Endpoint وAccess Token ثم اضغط اختبار الاتصال.",
                            "أنشئ Webhook Secret واحفظ الإعدادات.",
                            "انسخ Webhook URL الظاهر في Odoo وأضفه إلى Webhooks داخل WATI.",
                            "أرسل رسالة اختبار وتأكد أن الرسالة تظهر في سجل الرسائل ومراقبة التكامل.",
                        ],
                        "tips": [
                            "لا تستخدم Access Token نفسه كـWebhook Secret.",
                            "إذا تغيّر Webhook Secret يجب تحديث الرابط داخل WATI أيضًا.",
                        ],
                    },
                ],
            },
            {
                "id": "inbox",
                "title": "المحادثات",
                "icon": "fa-comments",
                "articles": [
                    {
                        "id": "use-inbox",
                        "title": "استخدام صندوق الوارد",
                        "summary": "استقبال الرسائل، فتح المحادثة والرد على العميل.",
                        "steps": [
                            "افتح صندوق الوارد من الرئيسية.",
                            "اختر المحادثة المطلوبة من القائمة.",
                            "راجع سياق المحادثة ثم اكتب الرد وأرسله.",
                            "استخدم سجل المحادثات عند الحاجة للبحث التاريخي أو معرفة المسؤول عن العميل.",
                        ],
                        "tips": ["سجل الرسائل مناسب للتتبع، وصندوق الوارد مناسب للعمل اليومي."],
                    },
                    {
                        "id": "message-statuses",
                        "title": "فهم حالات الرسائل",
                        "summary": "الفرق بين الإرسال والتسليم والقراءة والرد.",
                        "steps": [
                            "تم الإرسال: خرجت الرسالة من WATI.",
                            "تم التسليم: وصلت الرسالة إلى WhatsApp لدى المستلم.",
                            "تمت القراءة: أكد WhatsApp أن الرسالة قُرئت عندما تكون الإيصالات متاحة.",
                            "رد العميل: وصل رد جديد مرتبط بالمحادثة.",
                        ],
                        "tips": ["لا تعتبر حالة تم الإرسال دليلاً على التسليم؛ راقب دورة الحياة كاملة."],
                    },
                ],
            },
            {
                "id": "automation",
                "title": "الأتمتة",
                "icon": "fa-bolt",
                "articles": [
                    {
                        "id": "first-automation",
                        "title": "إنشاء أول أتمتة",
                        "summary": "من اختيار الحدث إلى الاختبار والتفعيل.",
                        "steps": [
                            "اختر التطبيق داخل Odoo ثم نوع السجل الذي تريد مراقبته.",
                            "حدد متى يبدأ الإرسال واختر الحقل والشرط والقيمة عند الحاجة.",
                            "حدد المستلم تلقائيًا أو اختر رقمًا من السجل أو سجل مرتبط.",
                            "اختر قالب WATI واربط متغيراته ببيانات Odoo.",
                            "في خطوة المراجعة أنشئ معاينة ثم نفذ إرسالًا تجريبيًا.",
                            "فعّل الأتمتة فقط بعد ظهور حالة الجاهزية بشكل صحيح.",
                        ],
                        "tips": ["استخدم الإرسال التجريبي قبل أول تفعيل في بيئة شركة حقيقية."],
                    },
                    {
                        "id": "automation-logs",
                        "title": "قراءة سجل التشغيل",
                        "summary": "كيف تعرف أن الأتمتة اشتغلت وما حدث للرسالة.",
                        "steps": [
                            "افتح سجل التشغيل من الرئيسية أو من مركز الأتمتة.",
                            "راجع الأتمتة والسجل الذي شغّلها ورقم المستلم والقالب.",
                            "حالة تم قبول الطلب تعني أن WATI قبل طلب الإرسال.",
                            "حالات التسليم والقراءة تأتي لاحقًا من Webhooks عندما تتوفر.",
                        ],
                        "tips": ["التفاصيل التقنية موجودة للمسؤول فقط عند الحاجة للتحقيق."],
                    },
                ],
            },
            {
                "id": "monitoring",
                "title": "المراقبة وحل المشاكل",
                "icon": "fa-heartbeat",
                "articles": [
                    {
                        "id": "webhook-monitor",
                        "title": "مراقبة Webhook",
                        "summary": "استخدمها كصندوق أسود لمعرفة ما وصل من WATI وما عالجه Odoo.",
                        "steps": [
                            "افتح مراقبة التكامل بحساب مسؤول.",
                            "راجع الحدث المفهوم مثل تم الإرسال أو التسليم أو القراءة بدل الاسم الخام.",
                            "راجع حالة المعالجة داخل Odoo بشكل منفصل عن حالة WATI.",
                            "فلتر يحتاج انتباه للعثور على Callback وصل من WATI ولم يرتبط برسالة أو تشغيل معروف.",
                            "استخدم التفاصيل التقنية والـPayload الخام فقط عند التحقيق المتقدم.",
                        ],
                        "tips": ["Callbacks المكررة محفوظة للتدقيق لكنها مخفية افتراضيًا حتى تبقى الصفحة نظيفة."],
                    },
                    {
                        "id": "message-not-sent",
                        "title": "الرسالة لم تصل",
                        "summary": "ترتيب سريع للتشخيص بدون تخمين.",
                        "steps": [
                            "ابدأ من سجل التشغيل: هل WATI قبل طلب الإرسال؟",
                            "تحقق من رقم المستلم وقالب WATI ومتغيرات القالب.",
                            "راجع مراقبة التكامل لمعرفة هل وصلت أحداث Sent أو Delivered أو Failed.",
                            "إذا لم يصل Webhook أصلًا، تحقق من Webhook URL والـSecret وإعداد WATI.",
                        ],
                        "tips": ["لا تعتمد على واجهة واحدة للحكم؛ سجل التشغيل ومراقبة التكامل يكملان بعضهما."],
                    },
                ],
            },
        ]
        return sections

    @api.model
    def get_dashboard_data(self):
        now = fields.Datetime.now()
        since = now - timedelta(hours=24)
        config = self.env["ir.config_parameter"].sudo()

        has_api = bool(
            (config.get_param("wati_connector.api_endpoint") or "").strip()
            and (config.get_param("wati_connector.api_token") or "").strip()
        )
        has_webhook = bool((config.get_param("wati_connector.webhook_token") or "").strip())
        message_count = self.env["wati.message"].sudo().search_count([])
        automation_count = (
            self.env["wati.automation.rule"]
            .sudo()
            .with_context(active_test=False)
            .search_count([])
        )

        onboarding = [
            {
                "id": "api",
                "title": "ربط حساب WATI",
                "description": "أضف Endpoint وAccess Token واختبر الاتصال.",
                "done": has_api,
                "action": "wati_connector.action_wati_settings",
            },
            {
                "id": "webhook",
                "title": "إعداد Webhook",
                "description": "اربط WATI بعنوان Webhook الآمن الخاص بـOdoo.",
                "done": has_webhook,
                "action": "wati_connector.action_wati_settings",
            },
            {
                "id": "message",
                "title": "استقبال أول رسالة",
                "description": "تأكد أن الرسائل تصل إلى صندوق الوارد وسجل الرسائل.",
                "done": bool(message_count),
                "action": "wati_connector.action_wati_inbox",
            },
            {
                "id": "automation",
                "title": "إنشاء أول أتمتة",
                "description": "ابنِ سيناريو واختبره قبل التفعيل.",
                "done": bool(automation_count),
                "action": "wati_connector.action_wati_automation_studio",
            },
        ]

        return {
            "features": self._workspace_features(),
            "connection": {
                "configured": has_api,
                "webhook_configured": has_webhook,
                "ready": has_api and has_webhook,
            },
            "kpis": {
                "unread_conversations": self.env["wati.conversation"].sudo().search_count(
                    [("unread_count", ">", 0)]
                ),
                "messages_24h": self.env["wati.message"].sudo().search_count(
                    [("received_at", ">=", since)]
                ),
                "active_automations": (
                    self.env["wati.automation.rule"]
                    .sudo()
                    .with_context(active_test=False)
                    .search_count([("active", "=", True)])
                ),
                "webhook_attention": self.env["wati.webhook.event"].sudo().search_count(
                    [
                        ("processing_state", "=", "needs_attention"),
                        ("received_at", ">=", since),
                    ]
                ),
            },
            "onboarding": onboarding,
            "onboarding_done": sum(1 for item in onboarding if item["done"]),
            "onboarding_total": len(onboarding),
            "is_admin": self.env.user.has_group("base.group_system"),
        }

    @api.model
    def get_help_content(self):
        return {"sections": self._workspace_help_sections()}
