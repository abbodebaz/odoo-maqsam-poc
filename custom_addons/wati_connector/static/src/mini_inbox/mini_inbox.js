/** @odoo-module **/

import {
    Component,
    onPatched,
    onWillStart,
    onWillUnmount,
    useRef,
    useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

export class WatiMiniInbox extends Component {
    static template = "wati_connector.WatiMiniInbox";

    setup() {
        this.notification = useService("notification");
        this.messagesRef = useRef("messages");
        this.state = useState({
            enabled: false,
            open: false,
            loading: false,
            chatLoading: false,
            sending: false,
            assigning: false,
            unreadTotal: 0,
            conversations: [],
            selectedId: 0,
            selectedConversation: null,
            messages: [],
            assignment: null,
            query: "",
            draft: "",
        });
        this.pollTimer = null;

        onWillStart(async () => {
            await this.refreshBootstrap(true);
            if (this.state.enabled) {
                this.pollTimer = window.setInterval(() => this.poll(), 20000);
            }
        });
        onWillUnmount(() => {
            if (this.pollTimer) window.clearInterval(this.pollTimer);
        });
        onPatched(() => {
            if (this.state.selectedId && this.messagesRef.el) {
                this.messagesRef.el.scrollTop = this.messagesRef.el.scrollHeight;
            }
        });
    }

    get filteredConversations() {
        const query = (this.state.query || "").trim().toLowerCase();
        if (!query) return this.state.conversations;
        return this.state.conversations.filter((conversation) => {
            return [conversation.name, conversation.wa_id, conversation.last_message]
                .filter(Boolean)
                .join(" ")
                .toLowerCase()
                .includes(query);
        });
    }

    get canSend() {
        return Boolean(
            this.state.assignment?.wati_email &&
            this.state.assignment?.assigned_to_me
        );
    }

    async poll() {
        if (!this.state.enabled || this.state.loading || this.state.sending) return;
        await this.refreshBootstrap(true);
        if (this.state.open && this.state.selectedId && !this.state.chatLoading) {
            await this.loadConversation(this.state.selectedId, true);
        }
    }

    async refreshBootstrap(silent = false) {
        if (this.state.loading) return;
        this.state.loading = true;
        try {
            const payload = await rpc("/wati/mini/bootstrap", {}, { silent: true });
            this.state.enabled = Boolean(payload?.enabled);
            if (!this.state.enabled) {
                this.state.open = false;
                this.state.unreadTotal = 0;
                this.state.conversations = [];
                return;
            }
            this.state.unreadTotal = Number(payload.unread_total || 0);
            this.state.conversations = Array.isArray(payload.conversations)
                ? payload.conversations
                : [];
            if (this.state.selectedId) {
                const selected = this.state.conversations.find(
                    (conversation) => Number(conversation.id) === Number(this.state.selectedId)
                );
                if (selected) this.state.selectedConversation = selected;
            }
        } catch (error) {
            if (!silent) {
                this.notification.add("تعذر تحديث محادثات WhatsApp السريعة.", {
                    type: "danger",
                });
            }
            console.error("WATI mini inbox bootstrap error", error);
        } finally {
            this.state.loading = false;
        }
    }

    async togglePanel(event) {
        event?.preventDefault();
        event?.stopPropagation();
        this.state.open = !this.state.open;
        if (this.state.open) await this.refreshBootstrap(true);
    }

    closePanel(event) {
        event?.preventDefault();
        event?.stopPropagation();
        this.state.open = false;
    }

    async manualRefresh() {
        await this.refreshBootstrap(false);
    }

    async openConversation(conversationId) {
        this.state.selectedId = Number(conversationId || 0);
        this.state.selectedConversation = this.state.conversations.find(
            (conversation) => Number(conversation.id) === this.state.selectedId
        ) || null;
        this.state.draft = "";
        await this.loadConversation(this.state.selectedId, false);
    }

    backToList() {
        this.state.selectedId = 0;
        this.state.selectedConversation = null;
        this.state.messages = [];
        this.state.assignment = null;
        this.state.draft = "";
        this.refreshBootstrap(true);
    }

    async loadConversation(conversationId, silent = false) {
        if (!conversationId || this.state.chatLoading) return;
        this.state.chatLoading = true;
        try {
            const payload = await rpc(
                "/wati/mini/conversation",
                { conversation_id: Number(conversationId) },
                { silent: true }
            );
            if (!payload?.ok) throw new Error(payload?.message || "تعذر تحميل المحادثة");
            this.state.selectedConversation = payload.conversation || this.state.selectedConversation;
            this.state.messages = Array.isArray(payload.messages) ? payload.messages : [];
            this.state.assignment = payload.assignment || null;
        } catch (error) {
            if (!silent) {
                this.notification.add(error.message || "تعذر تحميل المحادثة.", {
                    type: "danger",
                });
            }
            console.error("WATI mini inbox conversation error", error);
        } finally {
            this.state.chatLoading = false;
        }
    }

    async assignCurrent(force = false) {
        if (!this.state.selectedId || this.state.assigning) return;
        if (force) {
            const owner = this.state.assignment?.assigned_user_name || "موظف آخر";
            if (!window.confirm(`المحادثة حاليًا عند ${owner}. هل تريد نقلها إليك؟`)) return;
        }
        this.state.assigning = true;
        try {
            const payload = await rpc(
                "/wati/mini/assign",
                { conversation_id: this.state.selectedId, force: Boolean(force) },
                { silent: true }
            );
            if (!payload?.ok) throw new Error(payload?.message || "تعذر استلام المحادثة");
            this.notification.add(payload.message || "تم استلام المحادثة ✅", {
                type: "success",
            });
            await this.loadConversation(this.state.selectedId, true);
            await this.refreshBootstrap(true);
        } catch (error) {
            this.notification.add(error.message || "تعذر استلام المحادثة.", {
                type: "danger",
            });
        } finally {
            this.state.assigning = false;
        }
    }

    async sendMessage() {
        if (!this.canSend || this.state.sending) return;
        const text = (this.state.draft || "").trim();
        if (!text) return;

        this.state.sending = true;
        try {
            const requestId = window.crypto?.randomUUID?.()
                || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
            const payload = await rpc(
                "/wati/mini/send",
                {
                    conversation_id: this.state.selectedId,
                    message: text,
                    request_id: requestId,
                },
                { silent: true }
            );
            if (!payload?.ok) throw new Error(payload?.message || "تعذر إرسال الرسالة");
            this.state.draft = "";
            await this.loadConversation(this.state.selectedId, true);
            await this.refreshBootstrap(true);
        } catch (error) {
            this.notification.add(error.message || "تعذر إرسال الرسالة.", {
                type: "danger",
            });
        } finally {
            this.state.sending = false;
        }
    }

    onComposerKeydown(event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            this.sendMessage();
        }
    }

    initials(name) {
        const clean = String(name || "").trim();
        if (!clean) return "W";
        const digits = clean.replace(/\D/g, "");
        if (digits.length >= 7) return digits.slice(-2);
        return clean
            .split(/\s+/)
            .filter(Boolean)
            .slice(0, 2)
            .map((part) => part.charAt(0))
            .join("")
            .toUpperCase();
    }

    formatTime(value) {
        if (!value) return "";
        const normalized = String(value).includes("T")
            ? String(value)
            : `${String(value).replace(" ", "T")}Z`;
        const date = new Date(normalized);
        if (Number.isNaN(date.getTime())) return "";
        const now = new Date();
        if (date.toDateString() === now.toDateString()) {
            return new Intl.DateTimeFormat("ar-SA", {
                hour: "numeric",
                minute: "2-digit",
            }).format(date);
        }
        return new Intl.DateTimeFormat("ar-SA", {
            month: "short",
            day: "numeric",
        }).format(date);
    }

    messagePlaceholder(type) {
        const clean = String(type || "").toLowerCase();
        if (clean.includes("image")) return "📷 صورة";
        if (clean.includes("video")) return "🎥 فيديو";
        if (clean.includes("audio")) return "🎵 رسالة صوتية";
        if (clean.includes("document") || clean.includes("file")) return "📎 ملف";
        if (clean.includes("location")) return "📍 موقع";
        return "رسالة";
    }
}

registry.category("systray").add(
    "wati_connector.WatiMiniInbox",
    { Component: WatiMiniInbox },
    { sequence: 35 }
);
