(() => {
    "use strict";

    const app = document.getElementById("watiInboxApp");
    if (!app) return;

    const csrfToken = app.dataset.csrf || "";
    const conversationList = document.getElementById("conversationList");
    const conversationCount = document.getElementById("conversationCount");
    const searchInput = document.getElementById("conversationSearch");
    const refreshButton = document.getElementById("refreshButton");
    const filters = Array.from(document.querySelectorAll(".wati-filter"));
    const chatEmpty = document.getElementById("chatEmpty");
    const chatContent = document.getElementById("chatContent");
    const chatAvatar = document.getElementById("chatAvatar");
    const chatName = document.getElementById("chatName");
    const chatNumber = document.getElementById("chatNumber");
    const chatStatus = document.getElementById("chatStatus");
    const chatOperator = document.getElementById("chatOperator");
    const messageList = document.getElementById("messageList");
    const messageForm = document.getElementById("messageForm");
    const messageInput = document.getElementById("messageInput");
    const sendButton = document.getElementById("sendButton");
    const mobileBack = document.getElementById("mobileBack");
    const toast = document.getElementById("watiToast");

    const state = {
        conversations: [],
        messages: [],
        selectedId: Number(localStorage.getItem("watiInboxSelected") || 0),
        currentUserId: 0,
        filter: "all",
        query: "",
        loading: false,
        sending: false,
        messageSignature: "",
    };

    let toastTimer = null;

    function showToast(message, isError = false) {
        if (!toast) return;
        toast.textContent = message;
        toast.classList.toggle("error", isError);
        toast.classList.add("show");
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => toast.classList.remove("show"), 3200);
    }

    function initials(name) {
        const clean = String(name || "W").trim();
        if (!clean) return "W";
        const words = clean.split(/\s+/).filter(Boolean);
        return words.slice(0, 2).map((word) => word.charAt(0)).join("").toUpperCase();
    }

    function parseServerDate(value) {
        if (!value) return null;
        const normalized = value.includes("T") ? value : value.replace(" ", "T") + "Z";
        const parsed = new Date(normalized);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    function formatTime(value) {
        const date = parseServerDate(value);
        if (!date) return "";
        const now = new Date();
        const sameDay = date.toDateString() === now.toDateString();
        if (sameDay) {
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

    function messageStatus(status) {
        const clean = String(status || "").toLowerCase();
        if (clean.includes("read")) return { text: "✓✓", read: true };
        if (clean.includes("deliver")) return { text: "✓✓", read: false };
        if (clean.includes("sent")) return { text: "✓", read: false };
        if (clean.includes("fail")) return { text: "!", read: false };
        return { text: "", read: false };
    }

    function placeholderForType(type) {
        const clean = String(type || "").toLowerCase();
        if (clean.includes("image")) return "📷 صورة";
        if (clean.includes("video")) return "🎥 فيديو";
        if (clean.includes("audio")) return "🎵 رسالة صوتية";
        if (clean.includes("document") || clean.includes("file")) return "📎 ملف";
        if (clean.includes("location")) return "📍 موقع";
        if (clean.includes("template")) return "رسالة قالب";
        return "رسالة";
    }

    function selectedConversation() {
        return state.conversations.find((item) => Number(item.id) === Number(state.selectedId)) || null;
    }

    function filteredConversations() {
        const query = state.query.trim().toLowerCase();
        return state.conversations.filter((conversation) => {
            if (state.filter === "unread" && !(Number(conversation.unread_count) > 0)) return false;
            if (state.filter === "mine" && !conversation.assigned_to_me) return false;
            if (state.filter === "unassigned" && !conversation.is_unassigned) return false;
            if (!query) return true;
            const haystack = [
                conversation.name,
                conversation.wa_id,
                conversation.last_message,
                conversation.partner_name,
                conversation.assigned_user_name,
            ]
                .filter(Boolean)
                .join(" ")
                .toLowerCase();
            return haystack.includes(query);
        });
    }

    function renderConversations() {
        const rows = filteredConversations();
        conversationList.replaceChildren();
        conversationCount.textContent = `${rows.length} من ${state.conversations.length} محادثة`;

        if (!rows.length) {
            const empty = document.createElement("div");
            empty.className = "wati-list-empty";
            empty.textContent = state.query || state.filter !== "all"
                ? "لا توجد محادثات مطابقة."
                : "لا توجد محادثات WhatsApp حتى الآن.";
            conversationList.appendChild(empty);
            return;
        }

        rows.forEach((conversation) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "wati-conversation";
            button.dataset.conversationId = String(conversation.id);
            if (Number(conversation.id) === Number(state.selectedId)) button.classList.add("active");

            const avatar = document.createElement("div");
            avatar.className = "wati-avatar";
            avatar.textContent = initials(conversation.name);

            const main = document.createElement("div");
            main.className = "wati-conversation-main";
            const title = document.createElement("div");
            title.className = "wati-conversation-title";
            title.textContent = conversation.name || conversation.wa_id || "WhatsApp";
            const preview = document.createElement("div");
            preview.className = "wati-conversation-preview";
            preview.textContent = conversation.last_message || conversation.wa_id || "بدون رسائل";
            main.append(title, preview);

            const side = document.createElement("div");
            side.className = "wati-conversation-side";
            const time = document.createElement("span");
            time.className = "wati-conversation-time";
            time.textContent = formatTime(conversation.last_message_at);
            side.appendChild(time);
            if (Number(conversation.unread_count) > 0) {
                const unread = document.createElement("span");
                unread.className = "wati-unread";
                unread.textContent = String(conversation.unread_count);
                side.appendChild(unread);
            }

            button.append(avatar, main, side);
            button.addEventListener("click", () => selectConversation(conversation.id));
            conversationList.appendChild(button);
        });
    }

    function renderHeader() {
        const conversation = selectedConversation();
        if (!conversation) {
            chatEmpty.classList.remove("is-hidden");
            chatContent.classList.add("is-hidden");
            return;
        }

        chatEmpty.classList.add("is-hidden");
        chatContent.classList.remove("is-hidden");
        chatAvatar.textContent = initials(conversation.name);
        chatName.textContent = conversation.name || conversation.wa_id || "WhatsApp";
        chatNumber.textContent = conversation.wa_id || "";
        chatStatus.textContent = conversation.status || "";
        chatOperator.textContent = conversation.assigned_user_name
            ? `الموظف: ${conversation.assigned_user_name}`
            : (conversation.operator_name ? `الموظف: ${conversation.operator_name}` : "");
    }

    function renderMessages(force = false) {
        const signature = state.messages
            .map((message) => `${message.id}:${message.status}:${message.text}`)
            .join("|");
        if (!force && signature === state.messageSignature) return;
        state.messageSignature = signature;

        const distanceFromBottom = messageList.scrollHeight - messageList.scrollTop - messageList.clientHeight;
        const shouldStickToBottom = force || distanceFromBottom < 120;
        messageList.replaceChildren();

        if (!state.messages.length) {
            const empty = document.createElement("div");
            empty.className = "wati-list-empty";
            empty.textContent = "لا توجد رسائل محفوظة لهذه المحادثة.";
            messageList.appendChild(empty);
            return;
        }

        state.messages.forEach((message) => {
            const row = document.createElement("div");
            row.className = `wati-message-row ${message.direction === "outbound" ? "outbound" : "inbound"}`;

            const bubble = document.createElement("div");
            bubble.className = "wati-bubble";

            const text = document.createElement("div");
            const visibleText = String(message.text || "").trim();
            if (visibleText) {
                text.textContent = visibleText;
            } else {
                text.textContent = placeholderForType(message.message_type);
                text.className = "wati-message-placeholder";
            }

            const meta = document.createElement("div");
            meta.className = "wati-bubble-meta";
            const time = document.createElement("span");
            time.textContent = formatTime(message.received_at);
            meta.appendChild(time);

            if (message.direction === "outbound") {
                const status = messageStatus(message.status);
                if (status.text) {
                    const check = document.createElement("span");
                    check.className = `wati-check${status.read ? " read" : ""}`;
                    check.textContent = status.text;
                    check.title = message.status || "";
                    meta.appendChild(check);
                }
            }

            bubble.append(text, meta);
            row.appendChild(bubble);
            messageList.appendChild(row);
        });

        if (shouldStickToBottom) {
            requestAnimationFrame(() => {
                messageList.scrollTop = messageList.scrollHeight;
            });
        }
    }

    async function loadData({ forceMessages = false, silent = false } = {}) {
        if (state.loading || state.sending) return;
        state.loading = true;
        if (!silent) refreshButton.disabled = true;
        try {
            const params = new URLSearchParams();
            if (state.selectedId) params.set("conversation_id", String(state.selectedId));
            const response = await fetch(`/wati/inbox/data?${params.toString()}`, {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
                cache: "no-store",
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const payload = await response.json();
            if (!payload.ok) throw new Error(payload.message || "تعذر تحميل المحادثات");

            state.conversations = Array.isArray(payload.conversations) ? payload.conversations : [];
            state.messages = Array.isArray(payload.messages) ? payload.messages : [];
            state.currentUserId = Number(payload.current_user_id || 0);
            state.selectedId = Number(payload.selected_id || 0);
            if (state.selectedId) localStorage.setItem("watiInboxSelected", String(state.selectedId));

            renderConversations();
            renderHeader();
            renderMessages(forceMessages);
        } catch (error) {
            console.error("WATI Inbox load error", error);
            if (!silent) showToast("تعذر تحديث صندوق WhatsApp. حاول مرة أخرى.", true);
        } finally {
            state.loading = false;
            refreshButton.disabled = false;
        }
    }

    async function selectConversation(id) {
        state.selectedId = Number(id || 0);
        state.messageSignature = "";
        if (state.selectedId) localStorage.setItem("watiInboxSelected", String(state.selectedId));
        app.classList.add("mobile-chat-open");
        renderConversations();
        await loadData({ forceMessages: true });
    }

    async function sendMessage(event) {
        event.preventDefault();
        if (state.sending || !state.selectedId) return;
        const message = messageInput.value.trim();
        if (!message) return;

        state.sending = true;
        sendButton.disabled = true;
        sendButton.textContent = "جاري الإرسال...";
        try {
            const body = new URLSearchParams({
                csrf_token: csrfToken,
                conversation_id: String(state.selectedId),
                message,
            });
            const response = await fetch("/wati/inbox/send", {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    Accept: "application/json",
                },
                body: body.toString(),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) {
                throw new Error(payload.message || `فشل الإرسال (${response.status})`);
            }

            messageInput.value = "";
            resizeComposer();
            showToast("تم إرسال الرسالة إلى WATI ✅");
            state.messageSignature = "";
            window.setTimeout(() => loadData({ forceMessages: true, silent: true }), 600);
            window.setTimeout(() => loadData({ forceMessages: true, silent: true }), 1800);
        } catch (error) {
            console.error("WATI send error", error);
            showToast(error.message || "تعذر إرسال الرسالة.", true);
        } finally {
            state.sending = false;
            sendButton.disabled = false;
            sendButton.innerHTML = "إرسال <span>➤</span>";
            messageInput.focus();
        }
    }

    function resizeComposer() {
        messageInput.style.height = "auto";
        messageInput.style.height = `${Math.min(messageInput.scrollHeight, 140)}px`;
    }

    searchInput.addEventListener("input", () => {
        state.query = searchInput.value || "";
        renderConversations();
    });

    filters.forEach((button) => {
        button.addEventListener("click", () => {
            state.filter = button.dataset.filter || "all";
            filters.forEach((item) => item.classList.toggle("active", item === button));
            renderConversations();
        });
    });

    refreshButton.addEventListener("click", () => loadData({ forceMessages: true }));
    messageForm.addEventListener("submit", sendMessage);
    messageInput.addEventListener("input", resizeComposer);
    messageInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            messageForm.requestSubmit();
        }
    });
    mobileBack.addEventListener("click", () => app.classList.remove("mobile-chat-open"));

    loadData({ forceMessages: true });
    window.setInterval(() => loadData({ silent: true }), 4000);
})();
