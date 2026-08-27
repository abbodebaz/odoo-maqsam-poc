from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    maqsam_base_url = fields.Char(
        string="Maqsam Base URL",
        config_parameter="maqsam_connector.base_url",
        help="مثال: av.maqsam.com بدون https://api أو https://portal",
    )
    maqsam_access_key_id = fields.Char(
        string="Access Key ID",
        config_parameter="maqsam_connector.access_key_id",
    )
    maqsam_access_secret = fields.Char(
        string="Access Secret",
        config_parameter="maqsam_connector.access_secret",
    )
    maqsam_default_agent_email = fields.Char(
        string="Default Maqsam Agent Email",
        config_parameter="maqsam_connector.default_agent_email",
        help="إيميل الـAgent المستخدم في تجربة الاتصال. يمكن لكل مستخدم لاحقًا تحديد إيميل مختلف من صفحة المستخدم.",
    )
    maqsam_default_caller = fields.Char(
        string="Default Caller Number",
        config_parameter="maqsam_connector.default_caller",
        help="رقم مقسم الافتراضي للاتصالات الصادرة، إن احتجته.",
    )
