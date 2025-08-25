# utils/upc_helpers.py
def _digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def upc_variants_from_sheet(value: str):
    """
    Generate all reasonable variants for a UPC stored in the sheet.
    Handles cells that lost leading zero or were formatted as numbers.
    Returns a list of unique strings.
    """
    variants = []
    raw = (value or "").strip()
    dig = _digits_only(raw)

    def add(v):
        if v and v not in variants:
            variants.append(v)

    # raw and digits-only
    add(raw)
    add(dig)

    # If the sheet lost a leading zero on a 12-digit UPC (now 11 digits)
    if len(dig) == 11:
        add("0" + dig)             # 12-digit with restored leading zero
    # If the sheet stored 12-digit UPC properly, also add 13-digit EAN with leading 0
    if len(dig) == 12:
        add("0" + dig)             # EAN-13 variant
        add(dig.lstrip("0"))       # also without leading zeros (defensive)
    # If sheet stored EAN-13 that starts with 0, add 12-digit UPC-A
    if len(dig) == 13 and dig.startswith("0"):
        add(dig[1:])
    # If GTIN-14 with leading zeros, add trimmed versions down to 12
    if len(dig) == 14:
        t = dig.lstrip("0")
        add(t)
        if len(t) == 13 and t.startswith("0"):
            add(t[1:])
        if len(t) == 12 and (not t.startswith("0")):
            add("0" + t)  # also add an EAN-13 with leading zero

    return variants

def upc_variants_from_scan(scan: str):
    """
    Generate variants for an incoming scan.
    Most scanners give 12-digit UPC-A or 13-digit EAN-13.
    """
    variants = []
    raw = (scan or "").strip()
    dig = _digits_only(raw)

    def add(v):
        if v and v not in variants:
            variants.append(v)

    add(raw)
    add(dig)

    # If 13 and starts with 0, also try 12
    if len(dig) == 13 and dig.startswith("0"):
        add(dig[1:])
    # If 12 and starts with 0, try without that zero (for sheets that lost it)
    if len(dig) == 12 and dig.startswith("0"):
        add(dig[1:])
    # If 11 (sheet lost zero scenario), try adding a leading zero
    if len(dig) == 11:
        add("0" + dig)
    # If 14, trim leading zeros down to 13/12
    if len(dig) == 14:
        t = dig.lstrip("0")
        add(t)
        if len(t) == 13 and t.startswith("0"):
            add(t[1:])

    return variants
