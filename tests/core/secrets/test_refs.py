import pytest

from bastet.core.errors import BastetError
from bastet.core.secrets.redact import Redactor
from bastet.core.secrets.refs import MissingSecret, resolve_refs
from bastet.roles.contract import Option


class FakeSecrets:
    """A stand-in for SecretsContext: a fixed set of known secrets, with a real Redactor behind it."""

    def __init__(self, values: dict[str, str]):
        self.values = values
        self.redactor = Redactor()

    def get(self, sp):
        if sp.text not in self.values:
            raise MissingSecret(sp)
        value = self.values[sp.text]
        self.redactor.add(value)
        return value


def test_short_and_long_refs_resolve_in_list_and_map():
    options = {
        "token": Option(type="string"),
        "tags": Option(type="list", items=Option(type="string")),
        "env": Option(type="map", items=Option(type="string")),
    }
    sctx = FakeSecrets({"git1/gitea/token": "tok-value", "git1/gitea/db_password": "db-value"})
    values = {
        "token": "secret:token",  # short: host/role/name
        "tags": ["plain", "secret:git1/gitea/db_password"],  # long: a full path
        "env": {"DB": "secret:db_password"},
    }
    out, became = resolve_refs(values, host="git1", role="gitea", options=options, sctx=sctx)
    assert out == {
        "token": "tok-value",
        "tags": ["plain", "db-value"],
        "env": {"DB": "db-value"},
    }
    assert became == {"token", "tags", "env"}


def test_object_field_gains_the_secret_flag_when_a_sibling_resolves():
    file_opt = Option(type="object", fields={
        "content": Option(type="string"),
        "mode": Option(type="string"),
        "secret": Option(type="bool"),
    })
    options = {"files": Option(type="map", items=file_opt)}
    sctx = FakeSecrets({"box/files/motd": "SENTINEL-4242"})
    values = {"files": {"/etc/motd": {"content": "secret:motd", "mode": "0644"}}}
    out, became = resolve_refs(values, host="box", role="files", options=options, sctx=sctx)
    assert out["files"]["/etc/motd"] == {"content": "SENTINEL-4242", "mode": "0644", "secret": True}
    assert became == {"files"}


def test_int_option_with_a_non_int_secret_value_raises_naming_the_option():
    options = {"count": Option(type="int")}
    sctx = FakeSecrets({"git1/gitea/count": "abc"})
    with pytest.raises(BastetError, match="gitea.count"):
        resolve_refs({"count": "secret:count"}, host="git1", role="gitea", options=options, sctx=sctx)


def test_missing_secret_names_the_set_command():
    options = {"token": Option(type="string")}
    sctx = FakeSecrets({})
    with pytest.raises(MissingSecret, match=r"bastet secret set git1 gitea x"):
        resolve_refs({"token": "secret:x"}, host="git1", role="gitea", options=options, sctx=sctx)


def test_missing_secret_with_a_full_path_names_its_own_words():
    options = {"token": Option(type="string")}
    sctx = FakeSecrets({})
    with pytest.raises(MissingSecret, match=r"bastet secret set nfs bmc_password"):
        resolve_refs({"token": "secret:nfs/bmc_password"}, host="git1", role="gitea", options=options, sctx=sctx)


def test_redactor_masks_values_wherever_text_might_show_them():
    redactor = Redactor()
    redactor.add("SENTINEL-4242")
    assert "SENTINEL-4242" not in redactor.mask("content: (absent) -> SENTINEL-4242")
    assert "SENTINEL-4242" not in redactor.mask("command \"echo SENTINEL-4242\" failed: exit 1")
    assert "SENTINEL-4242" not in redactor.mask("secret: set git1/gitea/motd (previously SENTINEL-4242)")


def test_redactor_ignores_short_values():
    redactor = Redactor()
    redactor.add("abc")
    assert redactor.mask("abc is short") == "abc is short"


def test_unset_secret_option_reads_its_own_note():
    from bastet.roles.contract import Option
    options = {"admin_password": Option(type="string", secret=True), "port": Option(type="int")}
    values, secret = resolve_refs({"admin_password": None, "port": 3000}, host="git1", role="gitea",
                                  options=options, sctx=FakeSecrets({"git1/gitea/admin_password": "from-the-note"}))
    assert values == {"admin_password": "from-the-note", "port": 3000} and secret == {"admin_password"}


def test_unset_secret_option_without_a_note_is_missing():
    import pytest
    from bastet.roles.contract import Option
    with pytest.raises(MissingSecret, match="bastet secret set git1 gitea admin_password"):
        resolve_refs({"admin_password": None}, host="git1", role="gitea",
                     options={"admin_password": Option(type="string", secret=True)}, sctx=FakeSecrets({}))
