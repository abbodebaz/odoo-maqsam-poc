(() => {
    "use strict";

    const app = document.getElementById("watiInboxApp");
    const chatActions = document.querySelector(".wati-chat-actions");
    const messageInput = document.getElementById("messageInput");
    const toast = document.getElementById("watiToast");
    if (!app || !chatActions || !messageInput) return;

    const csrfToken = app.dataset.csrf || "";
    let templates = [];
    let selected = null;
    let loaded = false;
    let loading = false;
    let sending = false;
    let toastTimer = null;

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "wati-template-trigger";
    trigger.innerHTML = '<span class="wati-template-trigger-icon">▤</span><span>قوالب</span>';
    trigger.title = "إرسال قالب WhatsApp";
    chatActions.prepend(trigger);

    const overlay = document.createElement("div");
    overlay.className = "wati-template-overlay is-hidden";
    overlay.innerHTML = `
        <div class="wati-template-modal" role="dialog" aria-modal="true" aria-label="قوالب WhatsApp">
            <div class="wati-template-modal-head">
                <div>
                    <strong>قوالب WhatsApp</strong>
                    <span>إرسال قالب معتمد من WATI</span>
                </div>
                <button type="button" class="wati-template-close" aria-label="إغلاق">×</button>
            </div>
            <div class="wati-template-layout">
                <aside class="wati-template-sidebar">
                    <label class="wati-template-search">
                        <span>⌕</span>
                        <input type="search" placeholder="ابحث عن قالب..." />
                    </label>
                    <div class="wati-template-list"></div>
                </aside>
                <section class="wati-template-detail">
                    <div class="wati-template-empty">
                        <div>▤</div>
                        <strong>اختر قالبًا</strong>
                        <span>اختر قالبًا من القائمة لمعاينته وإرساله.</span>
                    </div>
                    <div class="wati-template-selected is-hidden">
                        <div class="wati-template-selected-head">
                            <div>
                                <strong class="wati-template-name"></strong>
                                <span class="wati-template-meta"></span>
                            </div>
                            <span class="wati-template-status"></span>
                        </div>
                        <div class="wati-template-preview"></div>
                        <div class="wati-template-params"></div>
                        <div class="wati-template-actions">
                            <button type="button" class="wati-template-send">إرسال القالب</button>
                        </div>
                    </div>
                </section>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    const closeButton = overlay.querySelector(".wati-template-close");
    const searchInput = overlay.querySelector(".wati-template-search input");
    const list = overlay.querySelector(".wati-template-list");
    const empty = overlay.querySelector(".wati-template-empty");
    const selectedBox = overlay.querySelector(".wati-template-selected");
    const nameEl = overlay.querySelector(".wati-template-name");
    const metaEl = overlay.querySelector(".wati-template-meta");
    const statusEl = overlay.querySelector(".wati-template-status");
    const previewEl = overlay.querySelector(".wati-template-preview");
    const paramsEl = overlay.querySelector(".wati-template-params");
    const sendButton = overlay.querySelector(".wati-template-send");

    function showToast(message, isError = false) {
        if (!toast) {
            if (isError) window.alert(message);
            return;
        }
        toast.textContent = message;
        toast.classList.toggle("error", isError);
        toast.classList.add("show");
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => toast.classList.remove("show"), 3500);
    }

    function requestId() {
        if (window.crypto && typeof window.crypto.randomUUID === "function") return window.crypto.randomUUID();
        return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function statusClass(status) {
        const clean = String(status || "").toLowerCase();
        if (clean.includes("approved") || clean.includes("active")) return "approved";
        if (clean.includes("reject") || clean.includes("disable")) return "rejected";
        if (clean.includes("pending") || clean.includes("review")) return "pending";
        return "neutral";
    }

    function isSendable(template) {
        const clean = String(template.status || "").toLowerCase();
        if (!clean) return true;
        return !clean.includes("reject") && !clean.includes("disable") && !clean.includes("pending");
    }

    function renderList() {
        const query = String(searchInput.value || "").trim().toLowerCase();
        const rows = templates.filter((item) => {
            if (!query) return true;
            return [item.name, item.language, item.category, item.body]
                .filter(Boolean)
                .join(" ")
                .toLowerCase()
                .includes(query);
        });
        list.replaceChildren();
        if (!rows.length) {
            const noData = document.createElement("div");
            noData.className = "wati-template-no-data";
            noData.textContent = loaded ? "لا توجد قوالب مطابقة." : "جاري تحميل القوالب...";
            list.appendChild(noData);
            return;
        }
        rows.forEach((item) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "wati-template-card";
            if (selected && selected.name === item.name && selected.language === item.language) button.classList.add("active");

            const top = document.createElement("div");
            top.className = "wati-template-card-top";
            const title = document.createElement("strong");
            title.textContent = item.name;
            const badge = document.createElement("span");
            badge.className = `wati-template-mini-status ${statusClass(item.status)}`;
            badge.textContent = item.status || "جاهز";
            top.append(title, badge);

            const body = document.createElement("span");
            body.className = "wati-template-card-body";
            body.textContent = item.body || "قالب WhatsApp";

            const meta = document.createElement("span");
            meta.className = "wati-template-card-meta";
            meta.textContent = [item.language, item.category].filter(Boolean).join(" · ");

            button.append(top, body, meta);
            button.addEventListener("click", () => selectTemplate(item));
            list.appendChild(button);
        });
    }

    function replacePreview() {
        if (!selected) return;
        let text = selected.body || selected.name || "قالب WhatsApp";
        const inputs = Array.from(paramsEl.querySelectorAll("input[data-param-name]"));
        inputs.forEach((input) => {
            const name = input.dataset.paramName || "";
            const value = input.value || `{{${name}}}`;
            const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            text = text.replace(new RegExp(`{{\\s*${escaped}\\s*}}`, "g"), value);
        });
        previewEl.textContent = text;
    }

    function selectTemplate(item) {
        selected = item;
        renderList();
        empty.classList.add("is-hidden");
        selectedBox.classList.remove("is-hidden");
        nameEl.textContent = item.name;
        metaEl.textContent = [item.language, item.category].filter(Boolean).join(" · ") || "قالب WATI";
        statusEl.textContent = item.status || "جاهز";
        statusEl.className = `wati-template-status ${statusClass(item.status)}`;
        paramsEl.replaceChildren();

        const params = Array.isArray(item.params) ? item.params : [];
        if (params.length) {
            const title = document.createElement("strong");
            title.className = "wati-template-params-title";
            title.textContent = "متغيرات القالب";
            paramsEl.appendChild(title);
            params.forEach((param, index) => {
                const label = document.createElement("label");
                label.className = "wati-template-param";
                const caption = document.createElement("span");
                caption.textContent = /^\d+$/.test(param) ? `المتغير ${param}` : param;
                const input = document.createElement("input");
                input.type = "text";
                input.dataset.paramName = param;
                input.placeholder = `اكتب قيمة ${caption.textContent}`;
                input.addEventListener("input", replacePreview);
                label.append(caption, input);
                paramsEl.appendChild(label);
            });
        }
        sendButton.disabled = !isSendable(item);
        sendButton.textContent = isSendable(item) ? "إرسال القالب" : "القالب غير متاح للإرسال";
        replacePreview();
    }

    async function loadTemplates() {
        if (loading || loaded) return;
        loading = true;
        renderList();
        try {
            const response = await fetch("/wati/inbox/templates", {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
                cache: "no-store",
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) throw new Error(payload.message || `فشل جلب القوالب (${response.status})`);
            templates = Array.isArray(payload.templates) ? payload.templates : [];
            loaded = true;
            renderList();
        } catch (error) {
            console.error("WATI template load error", error);
            showToast(error.message || "تعذر تحميل قوالب WATI.", true);
            list.innerHTML = '<div class="wati-template-no-data">تعذر تحميل القوالب. أغلق النافذة وحاول مرة أخرى.</div>';
        } finally {
            loading = false;
        }
    }

    function openModal() {
        const conversationId = Number(localStorage.getItem("watiInboxSelected") || 0);
        if (!conversationId) {
            showToast("اختر محادثة أولًا.", true);
            return;
        }
        if (messageInput.disabled) {
            showToast("استلم المحادثة أولًا قبل إرسال قالب.", true);
            return;
        }
        overlay.classList.remove("is-hidden");
        document.body.classList.add("wati-template-modal-open");
        searchInput.value = "";
        renderList();
        loadTemplates();
        window.setTimeout(() => searchInput.focus(), 50);
    }

    function closeModal() {
        if (sending) return;
        overlay.classList.add("is-hidden");
        document.body.classList.remove("wati-template-modal-open");
    }

    async function sendTemplate() {
        if (!selected || sending || !isSendable(selected)) return;
        const conversationId = Number(localStorage.getItem("watiInboxSelected") || 0);
        if (!conversationId) return;

        const paramInputs = Array.from(paramsEl.querySelectorAll("input[data-param-name]"));
        const missing = paramInputs.find((input) => !String(input.value || "").trim());
        if (missing) {
            missing.focus();
            showToast("عبّئ جميع متغيرات القالب أولًا.", true);
            return;
        }
        const values = paramInputs.map((input) => ({
            name: input.dataset.paramName || "",
            value: String(input.value || "").trim(),
        }));

        const body = new URLSearchParams({
            csrf_token: csrfToken,
            conversation_id: String(conversationId),
            template_name: selected.name,
            params_json: JSON.stringify(values),
            channel_number: selected.channel_number || "",
            request_id: requestId(),
        });

        sending = true;
        sendButton.disabled = true;
        sendButton.textContent = "جاري الإرسال...";
        try {
            const response = await fetch("/wati/inbox/send-template", {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    Accept: "application/json",
                },
                body: body.toString(),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) throw new Error(payload.message || `فشل إرسال القالب (${response.status})`);
            closeModal();
            showToast("تم إرسال القالب إلى WATI ✅");
            const refresh = document.getElementById("refreshButton");
            window.setTimeout(() => refresh && refresh.click(), 900);
            window.setTimeout(() => refresh && refresh.click(), 2400);
        } catch (error) {
            console.error("WATI template send error", error);
            showToast(error.message || "تعذر إرسال القالب.", true);
        } finally {
            sending = false;
            sendButton.disabled = !isSendable(selected);
            sendButton.textContent = isSendable(selected) ? "إرسال القالب" : "القالب غير متاح للإرسال";
        }
    }

    trigger.addEventListener("click", openModal);
    closeButton.addEventListener("click", closeModal);
    overlay.addEventListener("click", (event) => {
        if (event.target === overlay) closeModal();
    });
    searchInput.addEventListener("input", renderList);
    sendButton.addEventListener("click", sendTemplate);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !overlay.classList.contains("is-hidden")) closeModal();
    });
})();
