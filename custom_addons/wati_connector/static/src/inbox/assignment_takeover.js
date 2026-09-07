(() => {
    "use strict";

    const app = document.getElementById("watiInboxApp");
    const badge = document.getElementById("assignmentBadge");
    const statusValue = document.getElementById("drawerAssignmentStatus");
    const assignedUserValue = document.getElementById("drawerAssignedUser");
    const actionBox = document.getElementById("drawerAssignmentAction");
    const messageInput = document.getElementById("messageInput");
    const sendButton = document.getElementById("sendButton");
    const refreshButton = document.getElementById("refreshButton");
    if (!app || !badge || !statusValue || !assignedUserValue || !actionBox) return;

    const csrfToken = app.dataset.csrf || "";
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

    function setBadge(text, variant = "unassigned", title = "") {
        badge.textContent = text;
        badge.className = `wati-assignment-badge is-${variant}`;
        badge.title = title || text;
    }

    function makeActionButton(text, onClick, variant = "primary", disabled = false) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = text;
        button.disabled = disabled;
        button.className = variant === "takeover"
            ? "wati-actions-secondary is-takeover"
            : (variant === "secondary" ? "wati-actions-secondary" : "wati-actions-primary");
        if (onClick && !disabled) button.addEventListener("click", onClick);
        return button;
    }

    function refreshInboxData() {
        if (refreshButton && !refreshButton.disabled) refreshButton.click();
    }

    function renderEmptyState() {
        setBadge("اختر محادثة", "unassigned");
        statusValue.textContent = "لم يتم اختيار محادثة";
        assignedUserValue.textContent = "—";
        actionBox.replaceChildren();
        setComposerEnabled(false, "اختر محادثة أولًا...");
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
        actionBox.classList.add("is-busy");
        const currentButton = actionBox.querySelector("button");
        if (currentButton) currentButton.disabled = true;
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
            setComposerEnabled(true);
            refreshInboxData();
            window.setTimeout(refreshInboxData, 500);
            if (messageInput) window.setTimeout(() => messageInput.focus(), 80);
        } catch (error) {
            window.alert(error.message || "تعذر استلام المحادثة.");
            await refreshAssignment(true);
        } finally {
            busy = false;
            actionBox.classList.remove("is-busy");
        }
    }

    function renderAssignment(data) {
        actionBox.replaceChildren();

        if (!data.wati_email) {
            setBadge("إعداد مطلوب", "warning", "أضف WATI Operator Email لحساب المستخدم");
            statusValue.textContent = "بريد WATI غير مضبوط";
            assignedUserValue.textContent = data.current_user_name || "—";
            actionBox.appendChild(makeActionButton("أضف بريد WATI لحساب المستخدم", null, "secondary", true));
            setComposerEnabled(false, "أضف WATI Operator Email في حساب المستخدم...");
            return;
        }

        if (data.assigned_to_me) {
            setBadge("✓ مسندة لي", "mine", `المحادثة مسندة إلى ${data.current_user_name || "حسابك"}`);
            statusValue.textContent = "مسندة إليك";
            assignedUserValue.textContent = data.current_user_name || "—";
            setComposerEnabled(true);
            return;
        }

        if (data.is_unassigned) {
            setBadge("غير مسندة", "unassigned");
            statusValue.textContent = "غير مسندة";
            assignedUserValue.textContent = "—";
            actionBox.appendChild(makeActionButton("استلام المحادثة", () => assignMe(false)));
            setComposerEnabled(false, "استلم المحادثة أولًا...");
            return;
        }

        setBadge("مسندة لموظف", "other", `المحادثة عند ${data.assigned_user_name || "موظف آخر"}`);
        statusValue.textContent = "مسندة لموظف آخر";
        assignedUserValue.textContent = data.assigned_user_name || "—";
        if (data.can_takeover) {
            actionBox.appendChild(
                makeActionButton(
                    "نقل المحادثة إليّ",
                    () => assignMe(true, data.assigned_user_name),
                    "takeover"
                )
            );
        }
        setComposerEnabled(false, `المحادثة عند ${data.assigned_user_name || "موظف آخر"}`);
    }

    async function refreshAssignment(forceRender = false) {
        const id = selectedId();
        if (!id) {
            renderEmptyState();
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
            if (forceRender || lastConversationId !== id || badge.dataset.state !== signature) {
                lastConversationId = id;
                badge.dataset.state = signature;
                renderAssignment(data);
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
