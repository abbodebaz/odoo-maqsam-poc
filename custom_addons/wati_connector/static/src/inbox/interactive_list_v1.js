(() => {
  "use strict";

  const app = document.getElementById("watiInboxApp");
  const actions = document.querySelector(".wati-chat-actions");
  const input = document.getElementById("messageInput");
  const toast = document.getElementById("watiToast");
  if (!app || !actions || !input) return;

  const csrf = app.dataset.csrf || "";
  let sending = false;
  let toastTimer = null;

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "wati-list-trigger";
  trigger.innerHTML = '<span aria-hidden="true">☷</span><span>قائمة</span>';
  trigger.title = "إرسال قائمة تفاعلية";
  actions.prepend(trigger);

  const overlay = document.createElement("div");
  overlay.className = "wati-list-overlay is-hidden";
  overlay.innerHTML = `
    <div class="wati-list-modal" role="dialog" aria-modal="true" aria-label="قائمة WhatsApp تفاعلية">
      <div class="wati-list-head">
        <div><strong>قائمة تفاعلية</strong><span>حتى 10 خيارات موزعة على أقسام</span></div>
        <button class="wati-list-close" type="button" aria-label="إغلاق">×</button>
      </div>
      <div class="wati-list-layout">
        <div class="wati-list-form">
          <div class="wati-list-fields">
            <label>العنوان <small>اختياري · 60</small><input class="list-header" maxlength="60" placeholder="مثال: اختر الخدمة" /></label>
            <label class="wide">نص الرسالة <small>مطلوب · 1024</small><textarea class="list-body" maxlength="1024" rows="4" placeholder="اختر من القائمة أدناه..."></textarea></label>
            <label>نص زر القائمة <small>مطلوب · 20</small><input class="list-button-text" maxlength="20" value="عرض الخيارات" /></label>
            <label>التذييل <small>اختياري · 60</small><input class="list-footer" maxlength="60" placeholder="مثال: بيت الإباء" /></label>
          </div>
          <div class="wati-list-sections-head">
            <div><strong>الأقسام والخيارات</strong><span class="wati-list-counter">0 / 10 خيارات</span></div>
            <button class="wati-list-add-section" type="button">+ إضافة قسم</button>
          </div>
          <div class="wati-list-sections"></div>
        </div>
        <aside class="wati-list-preview">
          <span>معاينة</span>
          <div class="wati-list-preview-bubble">
            <strong class="list-preview-header"></strong>
            <div class="list-preview-body">اكتب نص الرسالة...</div>
            <small class="list-preview-footer"></small>
            <button type="button" class="list-preview-button">☷ عرض الخيارات</button>
            <div class="list-preview-options"></div>
          </div>
        </aside>
      </div>
      <div class="wati-list-actions">
        <button class="wati-list-cancel" type="button">إلغاء</button>
        <button class="wati-list-send" type="button">إرسال القائمة</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const q = (selector) => overlay.querySelector(selector);
  const header = q(".list-header");
  const body = q(".list-body");
  const footer = q(".list-footer");
  const buttonText = q(".list-button-text");
  const sectionsBox = q(".wati-list-sections");
  const counter = q(".wati-list-counter");
  const sendButton = q(".wati-list-send");

  function notify(message, error = false) {
    if (!toast) {
      if (error) window.alert(message);
      return;
    }
    toast.textContent = message;
    toast.classList.toggle("error", error);
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 3500);
  }

  function requestId() {
    return window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function totalRows() {
    return sectionsBox.querySelectorAll(".wati-list-row").length;
  }

  function updateCounter() {
    const count = totalRows();
    counter.textContent = `${count} / 10 خيارات`;
    counter.classList.toggle("limit", count >= 10);
  }

  function rowTemplate(title = "", description = "") {
    const row = document.createElement("div");
    row.className = "wati-list-row";
    row.innerHTML = `
      <div class="wati-list-row-fields">
        <input class="row-title" maxlength="24" placeholder="عنوان الخيار · 24" />
        <input class="row-description" maxlength="72" placeholder="وصف اختياري · 72" />
      </div>
      <button type="button" class="wati-list-remove-row" title="حذف الخيار">×</button>`;
    row.querySelector(".row-title").value = title;
    row.querySelector(".row-description").value = description;
    row.querySelectorAll("input").forEach((el) => el.addEventListener("input", preview));
    row.querySelector(".wati-list-remove-row").addEventListener("click", () => {
      row.remove();
      updateCounter();
      preview();
    });
    return row;
  }

  function addRow(section, title = "", description = "") {
    if (totalRows() >= 10) return notify("الحد الأقصى 10 خيارات.", true);
    section.querySelector(".wati-list-rows").appendChild(rowTemplate(title, description));
    updateCounter();
    preview();
  }

  function addSection(title = "", seedRows = true) {
    if (sectionsBox.children.length >= 10) return notify("الحد الأقصى 10 أقسام.", true);
    const section = document.createElement("section");
    section.className = "wati-list-section";
    section.innerHTML = `
      <div class="wati-list-section-head">
        <input class="section-title" maxlength="24" placeholder="عنوان القسم · 24" />
        <div>
          <button type="button" class="wati-list-add-row">+ خيار</button>
          <button type="button" class="wati-list-remove-section" title="حذف القسم">حذف</button>
        </div>
      </div>
      <div class="wati-list-rows"></div>`;
    section.querySelector(".section-title").value = title;
    section.querySelector(".section-title").addEventListener("input", preview);
    section.querySelector(".wati-list-add-row").addEventListener("click", () => addRow(section));
    section.querySelector(".wati-list-remove-section").addEventListener("click", () => {
      section.remove();
      updateCounter();
      preview();
    });
    sectionsBox.appendChild(section);
    if (seedRows) addRow(section);
    updateCounter();
    preview();
    return section;
  }

  function collectSections() {
    return Array.from(sectionsBox.querySelectorAll(".wati-list-section"))
      .map((section) => ({
        title: section.querySelector(".section-title").value.trim(),
        rows: Array.from(section.querySelectorAll(".wati-list-row"))
          .map((row) => ({
            title: row.querySelector(".row-title").value.trim(),
            description: row.querySelector(".row-description").value.trim(),
          }))
          .filter((row) => row.title),
      }))
      .filter((section) => section.rows.length);
  }

  function preview() {
    const h = header.value.trim();
    const b = body.value.trim();
    const f = footer.value.trim();
    const bt = buttonText.value.trim() || "عرض الخيارات";
    q(".list-preview-header").textContent = h;
    q(".list-preview-header").style.display = h ? "block" : "none";
    q(".list-preview-body").textContent = b || "اكتب نص الرسالة...";
    q(".list-preview-footer").textContent = f;
    q(".list-preview-footer").style.display = f ? "block" : "none";
    q(".list-preview-button").textContent = `☷ ${bt}`;
    const options = q(".list-preview-options");
    options.replaceChildren();
    collectSections().forEach((section) => {
      if (section.title) {
        const sectionTitle = document.createElement("strong");
        sectionTitle.textContent = section.title;
        options.appendChild(sectionTitle);
      }
      section.rows.forEach((row) => {
        const item = document.createElement("div");
        const title = document.createElement("span");
        title.textContent = row.title;
        item.appendChild(title);
        if (row.description) {
          const desc = document.createElement("small");
          desc.textContent = row.description;
          item.appendChild(desc);
        }
        options.appendChild(item);
      });
    });
  }

  function reset() {
    header.value = "";
    body.value = "";
    footer.value = "";
    buttonText.value = "عرض الخيارات";
    sectionsBox.replaceChildren();
    const first = addSection("الخيارات", false);
    addRow(first, "الخيار الأول", "");
    addRow(first, "الخيار الثاني", "");
    updateCounter();
    preview();
  }

  function open() {
    if (!Number(localStorage.getItem("watiInboxSelected") || 0)) return notify("اختر محادثة أولًا.", true);
    if (input.disabled) return notify("استلم المحادثة أولًا.", true);
    reset();
    overlay.classList.remove("is-hidden");
    setTimeout(() => body.focus(), 40);
  }

  function close(force = false) {
    if (!sending || force) overlay.classList.add("is-hidden");
  }

  function validate(sections) {
    if (!body.value.trim()) return "اكتب نص الرسالة أولًا.";
    if (!buttonText.value.trim()) return "اكتب نص زر فتح القائمة.";
    const rows = sections.flatMap((section) => section.rows);
    if (!rows.length) return "أضف خيارًا واحدًا على الأقل.";
    if (rows.length > 10) return "الحد الأقصى 10 خيارات.";
    if (sections.length > 1 && sections.some((section) => !section.title)) return "اكتب عنوانًا لكل قسم عند استخدام أكثر من قسم.";
    const normalized = rows.map((row) => row.title.toLocaleLowerCase());
    if (new Set(normalized).size !== normalized.length) return "اجعل عنوان كل خيار مختلفًا.";
    return "";
  }

  async function submit() {
    if (sending) return;
    const sections = collectSections();
    const error = validate(sections);
    if (error) return notify(error, true);

    const conversationId = Number(localStorage.getItem("watiInboxSelected") || 0);
    const form = new URLSearchParams({
      csrf_token: csrf,
      conversation_id: String(conversationId),
      header: header.value.trim(),
      body: body.value.trim(),
      footer: footer.value.trim(),
      button_text: buttonText.value.trim(),
      sections_json: JSON.stringify(sections),
      request_id: requestId(),
    });

    sending = true;
    sendButton.disabled = true;
    sendButton.textContent = "جاري الإرسال...";
    try {
      const response = await fetch("/wati/inbox/send-list", {
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
      close(true);
      notify("تم قبول القائمة التفاعلية في WATI ✅");
      const refresh = document.getElementById("refreshButton");
      setTimeout(() => refresh?.click(), 900);
      setTimeout(() => refresh?.click(), 2300);
    } catch (error) {
      notify(error.message || "تعذر إرسال القائمة التفاعلية.", true);
    } finally {
      sending = false;
      sendButton.disabled = false;
      sendButton.textContent = "إرسال القائمة";
    }
  }

  [header, body, footer, buttonText].forEach((el) => el.addEventListener("input", preview));
  q(".wati-list-add-section").addEventListener("click", () => addSection("", true));
  q(".wati-list-close").addEventListener("click", () => close());
  q(".wati-list-cancel").addEventListener("click", () => close());
  sendButton.addEventListener("click", submit);
  trigger.addEventListener("click", open);
  overlay.addEventListener("click", (event) => { if (event.target === overlay) close(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !overlay.classList.contains("is-hidden")) close(); });
})();
