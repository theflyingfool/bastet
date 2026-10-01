import shlex

from bastet.core.remote import LocalRunner
from bastet.engine.model import ABSENT, Read, show_value
from bastet.engine.script import exec_script, new_mark, read_script, split_results


def test_read_script_round_trip():
    groups = [(Read("a", "echo one"), Read("b", "exit 4")), (Read("a", "printf 'x\\ny'"),)]
    mark = new_mark()
    r = LocalRunner().run(read_script(groups, mark))
    out = split_results(r.stdout, groups, mark)
    assert out[0]["a"].output == "one" and out[0]["b"].returncode == 4
    assert out[1]["a"].output == "x\ny"


def test_exec_script_runs_commands_and_stops_at_first_failure(tmp_path):
    f = tmp_path / "f"
    text = shlex.quote("it's $HOME \\ \"q\"")
    script = exec_script([f"echo {text} > {f}", "false", f"echo no >> {f}"], root=False, mark=new_mark())
    r = LocalRunner().run(script)
    assert r.returncode != 0 and f.read_text() == "it's $HOME \\ \"q\"\n"


def test_exec_script_root_goes_through_sudo_prefix():
    script = exec_script(["true"], root=True, mark="@@M@@")
    assert "needs root" in script and "$SUDO sh -e <<'@@M@@'" in script and script.rstrip().endswith("@@M@@")
    assert "$SUDO" not in exec_script(["true"], root=False, mark="@@M@@").split("\n", 5)[-1]


def test_show_value():
    assert show_value(True) == "yes" and show_value(False) == "no" and show_value(None) == "(unset)"
    assert show_value("a\nb") == "(contents)" and show_value("x" * 61) == "(contents)"
    assert show_value("hunter2", secret=True) == "(secret)" and show_value(ABSENT, secret=True) == ABSENT
