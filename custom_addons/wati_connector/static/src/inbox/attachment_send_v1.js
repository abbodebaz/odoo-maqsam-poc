(() => {
    "use strict";

    const app = document.getElementById("watiInboxApp");
    const form = document.getElementById("messageForm");
    const input = document.getElementById("messageInput");
    const sendButton = document.getElementById("sendButton");
    const refreshButton = document.getElementById("refreshButton");
    const toast = document.getElementById("watiToast");
    if (!app || !form || !input || !sendButton) return;

    const csrfToken = app.dataset.csrf || "";
    let selectedFile = null;
    let uploading = false;
    let toastTimer = null;

    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.hidden = true;
    fileInput.accept = ".jpg,.jpeg,.png,.mp4,.3gp,.3gpp,.aac,.m4a,.mp3,.amr,.ogg,.opus,.txt,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,image/jpeg,image/png,video/mp4,video/3gpp,audio/*,application/pdf";

    const attachButton = document.createElement("button");
    attachButton.type = "button";
    attachButton.className = "wati-attach-button";
    attachButton.title = "Attach a photo or file";
    attachButton.setAttribute("aria-label", "Attach file");
    attachButton.textContent = "📎";

    const preview = document.createElement("div");
    preview.className = "wati-attachment-preview is-hidden";

    const previewIcon = document.createElement("span");
    previewIcon.className = "wati-attachment-preview-icon";
    previewIcon.textContent = "📎";

    const previewInfo = document.createElement("div");
    previewInfo.className = "wati-attachment-preview-info";
    const previewName = document.createElement("strong");
    const previewSize = document.createElement("span");
    previewInfo.append(previewName, previewSize);

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "wati-attachment-remove";
    removeButton.title = "Remove attachment";
    removeButton.textContent = "×";

    preview.append(previewIcon, previewInfo, removeButton);
    form.parentNode.insertBefore(preview, form);
    form.insertBefore(attachButton, input);
    form.appendChild(fileInput);

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

    function formatBytes(bytes) {
        if (!Number.isFinite(bytes) || bytes <= 0) return "";
        if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(bytes >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
    }

    function extension(filename) {
        const name = String(filename || "").toLowerCase();
        const index = name.lastIndexOf(".");
        return index >= 0 ? name.slice(index) : "";
    }

    function categoryFor(file) {
        const type = String(file.type || "").toLowerCase();
        const ext = extension(file.name);
        if (type === "image/jpeg" || type === "image/png" || [".jpg", ".jpeg", ".png"].includes(ext)) return "image";
        if (type === "video/mp4" || type === "video/3gpp" || [".mp4", ".3gp", ".3gpp"].includes(ext)) return "video";
        if (type.startsWith("audio/") || [".aac", ".m4a", ".mp3", ".amr", ".ogg", ".opus"].includes(ext)) return "audio";
        if ([".txt", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"].includes(ext)) return "document";
        return "";
    }

    function validateFile(file) {
        const category = categoryFor(file);
        if (!category) return "The file type is not supported in WATI.";
        const limits = {
            image: 5 * 1024 * 1024,
            video: 16 * 1024 * 1024,
            audio: 16 * 1024 * 1024,
            document: 100 * 1024 * 1024,
        };
        if (file.size > limits[category]) {
            return `The file size is larger than the allowed limit (${limits[category] / (1024 * 1024)} MB).`;
        }
        return "";
    }

    function requestId() {
        if (window.crypto && typeof window.crypto.randomUUID === "function") return window.crypto.randomUUID();
        return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function clearAttachment({ keepCaption = false } = {}) {
        selectedFile = null;
        fileInput.value = "";
        preview.classList.add("is-hidden");
        previewName.textContent = "";
        previewSize.textContent = "";
        input.required = true;
        input.maxLength = 4096;
        input.placeholder = input.disabled ? input.placeholder : "Write a message...";
        if (!keepCaption) input.value = "";
        if (!sendButton.disabled) sendButton.innerHTML = "Send <span>➤</span>";
    }

    function selectFile(file) {
        const error = validateFile(file);
        if (error) {
            showToast(error, true);
            fileInput.value = "";
            return;
        }
        selectedFile = file;
        input.required = false;
        input.maxLength = 1024;
        if (!input.disabled) input.placeholder = "Add an optional comment to the attachment...";
        previewName.textContent = file.name;
        previewSize.textContent = `${formatBytes(file.size)} · ${categoryFor(file)}`;
        preview.classList.remove("is-hidden");
        if (!sendButton.disabled) sendButton.innerHTML = "Send attachment <span>➤</span>";
        input.focus();
    }

    async function sendAttachment(event) {
        if (!selectedFile) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        if (uploading) return;
        if (input.disabled || sendButton.disabled) {
            showToast("Receive the chat first before sending an attachment.", true);
            return;
        }

        const conversationId = Number(localStorage.getItem("watiInboxSelected") || 0);
        if (!conversationId) {
            showToast("Choose a conversation first.", true);
            return;
        }

        uploading = true;
        attachButton.disabled = true;
        sendButton.disabled = true;
        sendButton.textContent = "File is being sent...";

        const body = new FormData();
        body.append("csrf_token", csrfToken);
        body.append("conversation_id", String(conversationId));
        body.append("request_id", requestId());
        body.append("caption", input.value.trim());
        body.append("file", selectedFile, selectedFile.name);

        try {
            const response = await fetch("/wati/inbox/send-file", {
                method: "POST",
                credentials: "same-origin",
                headers: { Accept: "application/json" },
                body,
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload.ok) throw new Error(payload.message || `Failed to send attachment (${response.status})`);

            clearAttachment();
            showToast("The attachment has been sent to WATI ✅");
            window.setTimeout(() => refreshButton && refreshButton.click(), 800);
            window.setTimeout(() => refreshButton && refreshButton.click(), 2200);
        } catch (error) {
            console.error("WATI attachment send error", error);
            showToast(error.message || "The attachment could not be sent.", true);
        } finally {
            uploading = false;
            sendButton.disabled = input.disabled;
            attachButton.disabled = input.disabled;
            if (selectedFile) sendButton.innerHTML = "Send attachment <span>➤</span>";
            else sendButton.innerHTML = "Send <span>➤</span>";
        }
    }

    attachButton.addEventListener("click", () => {
        if (input.disabled || sendButton.disabled) {
            showToast("Receive the chat first before sending an attachment.", true);
            return;
        }
        fileInput.click();
    });

    fileInput.addEventListener("change", () => {
        const file = fileInput.files && fileInput.files[0];
        if (file) selectFile(file);
    });

    removeButton.addEventListener("click", () => clearAttachment({ keepCaption: true }));
    form.addEventListener("submit", sendAttachment, true);

    // Keep the attachment control in sync with the assignment module, which
    // enables/disables the text composer based on conversation ownership.
    window.setInterval(() => {
        if (uploading) return;
        attachButton.disabled = input.disabled;
        if (selectedFile && !sendButton.disabled) sendButton.innerHTML = "Send attachment <span>➤</span>";
    }, 500);
})();
