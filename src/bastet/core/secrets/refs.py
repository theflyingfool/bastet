"""`secret:` references inside role option values: resolved between resolve() and batches_for() (spec 15.1, 15.2)."""

from __future__ import annotations

from bastet.core.secrets.crypto import SecretError
from bastet.core.secrets.notes import SecretPath
from bastet.roles.contract import SECRET_PREFIX, Option, check_value


class MissingSecret(SecretError):
    """A `secret:` reference names a note that doesn't exist yet."""

    def __init__(self, sp: SecretPath) -> None:
        self.sp = sp
        words = " ".join(part for part in (sp.host, sp.role, sp.name) if part)
        super().__init__(f"missing secret {sp.text} (bastet secret set {words})")


def _secret_path(ref: str, host: str, role: str) -> SecretPath:
    """A full `host/role/name` (or `host/name`) path, or a bare name short for `host/role/name`."""
    if "/" in ref:
        return SecretPath.parse(ref)
    return SecretPath(host, role, ref)


def _walk(opt: Option, value: object, where: str, host: str, role: str, sctx) -> tuple[object, bool]:
    if isinstance(value, str) and value.startswith(SECRET_PREFIX):
        sp = _secret_path(value[len(SECRET_PREFIX):], host, role)
        resolved = sctx.get(sp)
        return check_value(opt, resolved, where), True
    if value is None:
        return value, False
    if opt.type == "list":
        out: list = []
        secret = False
        for i, item in enumerate(value):
            v, s = _walk(opt.items, item, f"{where}[{i}]", host, role, sctx)
            out.append(v)
            secret |= s
        return out, secret
    if opt.type == "map":
        out = {}
        secret = False
        for k, v in value.items():
            nv, s = _walk(opt.items, v, f"{where}.{k}", host, role, sctx)
            out[k] = nv
            secret |= s
        return out, secret
    if opt.type == "object":
        out = dict(value)
        secret = False
        for k, v in value.items():
            nv, s = _walk(opt.fields[k], v, f"{where}.{k}", host, role, sctx)
            out[k] = nv
            secret |= s
        if secret and "secret" in opt.fields:
            out["secret"] = True
        return out, secret
    return value, False


def resolve_refs(values: dict, *, host: str, role: str, options: dict[str, Option], sctx) -> tuple[dict, set[str]]:
    """Walk `values` (as resolve() merged and defaulted them), replacing every `secret:` reference.

    Returns the new values and the top-level option names that became secret (directly or inside a
    list/map/object), so callers that care can mark the resources they build from them.
    """
    out: dict = {}
    became_secret: set[str] = set()
    for key, value in values.items():
        opt = options.get(key)
        if opt is None:
            out[key] = value
            continue
        if value is None and opt.secret:
            value = f"{SECRET_PREFIX}{key}"  # an unset secret option reads its own note: <host>/<role>/<option>
        nv, secret = _walk(opt, value, f"{role}.{key}", host, role, sctx)
        out[key] = nv
        if secret:
            became_secret.add(key)
    return out, became_secret
