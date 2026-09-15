/** @odoo-module **/

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { onWillStart } from "@odoo/owl";

patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
        this.watiAction = useService("action");
        this.watiOrm = useService("orm");
        this.state.watiGlobalEnabled = false;
        onWillStart(async () => {
            try {
                const state = await this.watiOrm.call(
                    "wati.smart.button.app.policy",
                    "smart_button_state",
                    [this.props.threadModel]
                );
                this.state.watiGlobalEnabled = Boolean(state?.enabled);
            } catch {
                this.state.watiGlobalEnabled = false;
            }
        });
    },

    async openWatiGlobalCompose() {
        if (!this.props.threadId) return;
        await this.watiAction.doAction("wati_connector.action_wati_universal_compose", {
            additionalContext: {
                active_model: this.props.threadModel,
                active_id: this.props.threadId,
                active_ids: [this.props.threadId],
                wati_global_button: true,
            },
        });
    },

    async openWatiGlobalTimeline() {
        if (!this.props.threadId) return;
        await this.watiAction.doAction("wati_connector.action_wati_universal_timeline", {
            additionalContext: {
                active_model: this.props.threadModel,
                active_id: this.props.threadId,
                active_ids: [this.props.threadId],
                wati_global_button: true,
            },
        });
    },
});
