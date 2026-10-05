"""Secret health: findings behind `check`'s summary and `bastet secret audit`."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import re
from dataclasses import dataclass

from bastet.core.errors import BastetError
from bastet.core.secrets import crypto
from bastet.core.secrets.crypto import PathMismatch, SecretError
from bastet.core.secrets.notes import SecretNote, SecretPath, all_notes_safe

EXPIRING_DAYS = 14  # a hard `expires` date within this many days is "expiring", not just "expired" later
FEW_RECIPIENTS_THRESHOLD = 2  # fewer distinct recipients than this: nobody but Bastet (or nobody at all) can decrypt
WEAK_MIN_LENGTH = 12
WEAK_DEFAULTS = {
    "admin", "password", "changeme", "123456", "letmein", "qwerty", "welcome", "secret", "default", "root", "guest",
}

BLOCKING_KINDS = {"missing", "undecryptable", "path_mismatch", "plaintext", "changed_upstream"}


@dataclass
class Finding:
    kind: str
    severity: str  # "block" (check stops hosts that need it) | "info" (a one-line summary pointing at audit)
    sp: SecretPath | None
    text: str  # a path and a reason; never a decrypted value


def _now() -> dt.datetime:  # patchable in tests
    return dt.datetime.now()


# --- duration and date parsing (rotation policy) ---

_DURATION = re.compile(r"^(\d+)([dwy])$")
_UNIT_DAYS = {"d": 1, "w": 7, "y": 365}


def _parse_duration(text: object) -> dt.timedelta | None:
    if not text:
        return None
    m = _DURATION.match(str(text).strip())
    if not m:
        return None
    n, unit = m.groups()
    return dt.timedelta(days=int(n) * _UNIT_DAYS[unit])


def _parse_when(value: object) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time())
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


# --- rotation policy precedence (read-only; rotating itself is part 2) ---


def _policy_map(value: object) -> dict[str, str]:
    """A `rotate_every` value: a per-source map, or a bare duration applied to every source."""
    if not value:
        return {}
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items() if v}
    return {"generated": value, "issued": value, "chosen": value}


def _opt_for(sp: SecretPath):
    if not sp.role:
        return None
    from bastet.roles.contract import load_roles  # lazy: roles builds on core

    role = load_roles().get(sp.role)
    return role.options.get(sp.name) if role else None


def _role_file_policy(ctx, sp: SecretPath) -> object:
    """The `rotate_every` set on the host's own role file for this secret's role, if any (highest-ranked source wins)."""
    if not sp.role or sp.host.lower() == "lab":
        return None
    host_doc = ctx.inventory.get(sp.host)
    if host_doc is None:
        return None
    from bastet.roles.resolve import sources_for  # lazy: roles builds on core

    sources = sources_for(ctx.inventory, host_doc, ctx.types).get(sp.role, [])
    best = None
    for s in sources:
        if s.doc is not None and s.doc.data.get("rotate_every") is not None and (best is None or s.rank > best.rank):
            best = s
    return best.doc.data.get("rotate_every") if best else None


def effective_rotate_every(ctx, note: SecretNote) -> object:
    """The weakest-to-strongest policy (role contract < Homelab.md < host note < host's role file < the secret note),
    each level a per-source map overriding only the keys it sets; the result is this note's own `source`'s duration.
    """
    sp = note.path
    policy: dict[str, str] = {}
    opt = _opt_for(sp)
    policy.update(_policy_map(opt.rotate_every if opt else None))
    lab = ctx.inventory.lab
    if lab is not None:
        policy.update(_policy_map((lab.data.get("secrets") or {}).get("rotate_every")))
    if sp.host.lower() != "lab":
        host_doc = ctx.inventory.get(sp.host)
        if host_doc is not None:
            policy.update(_policy_map(host_doc.data.get("rotate_every")))
    policy.update(_policy_map(_role_file_policy(ctx, sp)))
    policy.update(_policy_map(note.data.get("rotate_every")))
    source = note.data.get("source") or "chosen"
    return policy.get(source)


def _rotation_finding(ctx, note: SecretNote, now: dt.datetime) -> Finding | None:
    if note.data.get("rotates") is False:
        return None
    duration = _parse_duration(effective_rotate_every(ctx, note))
    if duration is None:
        return None
    base = _parse_when(note.data.get("rotated")) or _parse_when(note.data.get("created"))
    if base is None or now - base < duration:
        return None
    return Finding("rotation_due", "info", note.path, f"{note.path.text}: rotation due")


def _expiry_finding(note: SecretNote, now: dt.datetime) -> Finding | None:
    expires = _parse_when(note.data.get("expires"))
    if expires is None:
        return None
    if expires < now:
        return Finding("expired", "info", note.path, f"{note.path.text}: expired {expires:%Y-%m-%d}")
    if expires - now <= dt.timedelta(days=EXPIRING_DAYS):
        return Finding("expiring", "info", note.path, f"{note.path.text}: expires {expires:%Y-%m-%d}")
    return None


# --- needs_reencryption: compare the armor header's recipient stanzas with the current recipients ---

_STANZA = re.compile(r"^-> (\S+) (.+)$")


def _armor_stanzas(armor: str) -> list[tuple[str, str]]:
    body = "".join(line for line in armor.strip().splitlines() if not line.startswith("-----"))
    raw = base64.b64decode(body)
    text = raw.decode("ascii", errors="replace")
    out = []
    for line in text.splitlines():
        m = _STANZA.match(line)
        if m and m.group(1) in ("X25519", "ssh-ed25519"):
            out.append((m.group(1), m.group(2).split()[0]))
    return out


def _ssh_tag(pub_line: str) -> str | None:
    """age's ssh-ed25519 stanza tag: the first 4 bytes of SHA-256 of the key's SSH wire-format blob, base64 (no padding)."""
    parts = pub_line.strip().split()
    if len(parts) < 2:
        return None
    try:
        raw = base64.b64decode(parts[1])
    except Exception:
        return None
    return base64.b64encode(hashlib.sha256(raw).digest()[:4]).decode().rstrip("=")


def needs_reencryption(note: SecretNote, recipients: list[str]) -> bool:
    try:
        stanzas = _armor_stanzas(note.body)
    except Exception:
        return False
    have_ssh = {tag for kind, tag in stanzas if kind == "ssh-ed25519"}
    have_x25519 = sum(1 for kind, _ in stanzas if kind == "X25519")
    want_ssh: set[str] = set()
    want_x25519 = 0
    for line in dict.fromkeys(r.strip() for r in recipients if r.strip()):
        if line.startswith("age1"):
            want_x25519 += 1
        else:
            tag = _ssh_tag(line)
            if tag:
                want_ssh.add(tag)
    return have_ssh != want_ssh or have_x25519 != want_x25519


# --- weak values (audit only: decrypts every value) ---


def _is_weak(value: str) -> bool:
    if len(value) < WEAK_MIN_LENGTH:
        return True
    if value.lower() in WEAK_DEFAULTS:
        return True
    classes = sum((
        any(c.islower() for c in value),
        any(c.isupper() for c in value),
        any(c.isdigit() for c in value),
        any(not c.isalnum() for c in value),
    ))
    return classes <= 1


# --- who uses what (role files reaching a host, via `secret:` references or an implicit `secret: true` option) ---


def _refs_in(opt, value, host: str, role: str):
    if isinstance(value, str) and value.startswith("secret:"):
        ref = value[len("secret:"):]
        yield SecretPath.parse(ref) if "/" in ref else SecretPath(host, role, ref)
        return
    if value is None:
        return
    if opt.type == "list" and isinstance(value, list):
        for item in value:
            yield from _refs_in(opt.items, item, host, role)
    elif opt.type == "map" and isinstance(value, dict):
        for v in value.values():
            yield from _refs_in(opt.items, v, host, role)
    elif opt.type == "object" and isinstance(value, dict):
        for k, v in value.items():
            if k in opt.fields:
                yield from _refs_in(opt.fields[k], v, host, role)


def collect_uses(inv, types: dict) -> dict[str, list[str]]:
    """Secret paths referenced by a role option reaching a host, and which hosts reach it (used by health and
    `_bastet/Secrets.md`). Takes the inventory and host types directly, so it needs no decrypting context.
    """
    from bastet.roles.contract import load_roles  # lazy: roles builds on core
    from bastet.roles.resolve import resolve

    uses: dict[str, list[str]] = {}
    roles = load_roles()
    for doc in inv.of_kind("host"):
        if doc.data.get("state", "present") == "destroyed":
            continue
        try:
            applied = resolve(inv, doc, types, roles)
        except BastetError:
            continue
        try:
            for a in applied:
                for key, value in a.values.items():
                    opt = a.role.options.get(key)
                    if opt is None:
                        continue
                    if value is None:
                        if opt.secret:
                            sp = SecretPath(doc.name, a.role.name, key)
                            uses.setdefault(sp.text, [])
                            if doc.name not in uses[sp.text]:
                                uses[sp.text].append(doc.name)
                        continue
                    for sp in _refs_in(opt, value, doc.name, a.role.name):
                        uses.setdefault(sp.text, [])
                        if doc.name not in uses[sp.text]:
                            uses[sp.text].append(doc.name)
        except SecretError:
            # a host or role name this host's secret paths would be built from isn't a valid secret
            # path component (I8, e.g. a host name with a space): don't let it crash health findings
            # or Secrets.md for every other host.
            continue
    return uses


def _placeholder_findings(ctx) -> list[Finding]:
    """Early testing: a literal plain value in a `secret: true` option in a role file."""
    from bastet.roles.contract import load_roles  # lazy: roles builds on core

    roles = load_roles()
    out = []
    for doc in ctx.inventory.role_files:
        role = roles.get(str(doc.data.get("role")))
        if role is None:
            continue
        for key, value in doc.data.items():
            opt = role.options.get(key)
            if opt is None or not opt.secret:
                continue
            if isinstance(value, str) and value and not value.startswith("secret:"):
                out.append(Finding("placeholder", "info", None,
                                    f"{doc.path.name}: {role.name}.{key} is a literal value, not a secret: "
                                    "reference (placeholder values only)"))
    return out


def _few_recipients_finding(ctx) -> Finding | None:
    recipients = {r.strip() for r in ctx.secrets.recipients if r.strip()}
    if len(recipients) < FEW_RECIPIENTS_THRESHOLD:
        return Finding("few_recipients", "info", None,
                        f"only {len(recipients)} recipient(s) can decrypt secrets; "
                        "add more under Homelab.md secrets.recipients")
    return None


def _in_scope(sp: SecretPath, scope_hosts: list[str] | None, uses: dict[str, list[str]]) -> bool:
    if scope_hosts is None:
        return True
    wanted = {h.lower() for h in scope_hosts}
    if sp.host.lower() in wanted:
        return True
    if sp.host.lower() == "lab":
        return any(h.lower() in wanted for h in uses.get(sp.text, []))
    return False


def relevant_secrets(ctx, scope_hosts: list[str] | None = None) -> bool:
    """Whether there's anything secret-related in scope at all (so a secretless inventory's `check` stays silent)."""
    notes, bad = all_notes_safe(ctx.root)
    if bad:
        return True
    uses = collect_uses(ctx.inventory, ctx.types)
    if any(_in_scope(n.path, scope_hosts, uses) for n in notes):
        return True
    wanted = {h.lower() for h in scope_hosts} if scope_hosts is not None else None
    return any(wanted is None or any(h.lower() in wanted for h in hosts) for hosts in uses.values())


def findings(ctx, scope_hosts: list[str] | None = None, *, audit: bool = False) -> list[Finding]:
    """Every secret-health finding. `scope_hosts=None` means everything (`bastet secret audit`);
    otherwise only those hosts plus the lab secrets they use (`check`'s summary).
    """
    out: list[Finding] = []
    notes, bad = all_notes_safe(ctx.root)
    uses = collect_uses(ctx.inventory, ctx.types)

    for b in bad:
        out.append(Finding("undecryptable", "block", None, f"{b.rel}: can't be read ({b.error})"))

    try:
        identities = ctx.secrets.identities()
    except Exception:
        identities = None
    recipients = list(dict.fromkeys(r.strip() for r in ctx.secrets.recipients if r.strip()))
    now = _now()

    for note in notes:
        sp = note.path
        if not _in_scope(sp, scope_hosts, uses):
            continue
        plain = note.data.get("locked") is False or not note.is_sealed
        if plain:
            out.append(Finding("plaintext", "block", sp, f"{sp.text}: plain text; run `bastet secret lock`"))
            continue
        decrypted: str | None = None
        if identities is not None:
            try:
                decrypted = crypto.open_sealed(note.body.strip(), sp.text, identities).value
                ctx.secrets.redactor.add(decrypted)
            except PathMismatch as exc:
                out.append(Finding("path_mismatch", "block", sp, str(exc)))
                continue
            except SecretError as exc:
                out.append(Finding("undecryptable", "block", sp, str(exc)))
                continue
        if needs_reencryption(note, recipients):
            out.append(Finding("needs_reencryption", "info", sp, f"{sp.text}: recipients changed; needs re-encryption"))
        rf = _rotation_finding(ctx, note, now)
        if rf:
            out.append(rf)
        ef = _expiry_finding(note, now)
        if ef:
            out.append(ef)
        try:
            name, _email, _date = ctx.repo.last_author(ctx.root / sp.rel)
            from bastet.core.gitrepo import BASTET_NAME

            if name and name != BASTET_NAME:
                out.append(Finding("not_by_bastet", "info", sp, f"{sp.text}: last changed by {name}, not Bastet"))
        except Exception:
            pass
        standalone = bool(note.data.get("standalone"))
        used = bool(uses.get(sp.text))
        if standalone and used:
            out.append(Finding("standalone_but_used", "info", sp, f"{sp.text}: standalone, but something uses it"))
        elif not standalone and not used:
            out.append(Finding("unused", "info", sp, f"{sp.text}: nothing references it (set standalone: true if intentional)"))
        if audit and decrypted is not None and _is_weak(decrypted):
            out.append(Finding("weak", "info", sp, f"{sp.text}: weak value"))

    for text, hosts_using in uses.items():
        if scope_hosts is not None and not any(h.lower() in {s.lower() for s in scope_hosts} for h in hosts_using):
            continue
        sp = SecretPath.parse(text)
        if (ctx.root / sp.rel).exists():
            continue
        opt = _opt_for(sp)
        severity = "info" if (opt and opt.generate) else "block"
        out.append(Finding("missing", severity, sp, f"{sp.text}: missing (used by {', '.join(sorted(hosts_using))})"))

    out.extend(_placeholder_findings(ctx))

    few = _few_recipients_finding(ctx)
    if few:
        out.append(few)

    for rel in getattr(ctx, "upstream_secrets", None) or []:
        out.append(Finding("changed_upstream", "block", None, f"{rel}: changed upstream"))

    return out


AUDIT_PATH = "_bastet/secret-audit.md"
AUDIT_KIND_ORDER = (
    "missing", "undecryptable", "path_mismatch", "plaintext", "changed_upstream", "not_by_bastet",
    "rotation_due", "expiring", "expired", "unused", "standalone_but_used", "placeholder",
    "few_recipients", "needs_reencryption", "weak",
)


def audit_note(found: list[Finding], when: str) -> str:
    """`_bastet/secret-audit.md`: every finding grouped by kind, with a `checked` date."""
    import bastet.core.yamlstyle as yamlstyle

    by_kind: dict[str, list[Finding]] = {}
    for f in found:
        by_kind.setdefault(f.kind, []).append(f)
    parts = ["Secret hygiene, from `bastet secret audit`. Never shows a value.\n"]
    if not found:
        parts.append("\nNo findings.\n")
    for kind in AUDIT_KIND_ORDER:
        items = by_kind.pop(kind, None)
        if not items:
            continue
        parts.append(f"\n## {kind}\n\n")
        parts += [f"- {f.text}\n" for f in sorted(items, key=lambda f: f.text)]
    for kind, items in sorted(by_kind.items()):  # any kind not in AUDIT_KIND_ORDER, just in case
        parts.append(f"\n## {kind}\n\n")
        parts += [f"- {f.text}\n" for f in sorted(items, key=lambda f: f.text)]
    front = yamlstyle.dump_frontmatter({"checked": when})
    return f"---\n{front}---\n" + "".join(parts)


def summary_lines(found: list[Finding]) -> list[str]:
    """`check`'s summary: one line when healthy, else every blocking finding plus an audit pointer."""
    if not found:
        return ["Secrets: healthy."]
    blocking = [f for f in found if f.severity == "block"]
    rest = [f for f in found if f.severity != "block"]
    lines = [f"Secrets: {f.text}" for f in blocking]
    if rest:
        lines.append(f"Secrets: {len(rest)} audit finding{'s' if len(rest) != 1 else ''}; run `bastet secret audit`")
    if not lines:
        lines = ["Secrets: healthy."]
    return lines
