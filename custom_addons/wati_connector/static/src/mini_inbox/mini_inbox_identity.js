/** @odoo-module **/

import { rpc } from "@web/core/network/rpc";
import { WatiMiniInbox } from "./mini_inbox";

// Handle the identity state before rendering any list or chat data. The same
// bootstrap request drives the normal mini inbox, without an extra API call.
WatiMiniInbox.prototype.refreshBootstrap = async function (silent = false) {
    if (this.state.loading) return;
    this.state.loading = true;
    try {
        const payload = await rpc("/wati/mini/bootstrap", {}, { silent: true });
        this.state.enabled = Boolean(payload?.enabled);
        this.state.identityError = payload?.identity_error || "";
        if (!this.state.enabled || this.state.identityError) {
            this.state.unreadTotal = 0;
            this.state.conversations = [];
            this.state.selectedId = 0;
            this.state.selectedConversation = null;
            this.state.messages = [];
            this.state.assignment = null;
            this.state.draft = "";
            this.latestInboundId = 0;
            this.bootstrapInitialized = false;
            if (!this.state.enabled) this.state.open = false;
            return;
        }
        this.csrfToken = payload.csrf_token || this.csrfToken;
        const incomingId = Number(payload.latest_inbound_id || 0);
        if (!this.bootstrapInitialized) {
            this.latestInboundId = incomingId;
            this.bootstrapInitialized = true;
        } else if (incomingId > this.latestInboundId) {
            this.latestInboundId = incomingId;
            this.playNotificationSound();
        } else if (incomingId) {
            this.latestInboundId = Math.max(this.latestInboundId, incomingId);
        }
        this.state.unreadTotal = Number(payload.unread_total || 0);
        this.state.conversations = Array.isArray(payload.conversations) ? payload.conversations : [];
        if (this.state.selectedId) {
            const selected = this.state.conversations.find((row) => Number(row.id) === Number(this.state.selectedId));
            if (selected) this.state.selectedConversation = selected;
        }
    } catch (error) {
        if (!silent) this.notification.add("Unable to update WhatsApp conversations.", { type: "danger" });
        console.error("WATI mini inbox bootstrap error", error);
    } finally {
        this.state.loading = false;
    }
};

const originalLoadConversation = WatiMiniInbox.prototype.loadConversation;
WatiMiniInbox.prototype.loadConversation = async function (...args) {
    if (this.state.identityError) return;
    await originalLoadConversation.apply(this, args);
    if (this.state.identityError) {
        this.state.selectedId = 0;
        this.state.selectedConversation = null;
        this.state.messages = [];
        this.state.assignment = null;
    }
};
