import re

_SIZE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([a-z]*)\s*$", re.I)
_FACTORS = {
    "": 1, "b": 1,
    "k": 10**3, "kb": 10**3, "m": 10**6, "mb": 10**6, "g": 10**9, "gb": 10**9, "t": 10**12, "tb": 10**12,
    "kib": 2**10, "mib": 2**20, "gib": 2**30, "tib": 2**40,
}
SIZE_KEYS = {"ram", "storage", "disk", "size"}
_TOLERANCE = {"ram": 0.06}
_NICE_GB = (1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96, 128, 160, 192, 256, 320, 384, 512,
            640, 768, 1024, 1536, 2048, 3072, 4096)


def parse_size(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = _SIZE.match(str(value))
    if not m:
        return None
    unit = m.group(2).lower()
    if unit not in _FACTORS:
        return None
    return int(float(m.group(1)) * _FACTORS[unit])


def format_size(n: int, *, binary: bool = False) -> str:
    tb, gb, mb = (2**40, 2**30, 2**20) if binary else (10**12, 10**9, 10**6)
    if n >= tb:
        return f"{n / tb:.1f}".rstrip("0").rstrip(".") + " TB"
    if n >= gb:
        return f"{round(n / gb)} GB"
    if n >= mb:
        return f"{round(n / mb)} MB"
    return f"{n} B"


def ram_label(mem_total_kib: int) -> str:
    gib = mem_total_kib * 1024 / 2**30
    for nice in _NICE_GB:
        if nice >= gib - 0.01:
            return f"{nice} GB"
    return f"{round(gib)} GB"


def same_value(key: str, a: object, b: object) -> bool:
    if key in SIZE_KEYS:
        pa, pb = parse_size(a), parse_size(b)
        if pa and pb:
            return abs(pa - pb) <= _TOLERANCE.get(key, 0.02) * max(pa, pb)
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().casefold() == b.strip().casefold()
    return a == b
