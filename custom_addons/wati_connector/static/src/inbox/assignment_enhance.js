(() => {
    "use strict";

    const app = document.getElementById("watiInboxApp");
    const actions = document.querySelector(".wati-chat-actions");
    const messageInput = document.getElementById("messageInput");
    const sendButton = document.getElementById("sendButton");
    if (!app || !actions) return;

    const csrfToken = app.dataset.csrf || "";
    const box = document.createElement("div");
    box.style.display = "flex";
    box.style.alignItems = "center";
    box.style.gap = "8px";
    box.style.flexWrap = "wrap";
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
        }
        if (sendButton) sendButton.disabled = !enabled;
    }

    function makeButton(text, disabled = false, variant = "primary") {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = text;
        button.disabled = disabled;
        button.style.border = variant === "takeover" ? "1px solid #f59e0b" : "1px solid #d9e2e8";
        button.style.background = disabled ? "#f3f6f8" : (variant === "takeover" ? "#fff7ed" : "#16a34a");
        button.style.color = disabled ? "#52606d" : (variant === "takeover" ? "#b45309" : "white");
        button.style.borderRadius = "10px";
        button.style.padding = "8px 12px";
        button.style.fontWeight = "700";
        button.style.cursor = disabled ? "default" : "pointer";
        return button;
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
            await refreshAssignment(true);
            window.setTimeout(() => window.location.reload(), 250);
        } catch (error) {
            window.alert(error.message || "تعذر استلام المحادثة.");
        } finally {
            busy = false;
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
            ]);
            if (forceRender || lastConversationId !== id || box.dataset.state !== signature) {
                lastConversationId = id;
                box.dataset.state = signature;
                box.replaceChildren();

                if (!data.wati_email) {
                    const badge = makeButton("⚠ أضف بريد WATI لحسابك", true);
                    box.appendChild(badge);
                    setComposerEnabled(false, "أضف WATI Operator Email في حساب المستخدم...");
                    return;
                }

                if (data.assigned_to_me) {
                    box.appendChild(makeButton(`✓ عندي — ${data.current_user_name}`, true));
                    setComposerEnabled(true);
                } else if (data.is_unassigned) {
                    const button = makeButton("استلام المحادثة");
                    button.addEventListener("click", () => assignMe(false));
                    box.appendChild(button);
                    setComposerEnabled(false, "استلم المحادثة أولًا...");
                } else {
                    const badge = makeButton(`عند ${data.assigned_user_name}`, true);
                    box.appendChild(badge);
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
