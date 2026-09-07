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
  overlay.innerHTML = `<div class="wati-ib-modal"><div class="wati-ib-head"><div><strong>رسالة تفاعلية</strong><span>1 إلى 3 أزرار WhatsApp</span></div><button class="wati-ib-close" type="button">×</button></div><div class="wati-ib-grid"><div class="wati-ib-form"><label>العنوان <small>اختياري · 60</small><input class="ib-header" maxlength="60" placeholder="مثال: تأكيد الموعد"/></label><label>نص الرسالة <small>مطلوب · 1024</small><textarea class="ib-body" maxlength="1024" rows="5" placeholder="اكتب الرسالة..."></textarea></label><label>التذييل <small>اختياري · 60</small><input class="ib-footer" maxlength="60" placeholder="مثال: بيت الإباء"/></label><div class="wati-ib-buttons"><div><strong>الأزرار</strong><small>20 حرفًا لكل زر</small></div><input class="ib-btn" maxlength="20" placeholder="زر 1"/><input class="ib-btn" maxlength="20" placeholder="زر 2 (اختياري)"/><input class="ib-btn" maxlength="20" placeholder="زر 3 (اختياري)"/></div></div><aside class="wati-ib-preview"><span>معاينة</span><div class="wati-ib-bubble"><strong class="ib-ph"></strong><div class="ib-pb">اكتب نص الرسالة...</div><small class="ib-pf"></small><div class="ib-pbuttons"></div></div></aside></div><div class="wati-ib-actions"><button class="wati-ib-cancel" type="button">إلغاء</button><button class="wati-ib-send" type="button">إرسال الرسالة</button></div></div>`;
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
    q(".ib-pb").textContent = b || "اكتب نص الرسالة...";
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
      return notify("اختر محادثة أولًا.", true);
    }
    if (input.disabled) return notify("استلم المحادثة أولًا.", true);
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
    if (!body.value.trim()) return notify("اكتب نص الرسالة أولًا.", true);
    if (values.length < 1 || values.length > 3) return notify("أضف من زر واحد إلى 3 أزرار.", true);
    if (new Set(values.map((value) => value.toLowerCase())).size !== values.length) {
      return notify("اجعل نص كل زر مختلفًا.", true);
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
    send.textContent = "جاري الإرسال...";
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
      if (!response.ok || !payload.ok) throw new Error(payload.message || `فشل الإرسال (${response.status})`);
      overlay.classList.add("is-hidden");
      notify("تم قبول الرسالة التفاعلية في WATI ✅");
      const refresh = document.getElementById("refreshButton");
      window.setTimeout(() => refresh?.click(), 900);
      window.setTimeout(() => refresh?.click(), 2300);
    } catch (error) {
      notify(error.message || "تعذر إرسال الرسالة التفاعلية.", true);
    } finally {
      sending = false;
      send.disabled = false;
      send.textContent = "إرسال الرسالة";
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
