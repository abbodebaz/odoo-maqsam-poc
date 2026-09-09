#!/usr/bin/env python3
"""One-time converter for WATI runtime source strings.

The WATI addon historically accumulated Arabic hard-coded UI copy. This helper
converts Arabic word runs in runtime Python/XML/JavaScript files to English while
leaving identifiers, placeholders, numbers and punctuation untouched.

It deliberately batches translation requests so the one-time conversion does not
hammer the public translation endpoint and hit rate limits.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_GLOB = "wati_connector*"
TARGET_SUFFIXES = {".py", ".xml", ".js"}
SKIP_PARTS = {"tests", "docs", "notes", "i18n", "migrations"}
CACHE_PATH = ROOT / ".wati_translate_cache.json"
ARABIC_RUN = re.compile(r"[\u0600-\u06FF]+(?:[ \t]+[\u0600-\u06FF]+)*")
ARABIC_ANY = re.compile(r"[\u0600-\u06FF]")
SPLIT_MARKER = "ZXWATISPLITXZ"

OVERRIDES = {
    "واتساب": "WhatsApp",
    "واتس اب": "WhatsApp",
    "واتس آب": "WhatsApp",
    "واتي": "WATI",
    "أودو": "Odoo",
    "اودو": "Odoo",
    "الرئيسية": "Home",
    "المحادثات": "Conversations",
    "سجل المحادثات": "Conversation Log",
    "سجل الرسائل": "Message Log",
    "القوالب": "Templates",
    "مركز القوالب": "Template Center",
    "الأتمتة": "Automation",
    "مركز الأتمتة": "Automation Center",
    "سجل التشغيل": "Run Log",
    "المراقبة": "Monitor",
    "مراقبة": "Monitor",
    "المساعدة": "Help",
    "الإعدادات": "Settings",
    "الصلاحيات": "Permissions",
    "صندوق الوارد": "Inbox",
    "الاتصال": "Connection",
    "العميل": "Customer",
    "العملاء": "Customers",
    "رسالة": "Message",
    "الرسائل": "Messages",
    "إرسال": "Send",
    "إلغاء": "Cancel",
    "حفظ": "Save",
    "تحديث": "Refresh",
    "بحث": "Search",
    "نشط": "Active",
    "غير نشط": "Inactive",
    "مفعل": "Enabled",
    "معطل": "Disabled",
    "جاهز": "Ready",
    "فشل": "Failed",
    "ناجح": "Successful",
    "وارد": "Incoming",
    "صادر": "Outgoing",
    "رقم الجوال": "Mobile Number",
    "رقم الهاتف": "Phone Number",
    "القالب": "Template",
    "الحالة": "Status",
    "اللغة": "Language",
    "التصنيف": "Category",
    "المصدر": "Source",
    "التفاصيل": "Details",
    "سجل العميل": "Customer Timeline",
    "الأزرار": "Buttons",
    "القوائم": "Lists",
    "المرفقات": "Attachments",
    "مشرف": "Supervisor",
    "مدير": "Administrator",
    "موظف": "Agent",
    "نسخ": "Copy",
}


def runtime_files() -> list[Path]:
    files: list[Path] = []
    for module in sorted((ROOT / "custom_addons").glob(MODULE_GLOB)):
        if not module.is_dir():
            continue
        for path in module.rglob("*"):
            if not path.is_file() or path.suffix not in TARGET_SUFFIXES:
                continue
            if SKIP_PARTS.intersection(path.parts):
                continue
            files.append(path)
    return files


def clean_translation(value: str) -> str:
    value = value.strip()
    # Curly quotes cannot terminate ordinary ASCII Python/JS string delimiters.
    value = value.replace("'", "’").replace('"', "”").replace("`", "’")
    value = value.replace("&", "and").replace("<", "").replace(">", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def request_translation(text: str) -> str:
    query = urllib.parse.urlencode(
        {"client": "gtx", "sl": "ar", "tl": "en", "dt": "t", "q": text}
    )
    url = "https://translate.googleapis.com/translate_a/single?" + query
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 WATI-i18n-build/1.0"},
    )
    last_error: Exception | None = None
    for attempt in range(8):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            translated = "".join(part[0] for part in payload[0] if part and part[0])
            if not translated:
                raise ValueError("empty translation")
            return translated
        except Exception as exc:
            last_error = exc
            time.sleep(min(20.0, 1.0 * (2**attempt)))
    raise RuntimeError(f"Translation request failed: {last_error}")


def translate_batch(batch: list[str]) -> dict[str, str]:
    if not batch:
        return {}
    if len(batch) == 1:
        phrase = batch[0]
        value = OVERRIDES.get(phrase)
        if value is None:
            value = clean_translation(request_translation(phrase))
        if not value or ARABIC_ANY.search(value):
            raise RuntimeError(f"Invalid translation for {phrase!r}: {value!r}")
        return {phrase: value}

    joined = f"\n{SPLIT_MARKER}\n".join(batch)
    translated = request_translation(joined)
    parts = re.split(rf"\s*{re.escape(SPLIT_MARKER)}\s*", translated)
    if len(parts) != len(batch):
        # Translation services can occasionally rewrite a separator. Split the
        # work recursively rather than falling back to thousands of requests.
        mid = len(batch) // 2
        result = translate_batch(batch[:mid])
        result.update(translate_batch(batch[mid:]))
        return result

    result: dict[str, str] = {}
    for phrase, part in zip(batch, parts):
        value = OVERRIDES.get(phrase) or clean_translation(part)
        if not value or ARABIC_ANY.search(value):
            raise RuntimeError(f"Invalid translation for {phrase!r}: {value!r}")
        result[phrase] = value
    return result


def load_cache() -> dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in data.items()}
    except Exception:
        return {}


def save_cache(cache: dict[str, str]) -> None:
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def collect_phrases(files: list[Path]) -> list[str]:
    phrases: set[str] = set()
    for path in files:
        text = path.read_text(encoding="utf-8")
        phrases.update(match.group(0) for match in ARABIC_RUN.finditer(text))
    return sorted(phrases, key=lambda item: (-len(item), item))


def make_batches(items: list[str], max_items: int = 24, max_chars: int = 3200) -> list[list[str]]:
    batches: list[list[str]] = []
    current: list[str] = []
    chars = 0
    separator_cost = len(SPLIT_MARKER) + 2
    for item in items:
        projected = chars + len(item) + (separator_cost if current else 0)
        if current and (len(current) >= max_items or projected > max_chars):
            batches.append(current)
            current = []
            chars = 0
        current.append(item)
        chars += len(item) + (separator_cost if len(current) > 1 else 0)
    if current:
        batches.append(current)
    return batches


def translate_all(phrases: list[str], cache: dict[str, str]) -> dict[str, str]:
    for phrase, translated in OVERRIDES.items():
        if phrase in phrases:
            cache[phrase] = translated

    missing = [phrase for phrase in phrases if phrase not in cache]
    print(
        f"WATI_ENGLISH_PHRASES total={len(phrases)} "
        f"cached={len(phrases) - len(missing)} missing={len(missing)}"
    )
    batches = make_batches(missing)
    print(f"WATI_ENGLISH_BATCHES count={len(batches)}")

    completed = 0
    for index, batch in enumerate(batches, 1):
        cache.update(translate_batch(batch))
        completed += len(batch)
        save_cache(cache)
        print(f"WATI_ENGLISH_PROGRESS batch={index}/{len(batches)} phrases={completed}/{len(missing)}")
        time.sleep(0.15)
    return cache


def rewrite(files: list[Path], translations: dict[str, str]) -> tuple[int, int]:
    changed_files = 0
    replacements = 0

    def replace_match(match: re.Match[str]) -> str:
        nonlocal replacements
        phrase = match.group(0)
        translated = translations.get(phrase)
        if translated is None:
            raise RuntimeError(f"Missing translation for {phrase!r}")
        replacements += 1
        return translated

    for path in files:
        original = path.read_text(encoding="utf-8")
        if not ARABIC_ANY.search(original):
            continue
        updated = ARABIC_RUN.sub(replace_match, original)
        if ARABIC_ANY.search(updated):
            remaining = sorted(set(ARABIC_RUN.findall(updated)))[:10]
            raise RuntimeError(f"Arabic remained in {path}: {remaining}")
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed_files += 1

    return changed_files, replacements


def main() -> int:
    files = runtime_files()
    phrases = collect_phrases(files)
    cache = load_cache()
    translations = translate_all(phrases, cache)
    save_cache(translations)
    changed_files, replacements = rewrite(files, translations)
    print(f"WATI_ENGLISH_DONE files={changed_files} replacements={replacements}")
    CACHE_PATH.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
