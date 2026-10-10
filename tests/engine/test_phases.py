from typing import ClassVar

import pytest

from bastet.core.errors import BastetError
from bastet.core.remote import LocalRunner
from bastet.engine.model import Trigger
from bastet.engine.run import Batch, run_host
from bastet.engine.slots import SLOTS, apply_order, rank
from engine_fakes import Broken, Flag


class Pkg(Flag):
    slot: ClassVar[str] = "packages"


class Svc(Flag):
    slot: ClassVar[str] = "systemd"


def sequence(*batches):
    from bastet.engine.run import collect_items

    return [i.resource.label for i in apply_order(collect_items(list(batches)))]


def test_items_from_different_batches_run_in_slot_order(tmp_path):
    a, b, c = (str(tmp_path / n) for n in "abc")
    first = Batch("first", [Svc(path=a, value="1"), Flag(path=b, value="2")])      # systemd, then files
    second = Batch("second", [Pkg(path=c, value="3")])                              # packages
    assert sequence(first, second) == [c, b, a]


def test_within_a_slot_batch_order_then_item_order_is_kept(tmp_path):
    a, b, c = (str(tmp_path / n) for n in "abc")
    assert sequence(Batch("one", [Flag(path=a, value="1"), Flag(path=b, value="2")]), Batch("two", [Flag(path=c, value="3")])) == [a, b, c]


def test_entry_knobs_move_an_entry(tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    early = Flag(path=a, value="1", run_before="packages")           # a files-slot entry that must precede packages
    assert sequence(Batch("x", [Pkg(path=b, value="2"), early])) == [a, b]
    late = Pkg(path=a, value="1", run_after="systemd")
    assert sequence(Batch("x", [late, Svc(path=b, value="2")])) == [b, a]


def test_provides_moves_an_entry_before_the_blocks_that_want_it(tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    cfg = Flag(path=a, value="1", provides=("package-manager",))     # a files entry; packages wants package-manager
    assert sequence(Batch("x", [Pkg(path=b, value="2"), cfg])) == [a, b]
    assert rank(cfg) < SLOTS.index("repositories")
    assert rank(Flag(path=a, value="1", provides=("something-else",))) == SLOTS.index("files")


def test_an_unknown_block_name_is_an_error_at_plan_time_even_in_check(tmp_path):
    bad = Flag(path=str(tmp_path / "a"), value="1", run_before="nonsense")
    with pytest.raises(BastetError, match="unknown block 'nonsense'"):
        run_host(LocalRunner(), "h", [Batch("x", [bad])], apply=False)


def test_every_resource_class_has_a_known_slot():
    import bastet.engine.command, bastet.engine.files, bastet.engine.packages, bastet.engine.security  # noqa: F401
    import bastet.engine.systemd, bastet.engine.users  # noqa: F401
    from bastet.engine.model import Resource

    def walk(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from walk(sub)

    for cls in walk(Resource):
        if cls.__module__.startswith("bastet."):
            assert cls.slot in SLOTS, f"{cls.__name__}.slot = {cls.slot!r}"


def test_triggers_from_several_batches_run_once_at_the_end_in_order(tmp_path):
    log = tmp_path / "log"
    late = Trigger("late", f"echo late >> {log}", root=False)
    early = Trigger("early", f"echo early >> {log}", order=10, root=False)
    run = run_host(LocalRunner(), "h", [
        Batch("one", [Flag(path=str(tmp_path / "a"), value="1", on_change=(late, early))]),
        Batch("two", [Flag(path=str(tmp_path / "b"), value="2", on_change=(late,))]),
    ], apply=True)
    assert log.read_text() == "early\nlate\n"
    assert [(t.trigger.label, t.ok) for t in run.triggers] == [("early", True), ("late", True)]


def test_a_failure_skips_everything_later_on_the_host_but_earlier_triggers_still_fire(tmp_path):
    log = tmp_path / "log"
    t = Trigger("t", f"echo ran >> {log}", root=False)
    ok = Flag(path=str(tmp_path / "ok"), value="1", on_change=(t,))
    bad, later = str(tmp_path / "bad"), str(tmp_path / "later")
    run = run_host(LocalRunner(), "h", [Batch("x", [ok, Broken(path=bad, value="x")]), Batch("y", [Svc(path=later, value="z")])], apply=True)
    s = {i.resource.label: (i.status, i.error) for i in run.items}
    assert s[bad] == ("failed", "boom") and s[later] == ("skipped", f"earlier failure on this host: {bad}")
    assert not (tmp_path / "later").exists() and log.read_text() == "ran\n" and not run.ok


def test_a_failed_trigger_stops_the_remaining_triggers(tmp_path):
    log = tmp_path / "log"
    boom = Trigger("boom", "exit 1", order=10, root=False)
    after = Trigger("after", f"echo x >> {log}", order=20, root=False)
    run = run_host(LocalRunner(), "h", [Batch("x", [Flag(path=str(tmp_path / "a"), value="1", on_change=(after, boom))])], apply=True)
    assert [(t.trigger.label, t.ok) for t in run.triggers] == [("boom", False)] and not log.exists() and not run.ok
