(() => {
    "use strict";

    try {
        const app = document.getElementById("watiInboxApp");
        const messageList = document.getElementById("messageList");
        const conversationList = document.getElementById("conversationList");
        const composer = document.getElementById("messageForm");
        const messageInput = document.getElementById("messageInput");
        if (!app || !messageList || !conversationList || !composer || !messageInput) return;

        const style = document.createElement("style");
        style.id = "wati-ui-polish-v4";
        style.textContent = `
            :root {
                --ui-green: #18a957;
                --ui-green-dark: #128746;
                --ui-green-soft: #eaf8ef;
                --ui-text: #17212b;
                --ui-muted: #74818c;
                --ui-border: #e3e8ec;
            }

            .wati-topbar {
                height: 62px !important;
                flex-basis: 62px !important;
                padding: 0 18px !important;
            }
            .wati-logo {
                width: 36px !important;
                height: 36px !important;
                border-radius: 11px !important;
                font-size: 17px !important;
            }
            .wati-brand strong { font-size: 15px !important; }
            .wati-brand span { font-size: 11px !important; margin-top: 2px !important; }
            .wati-odoo-link {
                border-radius: 12px !important;
                padding: 8px 12px !important;
                font-size: 12px !important;
                background: #fff;
            }
            .wati-agent { font-size: 12px !important; }

            .wati-workspace {
                grid-template-columns: 342px minmax(0, 1fr) !important;
            }
            .wati-sidebar-head {
                padding: 17px 16px 10px !important;
            }
            .wati-sidebar-head h1 { font-size: 18px !important; }
            .wati-sidebar-head p { font-size: 11px !important; margin-top: 3px !important; }
            .wati-search { margin: 0 14px 10px !important; border-radius: 13px !important; }
            .wati-filters {
                padding-inline: 14px !important;
                gap: 6px !important;
                margin-bottom: 8px !important;
                flex-wrap: nowrap !important;
                overflow-x: auto;
                scrollbar-width: none;
            }
            .wati-filters::-webkit-scrollbar { display: none; }
            .wati-filter {
                min-width: max-content;
                padding: 7px 10px !important;
                font-size: 11px !important;
                border-radius: 999px !important;
            }
            .wati-conversation {
                min-height: 74px !important;
                padding: 10px 14px !important;
                border-bottom-color: #eef1f3 !important;
                transition: background .15s ease, transform .15s ease !important;
            }
            .wati-conversation:hover { background: #f8faf9 !important; }
            .wati-conversation.active {
                background: #ecf9f1 !important;
                box-shadow: inset -3px 0 0 var(--ui-green);
            }
            .wati-conversation .wati-avatar {
                width: 42px !important;
                height: 42px !important;
                min-width: 42px !important;
                font-size: 14px !important;
                border-radius: 50% !important;
            }
            .wati-conversation-title {
                font-size: 13.5px !important;
                font-weight: 750 !important;
                line-height: 1.35 !important;
            }
            .wati-conversation-preview {
                margin-top: 4px !important;
                font-size: 11.5px !important;
                line-height: 1.4 !important;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                max-width: 205px;
            }
            .wati-conversation-side { min-width: 42px !important; gap: 5px !important; }
            .wati-conversation-time { font-size: 9.5px !important; }
            .wati-unread {
                min-width: 19px !important;
                height: 19px !important;
                font-size: 10px !important;
                padding: 0 5px !important;
            }
            .wati-assignee-mini {
                display: inline-flex;
                align-items: center;
                gap: 4px;
                margin-top: 4px;
                max-width: 180px;
                color: #6b7882;
                font-size: 9.5px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .wati-assignee-mini::before {
                content: "";
                width: 5px;
                height: 5px;
                border-radius: 50%;
                background: #9aa6ae;
                flex: 0 0 auto;
            }
            .wati-assignee-mini.mine { color: #138347; font-weight: 700; }
            .wati-assignee-mini.mine::before { background: var(--ui-green); }

            .wati-chat-head {
                min-height: 64px !important;
                padding: 8px 18px !important;
                gap: 12px !important;
            }
            .wati-chat-person { gap: 10px !important; }
            .wati-chat-person > .wati-avatar {
                width: 42px !important;
                height: 42px !important;
                min-width: 42px !important;
                border-radius: 50% !important;
            }
            .wati-chat-person h2 {
                font-size: 14.5px !important;
                font-weight: 780 !important;
            }
            .wati-chat-meta { margin-top: 2px !important; font-size: 10.5px !important; }
            .wati-status-badge { display: none !important; }
            .wati-chat-actions { gap: 7px !important; }
            .wati-chat-actions > div:first-child {
                gap: 6px !important;
                flex-wrap: nowrap !important;
            }
            .wati-chat-actions > div:first-child button {
                border-radius: 999px !important;
                padding: 6px 10px !important;
                min-height: 30px;
                font-size: 10.5px !important;
                box-shadow: none !important;
            }
            .wati-operator {
                padding: 5px 8px;
                background: #f4f6f7;
                border-radius: 999px;
                font-size: 10px !important;
            }

            .wati-message-list {
                padding: 22px clamp(18px, 4vw, 56px) 26px !important;
                position: relative;
                overscroll-behavior: contain;
            }
            .wati-message-row { margin: 4px 0 !important; position: relative; }
            .wati-bubble {
                max-width: min(620px, 69%) !important;
                border-radius: 14px !important;
                padding: 8px 10px 6px !important;
                font-size: 12.5px !important;
                line-height: 1.58 !important;
                box-shadow: 0 1px 2px rgba(25, 35, 45, .075) !important;
                position: relative;
                transition: box-shadow .12s ease;
            }
            .wati-message-row:hover .wati-bubble {
                box-shadow: 0 2px 8px rgba(25, 35, 45, .08) !important;
            }
            .wati-bubble-meta { font-size: 9px !important; margin-top: 3px !important; }
            .wati-check.read { color: #1689d4 !important; }

            .wati-day-separator,
            .wati-unread-divider {
                width: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                clear: both;
                pointer-events: none;
            }
            .wati-day-separator { margin: 13px 0 10px; }
            .wati-day-separator span {
                display: inline-flex;
                align-items: center;
                min-height: 25px;
                padding: 4px 11px;
                border: 1px solid rgba(209, 218, 224, .85);
                border-radius: 999px;
                background: rgba(255,255,255,.9);
                color: #71808a;
                font-size: 9.5px;
                box-shadow: 0 1px 4px rgba(15,23,42,.035);
            }
            .wati-unread-divider {
                gap: 10px;
                margin: 15px 0 11px;
                color: #138347;
                font-size: 10px;
                font-weight: 750;
            }
            .wati-unread-divider::before,
            .wati-unread-divider::after {
                content: "";
                height: 1px;
                flex: 1;
                max-width: 260px;
                background: rgba(24,169,87,.2);
            }

            .wati-scroll-bottom {
                position: absolute;
                left: 18px;
                bottom: 78px;
                z-index: 8;
                width: 38px;
                height: 38px;
                border: 1px solid #dce4e8;
                border-radius: 50%;
                background: rgba(255,255,255,.96);
                color: #50606b;
                display: none;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                box-shadow: 0 5px 18px rgba(15,23,42,.12);
                font-size: 18px;
            }
            .wati-scroll-bottom.show { display: inline-flex; }
            .wati-scroll-bottom-count {
                position: absolute;
                top: -6px;
                right: -5px;
                min-width: 18px;
                height: 18px;
                padding: 0 4px;
                border-radius: 999px;
                display: none;
                align-items: center;
                justify-content: center;
                background: var(--ui-green);
                color: white;
                border: 2px solid white;
                font-size: 8px;
                font-weight: 800;
            }
            .wati-scroll-bottom.has-new .wati-scroll-bottom-count { display: inline-flex; }

            .wati-bubble-actions {
                position: absolute;
                top: 5px;
                left: -31px;
                opacity: 0;
                transform: translateX(3px);
                transition: opacity .12s ease, transform .12s ease;
                z-index: 4;
            }
            .inbound .wati-bubble-actions { left: auto; right: -31px; }
            .wati-message-row:hover .wati-bubble-actions { opacity: 1; transform: none; }
            .wati-bubble-menu-button {
                width: 25px;
                height: 25px;
                border: 0;
                border-radius: 8px;
                background: rgba(255,255,255,.93);
                color: #697781;
                cursor: pointer;
                box-shadow: 0 1px 6px rgba(15,23,42,.09);
            }
            .wati-bubble-menu {
                position: absolute;
                top: 29px;
                left: 0;
                width: 124px;
                padding: 5px;
                border: 1px solid var(--ui-border);
                border-radius: 10px;
                background: white;
                box-shadow: 0 8px 24px rgba(15,23,42,.12);
                display: none;
                direction: rtl;
            }
            .inbound .wati-bubble-menu { left: auto; right: 0; }
            .wati-bubble-actions.open .wati-bubble-menu { display: block; }
            .wati-bubble-menu button,
            .wati-bubble-menu a {
                width: 100%;
                min-height: 30px;
                border: 0;
                border-radius: 7px;
                background: transparent;
                color: #35434d;
                text-decoration: none;
                display: flex;
                align-items: center;
                padding: 5px 8px;
                font-size: 10px;
                cursor: pointer;
            }
            .wati-bubble-menu button:hover,
            .wati-bubble-menu a:hover { background: #f3f6f7; }

            .wati-media-content img {
                max-width: min(320px, 100%) !important;
                max-height: 360px !important;
                border-radius: 11px !important;
                cursor: zoom-in;
                object-fit: cover;
            }
            .wati-media-content video {
                max-width: min(360px, 100%) !important;
                max-height: 380px !important;
                border-radius: 11px !important;
            }
            .wati-media-document {
                min-width: min(310px, 100%) !important;
                border-radius: 11px !important;
                padding: 10px 11px !important;
                gap: 9px !important;
            }
            .wati-media-document::before {
                content: "📄";
                width: 34px;
                height: 34px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                background: #f2f5f6;
                border-radius: 9px;
                font-size: 17px;
                flex: 0 0 auto;
            }
            .wati-media-document strong {
                max-width: 205px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
                font-size: 11px !important;
            }
            .wati-media-document span { font-size: 9.5px !important; }

            .wati-native-audio-hidden { display: none !important; }
            .wati-voice-ui {
                width: min(300px, 100%);
                min-width: 230px;
                display: grid;
                grid-template-columns: 34px minmax(0,1fr) auto;
                gap: 8px;
                align-items: center;
                direction: ltr;
                padding: 3px 1px;
            }
            .wati-voice-play {
                width: 34px;
                height: 34px;
                border: 0;
                border-radius: 50%;
                background: var(--ui-green);
                color: white;
                cursor: pointer;
                display: grid;
                place-items: center;
                font-size: 13px;
            }
            .wati-voice-track {
                height: 4px;
                border-radius: 999px;
                background: rgba(91,109,120,.19);
                overflow: hidden;
                cursor: pointer;
            }
            .wati-voice-progress {
                display: block;
                width: 0;
                height: 100%;
                border-radius: inherit;
                background: var(--ui-green);
            }
            .wati-voice-time { color: #71808a; font-size: 9px; min-width: 34px; }

            .wati-lightbox {
                position: fixed;
                inset: 0;
                z-index: 10000;
                display: none;
                align-items: center;
                justify-content: center;
                padding: 32px;
                background: rgba(10,17,22,.87);
                backdrop-filter: blur(3px);
            }
            .wati-lightbox.open { display: flex; }
            .wati-lightbox img {
                max-width: min(1100px, 92vw);
                max-height: 88vh;
                object-fit: contain;
                border-radius: 12px;
                box-shadow: 0 18px 60px rgba(0,0,0,.32);
            }
            .wati-lightbox-close {
                position: absolute;
                top: 18px;
                left: 18px;
                width: 38px;
                height: 38px;
                border: 0;
                border-radius: 50%;
                background: rgba(255,255,255,.13);
                color: white;
                font-size: 24px;
                cursor: pointer;
            }

            .wati-composer-note { display: none !important; }
            .wati-composer {
                grid-template-columns: 44px 44px minmax(0,1fr) auto !important;
                padding: 9px 14px !important;
                gap: 7px !important;
                border-top-color: #e6ebee !important;
            }
            .wati-composer .wati-attach-button {
                grid-column: 1 !important;
                width: 44px !important;
                height: 44px !important;
                min-width: 44px !important;
            }
            .wati-composer .wati-template-trigger.ui-template-compose {
                grid-column: 2 !important;
                width: 44px !important;
                min-width: 44px !important;
                height: 44px !important;
                padding: 0 !important;
                border: 1px solid #d9e2e8 !important;
                border-radius: 50% !important;
                background: #fff !important;
                color: #53636e !important;
                display: inline-flex !important;
                align-items: center;
                justify-content: center;
                box-shadow: 0 2px 7px rgba(15,23,42,.045) !important;
                font-size: 17px !important;
            }
            .wati-composer .wati-template-trigger.ui-template-compose:hover:not(:disabled) {
                border-color: #9bdcb5 !important;
                background: #eefbf3 !important;
                color: #149447 !important;
            }
            .wati-composer .wati-template-trigger.ui-template-compose span:last-child { display: none !important; }
            .wati-composer textarea {
                grid-column: 3 !important;
                min-height: 44px !important;
                max-height: 128px !important;
                border-radius: 22px !important;
                padding: 10px 16px !important;
                line-height: 1.5 !important;
            }
            .wati-composer #sendButton {
                grid-column: 4 !important;
                min-width: 84px !important;
                height: 44px !important;
                border-radius: 22px !important;
                padding: 0 16px !important;
            }
            .wati-attachment-preview {
                margin: 7px 14px 0 !important;
                border-radius: 11px !important;
            }

            .wati-message-list.ui-switching::after {
                content: "";
                position: absolute;
                inset: 0;
                z-index: 6;
                pointer-events: none;
                background: linear-gradient(100deg, rgba(238,242,244,.68) 25%, rgba(255,255,255,.82) 40%, rgba(238,242,244,.68) 55%) 0 0 / 220% 100%;
                animation: watiUiShimmer .8s linear infinite;
            }
            @keyframes watiUiShimmer { to { background-position: -220% 0; } }

            @media (max-width: 1100px) {
                .wati-workspace { grid-template-columns: 320px minmax(0,1fr) !important; }
                .wati-bubble { max-width: 76% !important; }
            }
            @media (max-width: 720px) {
                .wati-topbar { height: 56px !important; flex-basis: 56px !important; padding: 0 10px !important; }
                .wati-brand span, .wati-agent { display: none !important; }
                .wati-odoo-link { font-size: 0 !important; width: 38px; height: 38px; padding: 0 !important; display: grid; place-items: center; }
                .wati-odoo-link::after { content: "↩"; font-size: 18px; }
                .wati-chat-head { min-height: 58px !important; padding: 7px 10px !important; }
                .wati-chat-actions > div:first-child button { max-width: 132px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
                .wati-message-list { padding: 15px 10px 20px !important; }
                .wati-bubble { max-width: 86% !important; font-size: 12px !important; }
                .wati-bubble-actions { display: none !important; }
                .wati-composer {
                    grid-template-columns: 40px 40px minmax(0,1fr) 46px !important;
                    padding: 7px 8px !important;
                    gap: 5px !important;
                }
                .wati-composer .wati-attach-button,
                .wati-composer .wati-template-trigger.ui-template-compose {
                    width: 40px !important;
                    min-width: 40px !important;
                    height: 40px !important;
                }
                .wati-composer textarea { min-height: 40px !important; padding: 8px 12px !important; }
                .wati-composer #sendButton { min-width: 46px !important; width: 46px !important; height: 40px !important; padding: 0 !important; font-size: 0 !important; }
                .wati-composer #sendButton span { font-size: 17px !important; }
                .wati-scroll-bottom { bottom: 66px; left: 10px; }
            }
        `;
        document.head.appendChild(style);

        const brandStrong = document.querySelector(".wati-brand strong");
        const brandSub = document.querySelector(".wati-brand span");
        const returnLink = document.querySelector(".wati-odoo-link");
        if (brandStrong) brandStrong.textContent = "محادثات واتساب";
        if (brandSub) brandSub.textContent = "خدمة العملاء";
        if (returnLink) {
            returnLink.textContent = "العودة إلى Odoo";
            returnLink.title = "العودة إلى WhatsApp داخل Odoo";
        }

        const templateTrigger = document.querySelector(".wati-template-trigger");
        if (templateTrigger) {
            templateTrigger.classList.add("ui-template-compose");
            templateTrigger.title = "قوالب WhatsApp";
            templateTrigger.setAttribute("aria-label", "قوالب WhatsApp");
            const input = document.getElementById("messageInput");
            if (input && input.parentNode === composer) composer.insertBefore(templateTrigger, input);
        }

        const chatContent = document.getElementById("chatContent");
        const scrollButton = document.createElement("button");
        scrollButton.type = "button";
        scrollButton.className = "wati-scroll-bottom";
        scrollButton.title = "النزول إلى آخر المحادثة";
        scrollButton.setAttribute("aria-label", "النزول إلى آخر المحادثة");
        scrollButton.innerHTML = '<span>↓</span><span class="wati-scroll-bottom-count">0</span>';
        if (chatContent) chatContent.appendChild(scrollButton);
        const scrollCount = scrollButton.querySelector(".wati-scroll-bottom-count");
        let pendingNew = 0;
        let previousRows = messageList.querySelectorAll(".wati-message-row").length;
        let userNearBottom = true;

        function distanceFromBottom() {
            return messageList.scrollHeight - messageList.scrollTop - messageList.clientHeight;
        }
        function updateScrollButton() {
            userNearBottom = distanceFromBottom() < 130;
            scrollButton.classList.toggle("show", !userNearBottom);
            if (userNearBottom) pendingNew = 0;
            scrollButton.classList.toggle("has-new", pendingNew > 0);
            if (scrollCount) scrollCount.textContent = String(pendingNew || 0);
        }
        messageList.addEventListener("scroll", updateScrollButton, { passive: true });
        scrollButton.addEventListener("click", () => {
            pendingNew = 0;
            messageList.scrollTo({ top: messageList.scrollHeight, behavior: "smooth" });
            window.setTimeout(updateScrollButton, 320);
        });

        const lightbox = document.createElement("div");
        lightbox.className = "wati-lightbox";
        lightbox.innerHTML = '<button type="button" class="wati-lightbox-close" aria-label="إغلاق">×</button><img alt="معاينة الصورة" />';
        document.body.appendChild(lightbox);
        const lightboxImg = lightbox.querySelector("img");
        function closeLightbox() {
            lightbox.classList.remove("open");
            if (lightboxImg) lightboxImg.removeAttribute("src");
        }
        lightbox.querySelector(".wati-lightbox-close").addEventListener("click", closeLightbox);
        lightbox.addEventListener("click", (event) => {
            if (event.target === lightbox) closeLightbox();
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && lightbox.classList.contains("open")) closeLightbox();
        });

        function parseServerDate(value) {
            if (!value) return null;
            const normalized = value.includes("T") ? value : value.replace(" ", "T") + "Z";
            const parsed = new Date(normalized);
            return Number.isNaN(parsed.getTime()) ? null : parsed;
        }
        function dayKey(value) {
            const date = parseServerDate(value);
            if (!date) return "";
            return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
        }
        function dayLabel(value) {
            const date = parseServerDate(value);
            if (!date) return "";
            const today = new Date();
            const yesterday = new Date(today);
            yesterday.setDate(today.getDate() - 1);
            if (date.toDateString() === today.toDateString()) return "اليوم";
            if (date.toDateString() === yesterday.toDateString()) return "أمس";
            return new Intl.DateTimeFormat("ar-SA", { day: "numeric", month: "long", year: date.getFullYear() !== today.getFullYear() ? "numeric" : undefined }).format(date);
        }
        function audioTime(seconds) {
            if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
            const minutes = Math.floor(seconds / 60);
            const rest = Math.floor(seconds % 60).toString().padStart(2, "0");
            return `${minutes}:${rest}`;
        }

        function enhanceVoicePlayers() {
            messageList.querySelectorAll(".wati-media-content audio:not([data-ui-voice])").forEach((audio) => {
                audio.dataset.uiVoice = "1";
                audio.classList.add("wati-native-audio-hidden");
                const ui = document.createElement("div");
                ui.className = "wati-voice-ui";
                const play = document.createElement("button");
                play.type = "button";
                play.className = "wati-voice-play";
                play.textContent = "▶";
                const track = document.createElement("div");
                track.className = "wati-voice-track";
                const progress = document.createElement("span");
                progress.className = "wati-voice-progress";
                track.appendChild(progress);
                const time = document.createElement("span");
                time.className = "wati-voice-time";
                time.textContent = "0:00";
                ui.append(play, track, time);
                audio.insertAdjacentElement("afterend", ui);

                function sync() {
                    const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
                    const current = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
                    progress.style.width = duration ? `${Math.min(100, (current / duration) * 100)}%` : "0%";
                    time.textContent = audio.paused && current === 0 ? audioTime(duration) : audioTime(current);
                    play.textContent = audio.paused ? "▶" : "❚❚";
                }
                play.addEventListener("click", () => {
                    document.querySelectorAll("audio[data-ui-voice]").forEach((other) => {
                        if (other !== audio) other.pause();
                    });
                    if (audio.paused) audio.play().catch(() => {});
                    else audio.pause();
                });
                track.addEventListener("click", (event) => {
                    if (!Number.isFinite(audio.duration) || !audio.duration) return;
                    const rect = track.getBoundingClientRect();
                    audio.currentTime = Math.max(0, Math.min(audio.duration, ((event.clientX - rect.left) / rect.width) * audio.duration));
                    sync();
                });
                audio.addEventListener("loadedmetadata", sync);
                audio.addEventListener("timeupdate", sync);
                audio.addEventListener("play", sync);
                audio.addEventListener("pause", sync);
                audio.addEventListener("ended", sync);
                sync();
            });
        }

        function normalizeDocuments() {
            messageList.querySelectorAll(".wati-media-document").forEach((link) => {
                const strong = link.querySelector("strong");
                const bubble = link.closest(".wati-bubble");
                if (!strong || !bubble) return;
                const textNode = Array.from(bubble.children).find((node) =>
                    node !== link.parentElement &&
                    !node.classList?.contains("wati-bubble-meta") &&
                    !node.classList?.contains("wati-media-content") &&
                    !node.classList?.contains("wati-bubble-actions")
                );
                const rawText = String(textNode?.textContent || "").trim();
                const technical = String(strong.textContent || "").trim().toLowerCase();
                if (technical === "showfile" || technical === "file") {
                    if (/\.(pdf|docx?|xlsx?|pptx?|txt)$/i.test(rawText)) {
                        strong.textContent = rawText;
                        if (textNode) textNode.style.display = "none";
                    } else {
                        strong.textContent = "ملف مرفق";
                    }
                } else if (rawText && rawText === strong.textContent) {
                    if (textNode) textNode.style.display = "none";
                }
            });
        }

        function addBubbleActions() {
            messageList.querySelectorAll(".wati-message-row").forEach((row) => {
                const bubble = row.querySelector(".wati-bubble");
                if (!bubble || bubble.querySelector(".wati-bubble-actions")) return;
                const actions = document.createElement("div");
                actions.className = "wati-bubble-actions";
                const toggle = document.createElement("button");
                toggle.type = "button";
                toggle.className = "wati-bubble-menu-button";
                toggle.textContent = "⋮";
                toggle.title = "خيارات الرسالة";
                const menu = document.createElement("div");
                menu.className = "wati-bubble-menu";
                const copy = document.createElement("button");
                copy.type = "button";
                copy.textContent = "نسخ النص";
                copy.addEventListener("click", async () => {
                    const textParts = Array.from(bubble.children)
                        .filter((node) => !node.classList?.contains("wati-bubble-meta") && !node.classList?.contains("wati-media-content") && !node.classList?.contains("wati-bubble-actions"))
                        .map((node) => String(node.textContent || "").trim())
                        .filter(Boolean);
                    const text = textParts.join("\n");
                    if (text) {
                        try { await navigator.clipboard.writeText(text); } catch (_) {}
                    }
                    actions.classList.remove("open");
                });
                menu.appendChild(copy);
                const mediaLink = bubble.querySelector(".wati-media-content a[href]");
                if (mediaLink) {
                    const open = document.createElement("a");
                    open.href = mediaLink.href;
                    open.target = "_blank";
                    open.rel = "noopener";
                    open.textContent = "فتح المرفق";
                    menu.appendChild(open);
                }
                toggle.addEventListener("click", (event) => {
                    event.stopPropagation();
                    document.querySelectorAll(".wati-bubble-actions.open").forEach((item) => {
                        if (item !== actions) item.classList.remove("open");
                    });
                    actions.classList.toggle("open");
                });
                actions.append(toggle, menu);
                bubble.appendChild(actions);
            });
        }

        function enhanceConversationRows(conversations) {
            const byId = new Map((Array.isArray(conversations) ? conversations : []).map((item) => [Number(item.id), item]));
            conversationList.querySelectorAll(".wati-conversation[data-conversation-id]").forEach((button) => {
                const item = byId.get(Number(button.dataset.conversationId));
                if (!item) return;
                const main = button.querySelector(".wati-conversation-main");
                if (!main) return;
                let badge = main.querySelector(".wati-assignee-mini");
                if (!item.assigned_user_name) {
                    if (badge) badge.remove();
                    return;
                }
                if (!badge) {
                    badge = document.createElement("span");
                    badge.className = "wati-assignee-mini";
                    main.appendChild(badge);
                }
                badge.classList.toggle("mine", Boolean(item.assigned_to_me));
                badge.textContent = item.assigned_to_me ? "عندي" : item.assigned_user_name;
            });
        }

        function enhanceMessageRows(messages, unreadCount) {
            const rows = Array.from(messageList.querySelectorAll(".wati-message-row"));
            if (!rows.length || !Array.isArray(messages)) return;
            messageList.querySelectorAll(".wati-day-separator,.wati-unread-divider").forEach((node) => node.remove());

            let previousDay = "";
            rows.forEach((row, index) => {
                const message = messages[index];
                if (!message) return;
                const key = dayKey(message.received_at);
                if (key && key !== previousDay) {
                    const separator = document.createElement("div");
                    separator.className = "wati-day-separator";
                    const label = document.createElement("span");
                    label.textContent = dayLabel(message.received_at);
                    separator.appendChild(label);
                    row.before(separator);
                    previousDay = key;
                }
            });

            const unread = Math.max(0, Number(unreadCount || 0));
            if (unread) {
                const inboundIndices = [];
                messages.forEach((message, index) => {
                    if (message && message.direction !== "outbound") inboundIndices.push(index);
                });
                if (inboundIndices.length) {
                    const firstUnreadIndex = inboundIndices[Math.max(0, inboundIndices.length - unread)];
                    const target = rows[firstUnreadIndex];
                    if (target) {
                        const divider = document.createElement("div");
                        divider.className = "wati-unread-divider";
                        divider.textContent = `${Math.min(unread, inboundIndices.length)} رسائل غير مقروءة`;
                        target.before(divider);
                    }
                }
            }

            enhanceVoicePlayers();
            normalizeDocuments();
            addBubbleActions();
            updateScrollButton();
        }

        let metaLoading = false;
        let metaTimer = null;
        let lastMetaAt = 0;
        async function refreshUiMeta(force = false) {
            const selectedId = Number(localStorage.getItem("watiInboxSelected") || 0);
            if (!selectedId || metaLoading) return;
            const now = Date.now();
            if (!force && now - lastMetaAt < 1200) return;
            metaLoading = true;
            try {
                const response = await fetch(`/wati/inbox/data?conversation_id=${encodeURIComponent(selectedId)}`, {
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                    cache: "no-store",
                });
                if (!response.ok) return;
                const payload = await response.json();
                if (!payload.ok) return;
                const selected = (payload.conversations || []).find((item) => Number(item.id) === Number(payload.selected_id));
                enhanceConversationRows(payload.conversations || []);
                enhanceMessageRows(payload.messages || [], selected?.unread_count || 0);
                lastMetaAt = Date.now();
            } catch (error) {
                console.debug("WATI UI polish metadata skipped", error);
            } finally {
                metaLoading = false;
            }
        }
        function scheduleUiMeta(force = false) {
            window.clearTimeout(metaTimer);
            metaTimer = window.setTimeout(() => refreshUiMeta(force), 100);
        }

        const messageObserver = new MutationObserver(() => {
            const currentRows = messageList.querySelectorAll(".wati-message-row").length;
            if (currentRows > previousRows && !userNearBottom) pendingNew += currentRows - previousRows;
            previousRows = currentRows;
            messageList.classList.remove("ui-switching");
            enhanceVoicePlayers();
            normalizeDocuments();
            addBubbleActions();
            scheduleUiMeta(false);
            updateScrollButton();
        });
        messageObserver.observe(messageList, { childList: true, subtree: true });

        const conversationObserver = new MutationObserver(() => scheduleUiMeta(false));
        conversationObserver.observe(conversationList, { childList: true, subtree: true });

        conversationList.addEventListener("click", (event) => {
            const button = event.target.closest(".wati-conversation[data-conversation-id]");
            if (!button) return;
            messageList.classList.add("ui-switching");
            pendingNew = 0;
            window.setTimeout(() => messageList.classList.remove("ui-switching"), 900);
            window.setTimeout(() => scheduleUiMeta(true), 150);
        }, true);

        messageList.addEventListener("click", (event) => {
            const image = event.target.closest(".wati-media-content img");
            if (image && image.src) {
                event.preventDefault();
                lightboxImg.src = image.src;
                lightbox.classList.add("open");
            }
        });
        document.addEventListener("click", () => {
            document.querySelectorAll(".wati-bubble-actions.open").forEach((item) => item.classList.remove("open"));
        });

        // Keep the composer comfortably small while still allowing multi-line replies.
        messageInput.addEventListener("input", () => {
            messageInput.style.height = "auto";
            messageInput.style.height = `${Math.min(messageInput.scrollHeight, 128)}px`;
        });

        enhanceVoicePlayers();
        normalizeDocuments();
        addBubbleActions();
        scheduleUiMeta(true);
        updateScrollButton();
    } catch (error) {
        // This file is intentionally an optional enhancement layer. If it fails,
        // the stable WATI inbox underneath must continue to work normally.
        console.error("WATI UI polish disabled safely", error);
    }
})();
