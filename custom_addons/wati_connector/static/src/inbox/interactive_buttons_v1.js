(() => {
  "use strict";

  const app = document.getElementById("watiInboxApp");
  const input = document.getElementById("messageInput");
  const toast = document.getElementById("watiToast");
  if (!app || !input) return;

  const csrf = app.dataset.csrf || "";
  let sending = false;
  let timer = null;

  const overlay = document.createElement("div");
  overlay.className = "wati-ib-overlay is-hidden";
  overlay.innerHTML = `<div class="wati-ib-modal"><div class="wati-ib-head"><div><strong>Interactive message</strong><span>1 To 3 Buttons WhatsApp</span></div><button class="wati-ib-close" type="button">×</button></div><div class="wati-ib-grid"><div class="wati-ib-form"><label>Address <small>Optional · 60</small><input class="ib-header" maxlength="60" placeholder="Example: Confirm appointment"/></label><label>Message text <small>Wanted · 1024</small><textarea class="ib-body" maxlength="1024" rows="5" placeholder="Write the message..."></textarea></label><label>Footer <small>Optional · 60</small><input class="ib-footer" maxlength="60" placeholder="Example: The house of fathers"/></label><div class="wati-ib-buttons"><div><strong>Buttons</strong><small>20 A letter for each button</small></div><input class="ib-btn" maxlength="20" placeholder="button 1"/><input class="ib-btn" maxlength="20" placeholder="button 2 (Optional)"/><input class="ib-btn" maxlength="20" placeholder="button 3 (Optional)"/></div></div><aside class="wati-ib-preview"><span>Preview</span><div class="wati-ib-bubble"><strong class="ib-ph"></strong><div class="ib-pb">Type the message text...</div><small class="ib-pf"></small><div class="ib-pbuttons"></div></div></aside></div><div class="wati-ib-actions"><button class="wati-ib-cancel" type="button">Cancel</button><button class="wati-ib-send" type="button">Send message</button></div></div>`;
  document.body.appendChild(overlay);

  const q = (selector) => overlay.querySelector(selector);
  const qa = (selector) => Array.from(overlay.querySelectorAll(selector));
  const header = q(".ib-header");
  const body = q(".ib-body");
  const footer = q(".ib-footer");
  const send = q(".wati-ib-send");

  function notify(message, error = false) {
    if (!toast) {
      if (error) window.alert(message);
      return;
    }
    toast.textContent = message;
    toast.classList.toggle("error", error);
    toast.classList.add("show");
    window.clearTimeout(timer);
    timer = window.setTimeout(() => toast.classList.remove("show"), 3500);
  }

  function requestId() {
    return window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function buttons() {
    return qa(".ib-btn").map((element) => element.value.trim()).filter(Boolean);
  }

  function preview() {
    const h = header.value.trim();
    const b = body.value.trim();
    const f = footer.value.trim();
    q(".ib-ph").textContent = h;
    q(".ib-ph").style.display = h ? "block" : "none";
    q(".ib-pb").textContent = b || "Type the message text...";
    q(".ib-pf").textContent = f;
    q(".ib-pf").style.display = f ? "block" : "none";
    const box = q(".ib-pbuttons");
    box.replaceChildren();
    buttons().forEach((text) => {
      const element = document.createElement("div");
      element.textContent = text;
      box.appendChild(element);
    });
  }

  function open() {
    if (!Number(localStorage.getItem("watiInboxSelected") || 0)) {
      return notify("Choose a conversation first.", true);
    }
    if (input.disabled) return notify("Receive the conversation first.", true);
    header.value = "";
    body.value = "";
    footer.value = "";
    qa(".ib-btn").forEach((element) => { element.value = ""; });
    preview();
    overlay.classList.remove("is-hidden");
    window.setTimeout(() => body.focus(), 40);
  }

  function close() {
    if (!sending) overlay.classList.add("is-hidden");
  }

  async function submit() {
    if (sending) return;
    const values = buttons();
    if (!body.value.trim()) return notify("Write the body of the message first.", true);
    if (values.length < 1 || values.length > 3) return notify("Add from one button to 3 Buttons.", true);
    if (new Set(values.map((value) => value.toLowerCase())).size !== values.length) {
      return notify("Make each button’s text different.", true);
    }

    const conversationId = Number(localStorage.getItem("watiInboxSelected") || 0);
    const form = new URLSearchParams({
      csrf_token: csrf,
      conversation_id: String(conversationId),
      header: header.value.trim(),
      body: body.value.trim(),
      footer: footer.value.trim(),
      buttons_json: JSON.stringify(values.map((text) => ({ text }))),
      request_id: requestId(),
    });

    sending = true;
    send.disabled = true;
    send.textContent = "Sending...";
    try {
      const response = await fetch("/wati/inbox/send-buttons", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          Accept: "application/json",
        },
        body: form.toString(),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) throw new Error(payload.message || `Transmission failed (${response.status})`);
      overlay.classList.add("is-hidden");
      notify("Interactive message accepted in WATI ✅");
      const refresh = document.getElementById("refreshButton");
      window.setTimeout(() => refresh?.click(), 900);
      window.setTimeout(() => refresh?.click(), 2300);
    } catch (error) {
      notify(error.message || "The interactive message could not be sent.", true);
    } finally {
      sending = false;
      send.disabled = false;
      send.textContent = "Send message";
    }
  }

  [header, body, footer, ...qa(".ib-btn")].forEach((element) => element.addEventListener("input", preview));
  q(".wati-ib-close").addEventListener("click", close);
  q(".wati-ib-cancel").addEventListener("click", close);
  send.addEventListener("click", submit);
  overlay.addEventListener("click", (event) => { if (event.target === overlay) close(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") close(); });
  document.addEventListener("wati:open-interactive-buttons", open);
})();
