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
        this.fileInputRef = useRef("fileInput");
        this.state = useState({
            enabled: false,
            open: false,
            loading: false,
            chatLoading: false,
            sending: false,
            uploading: false,
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
        this.csrfToken = "";
        this.latestInboundId = 0;
        this.bootstrapInitialized = false;
        this.audioContext = null;
        this.soundUnlockHandler = () => this.ensureAudioContext();

        onWillStart(async () => {
            window.addEventListener("pointerdown", this.soundUnlockHandler, { passive: true });
            window.addEventListener("keydown", this.soundUnlockHandler);
            await this.refreshBootstrap(true);
            if (this.state.enabled) {
                this.pollTimer = window.setInterval(() => this.poll(), 10000);
            }
        });
        onWillUnmount(() => {
            if (this.pollTimer) window.clearInterval(this.pollTimer);
            window.removeEventListener("pointerdown", this.soundUnlockHandler);
            window.removeEventListener("keydown", this.soundUnlockHandler);
            if (this.audioContext && typeof this.audioContext.close === "function") {
                this.audioContext.close().catch(() => {});
            }
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

    ensureAudioContext() {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;
        try {
            if (!this.audioContext) this.audioContext = new AudioContext();
            if (this.audioContext.state === "suspended") {
                this.audioContext.resume().catch(() => {});
            }
        } catch (error) {
            console.debug("WATI notification sound unavailable", error);
        }
    }

    playNotificationSound() {
        this.ensureAudioContext();
        const context = this.audioContext;
        if (!context || context.state !== "running") return;
        try {
            const now = context.currentTime;
            const oscillator = context.createOscillator();
            const gain = context.createGain();
            oscillator.type = "sine";
            oscillator.frequency.setValueAtTime(880, now);
            oscillator.frequency.setValueAtTime(1175, now + 0.11);
            gain.gain.setValueAtTime(0.0001, now);
            gain.gain.exponentialRampToValueAtTime(0.12, now + 0.015);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.24);
            oscillator.connect(gain);
            gain.connect(context.destination);
            oscillator.start(now);
            oscillator.stop(now + 0.25);
        } catch (error) {
            console.debug("WATI notification sound failed", error);
        }
    }

    async poll() {
        if (
            !this.state.enabled ||
            this.state.loading ||
            this.state.sending ||
            this.state.uploading
        ) {
            return;
        }
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
        this.ensureAudioContext();
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
        this.state.selectedConversation =
            this.state.conversations.find(
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
            this.state.selectedConversation =
                payload.conversation || this.state.selectedConversation;
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
        if (!this.canSend || this.state.sending || this.state.uploading) return;
        const text = (this.state.draft || "").trim();
        if (!text) return;

        this.state.sending = true;
        try {
            const requestId =
                window.crypto?.randomUUID?.() ||
                `${Date.now()}-${Math.random().toString(16).slice(2)}`;
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

    attachmentCategory(file) {
        const type = String(file?.type || "").toLowerCase();
        const name = String(file?.name || "").toLowerCase();
        const dot = name.lastIndexOf(".");
        const extension = dot >= 0 ? name.slice(dot) : "";
        if (type === "image/jpeg" || type === "image/png" || [".jpg", ".jpeg", ".png"].includes(extension)) {
            return "image";
        }
        if (type === "video/mp4" || type === "video/3gpp" || [".mp4", ".3gp", ".3gpp"].includes(extension)) {
            return "video";
        }
        if (type.startsWith("audio/") || [".aac", ".m4a", ".mp3", ".amr", ".ogg", ".opus"].includes(extension)) {
            return "audio";
        }
        if ([".txt", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"].includes(extension)) {
            return "document";
        }
        return "";
    }

    validateAttachment(file) {
        const category = this.attachmentCategory(file);
        if (!category) return "نوع الملف غير مدعوم في WhatsApp.";
        const limits = {
            image: 5 * 1024 * 1024,
            video: 16 * 1024 * 1024,
            audio: 16 * 1024 * 1024,
            document: 100 * 1024 * 1024,
        };
        if (!file.size) return "الملف فارغ ولا يمكن إرساله.";
        if (file.size > limits[category]) {
            return `حجم الملف أكبر من الحد المسموح (${limits[category] / (1024 * 1024)} MB).`;
        }
        return "";
    }

    pickAttachment() {
        if (!this.canSend || this.state.sending || this.state.uploading) {
            this.notification.add("استلم المحادثة أولًا قبل إرسال مرفق.", {
                type: "warning",
            });
            return;
        }
        this.fileInputRef.el?.click();
    }

    async onFileSelected(event) {
        const input = event.currentTarget;
        const file = input?.files?.[0];
        if (!file) return;
        const errorMessage = this.validateAttachment(file);
        if (errorMessage) {
            this.notification.add(errorMessage, { type: "danger" });
            input.value = "";
            return;
        }
        if ((this.state.draft || "").trim().length > 1024) {
            this.notification.add("تعليق المرفق يجب ألا يتجاوز 1024 حرفًا.", {
                type: "danger",
            });
            input.value = "";
            return;
        }

        this.state.uploading = true;
        const requestId =
            window.crypto?.randomUUID?.() ||
            `${Date.now()}-${Math.random().toString(16).slice(2)}`;
        const formData = new FormData();
        formData.append("csrf_token", this.csrfToken || "");
        formData.append("conversation_id", String(this.state.selectedId));
        formData.append("request_id", requestId);
        formData.append("caption", (this.state.draft || "").trim());
        formData.append("file", file, file.name);

        try {
            const response = await fetch("/wati/inbox/send-file", {
                method: "POST",
                credentials: "same-origin",
                headers: { Accept: "application/json" },
                body: formData,
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) {
                throw new Error(payload.message || `تعذر إرسال المرفق (${response.status})`);
            }
            this.state.draft = "";
            this.notification.add("تم إرسال المرفق إلى WATI ✅", { type: "success" });
            await this.refreshBootstrap(true);
            window.setTimeout(() => this.loadConversation(this.state.selectedId, true), 900);
            window.setTimeout(() => this.loadConversation(this.state.selectedId, true), 2400);
        } catch (error) {
            console.error("WATI Mini Inbox attachment error", error);
            this.notification.add(error.message || "تعذر إرسال المرفق.", {
                type: "danger",
            });
        } finally {
            this.state.uploading = false;
            if (input) input.value = "";
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
        if (clean.includes("image") || clean.includes("sticker")) return "📷 صورة";
        if (clean.includes("video")) return "🎥 فيديو";
        if (clean.includes("audio") || clean.includes("voice")) return "🎵 رسالة صوتية";
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
