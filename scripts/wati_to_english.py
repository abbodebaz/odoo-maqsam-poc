#!/usr/bin/env python3
"""One-time converter for WATI runtime source strings.

The commercial WATI addon historically accumulated Arabic hard-coded UI copy.
This script converts Arabic word sequences in runtime Python/XML/JavaScript files
to English while leaving code syntax, identifiers, placeholders and punctuation
untouched. It is intended to run once on the bilingual cleanup feature branch.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_GLOB = "wati_connector*"
TARGET_SUFFIXES = {".py", ".xml", ".js"}
SKIP_PARTS = {"tests", "docs", "notes", "i18n", "migrations"}
CACHE_PATH = ROOT / ".wati_translate_cache.json"

# Translate complete Arabic word runs, but deliberately leave ASCII syntax,
# placeholders, numbers and punctuation outside each run.
ARABIC_RUN = re.compile(r"[\u0600-\u06FF]+(?:[ \t]+[\u0600-\u06FF]+)*")
ARABIC_ANY = re.compile(r"[\u0600-\u06FF]")

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
    # Keep translated text safe inside Python/JS/XML delimiters. Curly quote
    # characters are display-safe and cannot terminate ASCII string literals.
    value = value.replace("'", "’").replace('"', "”").replace("`", "’")
    value = value.replace("&", "and").replace("<", "").replace(">", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def google_translate(phrase: str) -> str:
    if phrase in OVERRIDES:
        return OVERRIDES[phrase]

    query = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": "ar",
            "tl": "en",
            "dt": "t",
            "q": phrase,
        }
    )
    url = "https://translate.googleapis.com/translate_a/single?" + query
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 WATI-i18n-build/1.0"},
    )
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            translated = "".join(part[0] for part in payload[0] if part and part[0])
            translated = clean_translation(translated)
            if not translated or ARABIC_ANY.search(translated):
                raise ValueError(f"translation still contains Arabic: {translated!r}")
            return translated
        except Exception as exc:  # network service can transiently throttle
            last_error = exc
            time.sleep(min(8.0, 0.5 * (2**attempt)))
    raise RuntimeError(f"Could not translate {phrase!r}: {last_error}")


def load_cache() -> dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}
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


def translate_all(phrases: list[str], cache: dict[str, str]) -> dict[str, str]:
    for phrase, translated in OVERRIDES.items():
        if phrase in phrases:
            cache[phrase] = translated

    missing = [phrase for phrase in phrases if phrase not in cache]
    print(f"WATI_ENGLISH_PHRASES total={len(phrases)} cached={len(phrases)-len(missing)} missing={len(missing)}")

    if not missing:
        return cache

    workers = max(2, min(int(os.environ.get("WATI_TRANSLATE_WORKERS", "6")), 10))
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(google_translate, phrase): phrase for phrase in missing}
        for future in as_completed(futures):
            phrase = futures[future]
            translated = future.result()
            cache[phrase] = translated
            completed += 1
            if completed % 50 == 0 or completed == len(missing):
                print(f"WATI_ENGLISH_PROGRESS {completed}/{len(missing)}")
                save_cache(cache)
    return cache


def rewrite(files: list[Path], translations: dict[str, str]) -> tuple[int, int]:
    changed_files = 0
    replacements = 0

    # Regex callback avoids replacement ordering problems with phrases that are
    # substrings of other phrases.
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
