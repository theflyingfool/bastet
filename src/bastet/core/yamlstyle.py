"""Write YAML frontmatter the way Obsidian writes it, so Obsidian edits don't reformat Bastet's lines."""

import datetime as dt
import json
from collections.abc import Mapping

import yaml


def _scalar(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    text = str(value)
    if text.startswith("[["):
        return json.dumps(text, ensure_ascii=False)
    if text and "\n" not in text and text == text.strip():
        try:
            if yaml.safe_load(f"k: {text}") == {"k": text}:
                return text
        except yaml.YAMLError:
            pass
    return json.dumps(text, ensure_ascii=False)


def _entry(key: str, value: object, indent: int) -> list[str]:
    pad = " " * indent
    k = _scalar(key)
    if isinstance(value, Mapping):
        if not value:
            return [f"{pad}{k}: {{}}"]
        lines = [f"{pad}{k}:"]
        for sub_key, sub_value in value.items():
            lines += _entry(str(sub_key), sub_value, indent + 2)
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{pad}{k}: []"]
        lines = [f"{pad}{k}:"]
        for item in value:
            lines += _item(item, indent + 2)
        return lines
    rendered = _scalar(value)
    return [f"{pad}{k}:" + (f" {rendered}" if rendered else "")]


def _item(value: object, indent: int) -> list[str]:
    pad = " " * indent
    if isinstance(value, Mapping):
        if not value:
            return [f"{pad}- {{}}"]
        lines: list[str] = []
        for sub_key, sub_value in value.items():
            lines += _entry(str(sub_key), sub_value, indent + 2)
        lines[0] = f"{pad}- {lines[0].lstrip()}"
        return lines
    if isinstance(value, list):
        return [f"{pad}- {json.dumps(value, ensure_ascii=False, default=str)}"]
    return [f"{pad}- {_scalar(value)}"]


def dump_frontmatter(data: Mapping[str, object]) -> str:
    lines: list[str] = []
    for key, value in data.items():
        lines += _entry(str(key), value, 0)
    return "".join(f"{line}\n" for line in lines)
