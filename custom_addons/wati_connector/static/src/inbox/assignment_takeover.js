(() => {
    "use strict";

    const app = document.getElementById("watiInboxApp");
    const actions = document.querySelector(".wati-chat-actions");
    const messageInput = document.getElementById("messageInput");
    const sendButton = document.getElementById("sendButton");
    const refreshButton = document.getElementById("refreshButton");
    if (!app || !actions) return;

    const csrfToken = app.dataset.csrf || "";
    const box = document.createElement("div");
    box.className = "wati-assignment-box";
    actions.prepend(box);

    let lastConversationId = 0;
    let busy = false;

    function selectedId() {
        return Number(localStorage.getItem("watiInboxSelected") || 0);
    }

    function setComposerEnabled(enabled, note) {
        if (messageInput) {
            messageInput.disabled = !enabled;
            messageInput.placeholder = enabled ? "اكتب رسالة..." : (note || "استلم المحادثة أولًا...");
            messageInput.setAttribute("aria-disabled", enabled ? "false" : "true");
        }
        if (sendButton) {
            sendButton.disabled = !enabled;
            sendButton.setAttribute("aria-disabled", enabled ? "false" : "true");
        }
    }

    function makeButton(text, disabled = false, variant = "primary") {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = text;
        button.disabled = disabled;
        button.className = `wati-assignment-button ${variant === "takeover" ? "is-takeover" : "is-primary"}${disabled ? " is-disabled" : ""}`;
        return button;
    }

    function refreshInboxData() {
        // Reuse the Inbox's own refresh pipeline instead of reloading the page.
        // A full reload used to race with the toolbar enhancement scripts and
        // could leave the composer disabled or wider than the chat viewport.
        if (refreshButton && !refreshButton.disabled) {
            refreshButton.click();
        }
    }

    async function assignMe(force = false, previousUserName = "") {
        const id = selectedId();
        if (!id || busy) return;

        if (force) {
            const confirmed = window.confirm(
                `المحادثة حاليًا عند ${previousUserName || "موظف آخر"}.\n\nهل تريد نقلها إليك؟`
            );
            if (!confirmed) return;
        }

        busy = true;
        box.classList.add("is-busy");
        try {
            const body = new URLSearchParams({
                csrf_token: csrfToken,
                conversation_id: String(id),
                force: force ? "1" : "0",
            });
            const response = await fetch("/wati/inbox/assign-me", {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    Accept: "application/json",
                },
                body: body.toString(),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) throw new Error(payload.message || "تعذر استلام المحادثة");

            // Update ownership and composer in-place. No window.location.reload().
            await refreshAssignment(true);
            setComposerEnabled(true);
            refreshInboxData();
            window.setTimeout(refreshInboxData, 500);
            if (messageInput) window.setTimeout(() => messageInput.focus(), 80);
        } catch (error) {
            window.alert(error.message || "تعذر استلام المحادثة.");
            await refreshAssignment(true);
        } finally {
            busy = false;
            box.classList.remove("is-busy");
        }
    }

    async function refreshAssignment(forceRender = false) {
        const id = selectedId();
        if (!id) {
            box.replaceChildren();
            setComposerEnabled(false, "اختر محادثة أولًا...");
            lastConversationId = 0;
            return;
        }
        try {
            const response = await fetch(`/wati/inbox/assignment?conversation_id=${encodeURIComponent(id)}`, {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
                cache: "no-store",
            });
            if (!response.ok) return;
            const data = await response.json();
            if (!data.ok) return;

            const signature = JSON.stringify([
                data.assigned_user_id,
                data.assigned_to_me,
                data.wati_email,
                data.can_takeover,
                data.assigned_user_name,
                data.current_user_name,
            ]);
            if (forceRender || lastConversationId !== id || box.dataset.state !== signature) {
                lastConversationId = id;
                box.dataset.state = signature;
                box.replaceChildren();

                if (!data.wati_email) {
                    box.appendChild(makeButton("⚠ أضف بريد WATI لحسابك", true));
                    setComposerEnabled(false, "أضف WATI Operator Email في حساب المستخدم...");
                    return;
                }

                if (data.assigned_to_me) {
                    const mine = makeButton(`✓ عندي — ${data.current_user_name}`, true);
                    mine.title = `المحادثة مسندة إلى ${data.current_user_name}`;
                    box.appendChild(mine);
                    setComposerEnabled(true);
                } else if (data.is_unassigned) {
                    const button = makeButton("استلام المحادثة");
                    button.addEventListener("click", () => assignMe(false));
                    box.appendChild(button);
                    setComposerEnabled(false, "استلم المحادثة أولًا...");
                } else {
                    const owner = makeButton(`عند ${data.assigned_user_name}`, true);
                    owner.title = `المحادثة مسندة إلى ${data.assigned_user_name}`;
                    box.appendChild(owner);
                    if (data.can_takeover) {
                        const button = makeButton("أخذ المحادثة", false, "takeover");
                        button.title = `نقل المحادثة من ${data.assigned_user_name} إليك`;
                        button.addEventListener("click", () => assignMe(true, data.assigned_user_name));
                        box.appendChild(button);
                    }
                    setComposerEnabled(false, `المحادثة عند ${data.assigned_user_name}`);
                }
            }
        } catch (error) {
            console.error("WATI assignment state error", error);
        }
    }

    window.setInterval(refreshAssignment, 2500);
    window.addEventListener("storage", refreshAssignment);
    document.addEventListener("click", () => window.setTimeout(refreshAssignment, 50));
    refreshAssignment(true);
})();
