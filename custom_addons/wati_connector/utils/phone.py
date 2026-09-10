import re


DEFAULT_COUNTRY_CODE = "966"


def digits_only(value):
    digits = re.sub(r"\D+", "", str(value or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


def normalize_whatsapp_number(value, *, country_code=DEFAULT_COUNTRY_CODE):
    """Normalize common Saudi phone formats to digits-only international form.

    The connector historically accepted +9665..., 009665..., 05..., and 5....
    Keep that behavior in one place. Numbers outside these known local patterns
    are returned as digits-only values rather than guessed into another country.
    """
    digits = digits_only(value)
    if not digits:
        return ""
    if digits.startswith(country_code):
        return digits
    if country_code == "966":
        if len(digits) == 10 and digits.startswith("05"):
            return "966" + digits[1:]
        if len(digits) == 9 and digits.startswith("5"):
            return "966" + digits
    return digits


def phone_identity(value, *, country_code=DEFAULT_COUNTRY_CODE):
    original_digits = digits_only(value)
    international = normalize_whatsapp_number(value, country_code=country_code)
    if not international:
        return {"digits": "", "e164": "", "local": "", "suffix": ""}

    if country_code == "966" and international.startswith("966"):
        local = "0" + international[3:]
    else:
        local = original_digits or international

    return {
        "digits": original_digits,
        "e164": f"+{international}",
        "local": local,
        "suffix": international[-9:],
    }


def equivalent_variants(value, *, country_code=DEFAULT_COUNTRY_CODE):
    normalized = normalize_whatsapp_number(value, country_code=country_code)
    if not normalized:
        return []
    variants = [normalized, f"+{normalized}"]
    if country_code == "966" and normalized.startswith("966") and len(normalized) > 3:
        variants.append("0" + normalized[3:])
    return list(dict.fromkeys(variants))
