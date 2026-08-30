(() => {
    "use strict";

    const messageList = document.getElementById("messageList");
    if (!messageList) return;

    let currentConversationId = 0;
    let mediaRows = [];
    let loading = false;
    let lastFetchAt = 0;

    function selectedId() {
        return Number(localStorage.getItem("watiInboxSelected") || 0);
    }

    function mediaElement(item) {
        const type = String(item.type || "").toLowerCase();
        const wrap = document.createElement("div");
        wrap.className = `wati-media-content wati-media-${type || "file"}`;

        if (type === "image" || type === "sticker") {
            const img = document.createElement("img");
            img.src = item.media_url;
            img.alt = item.file_name || (type === "sticker" ? "ملصق" : "صورة WhatsApp");
            img.loading = "lazy";
            img.addEventListener("error", () => {
                wrap.textContent = "تعذر تحميل الصورة";
                wrap.classList.add("is-error");
            });
            wrap.appendChild(img);
            return wrap;
        }

        if (type === "video") {
            const video = document.createElement("video");
            video.src = item.media_url;
            video.controls = true;
            video.preload = "metadata";
            wrap.appendChild(video);
            return wrap;
        }

        if (type === "audio" || type === "voice") {
            const audio = document.createElement("audio");
            audio.src = item.media_url;
            audio.controls = true;
            audio.preload = "metadata";
            wrap.appendChild(audio);
            return wrap;
        }

        if (type === "document") {
            const link = document.createElement("a");
            link.href = item.media_url;
            link.target = "_blank";
            link.rel = "noopener";
            link.className = "wati-media-document";
            const title = document.createElement("strong");
            title.textContent = item.file_name || "ملف WhatsApp";
            const hint = document.createElement("span");
            hint.textContent = "فتح الملف";
            link.append(title, hint);
            wrap.appendChild(link);
            return wrap;
        }

        const link = document.createElement("a");
        link.href = item.media_url;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = item.file_name || "فتح المرفق";
        wrap.appendChild(link);
        return wrap;
    }

    function applyMedia() {
        if (!mediaRows.length) return;
        const rows = Array.from(messageList.querySelectorAll(".wati-message-row"));
        if (!rows.length) return;

        mediaRows.forEach((item, index) => {
            if (!item || !item.has_media || !item.media_url) return;
            const row = rows[index];
            if (!row) return;
            const bubble = row.querySelector(".wati-bubble");
            if (!bubble) return;

            const marker = String(item.id || index);
            if (bubble.dataset.mediaMessageId === marker && bubble.querySelector(".wati-media-content")) return;
            bubble.dataset.mediaMessageId = marker;

            bubble.querySelectorAll(".wati-media-content").forEach((node) => node.remove());
            const placeholder = bubble.querySelector(".wati-message-placeholder");
            if (placeholder) placeholder.style.display = "none";

            const element = mediaElement(item);
            const meta = bubble.querySelector(".wati-bubble-meta");
            if (meta) bubble.insertBefore(element, meta);
            else bubble.prepend(element);
        });
    }

    async function refreshMedia(force = false) {
        const conversationId = selectedId();
        if (!conversationId || loading) return;

        const now = Date.now();
        const changed = conversationId !== currentConversationId;
        if (!force && !changed && now - lastFetchAt < 3500) {
            applyMedia();
            return;
        }

        loading = true;
        try {
            const response = await fetch(
                `/wati/inbox/media-meta?conversation_id=${encodeURIComponent(conversationId)}`,
                {
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                    cache: "no-store",
                }
            );
            if (!response.ok) return;
            const payload = await response.json();
            if (!payload.ok) return;
            currentConversationId = conversationId;
            mediaRows = Array.isArray(payload.messages) ? payload.messages : [];
            lastFetchAt = Date.now();
            applyMedia();
        } catch (error) {
            console.error("WATI media enhancement error", error);
        } finally {
            loading = false;
        }
    }

    const observer = new MutationObserver(() => {
        window.setTimeout(() => refreshMedia(false), 40);
    });
    observer.observe(messageList, { childList: true, subtree: true });

    document.addEventListener("click", () => window.setTimeout(() => refreshMedia(false), 80));
    window.setInterval(() => refreshMedia(false), 3000);
    refreshMedia(true);
})();
