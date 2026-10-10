from bastet.core.views import (
    BOARD_VIEW_TYPE, HARDWARE_BASE_PATH, RUNS_BASE_PATH, RUNS_BOARD_HERE_PATH, RUNS_BOARD_PATH, RUNS_HERE_BASE_PATH,
    SECRETS_BASE_PATH, VIEWS,
)


def test_existing_bases_without_grouping_render_exactly_as_before():
    text = VIEWS[HARDWARE_BASE_PATH]
    assert text.startswith('filters:\n  and:\n    - bastet == "facts"\n    - installed_in == this\nviews:\n')
    assert "filters:" not in text.split("views:")[1] and "groupBy" not in text


def test_group_by_is_the_documented_map_in_the_secrets_base():
    text = VIEWS[SECRETS_BASE_PATH]
    assert "groupBy:\n      property: role\n      direction: ASC\n" in text and "groupBy: role" not in text


def test_all_four_runs_bases_are_known():
    for path in (RUNS_BASE_PATH, RUNS_HERE_BASE_PATH, RUNS_BOARD_PATH, RUNS_BOARD_HERE_PATH):
        assert path in VIEWS


def test_runs_base_has_the_four_views_in_order_with_filters_and_newest_first():
    text = VIEWS[RUNS_BASE_PATH]
    assert text.startswith('filters:\n  and:\n    - bastet == "run"\n')
    names = [line.split(": ", 1)[1] for line in text.splitlines() if line.strip().startswith("name: ")]
    assert names == ["Changes", "Checks", "Failures", "All runs"]
    changes = text.split("name: Changes")[1].split("name: Checks")[0]
    assert 'mode == "apply"' in changes and 'mode == "gather"' in changes and 'status == "failed"' in changes and "or:" in changes
    assert 'mode == "check"' in text.split("name: Checks")[1].split("name: Failures")[0]
    assert text.count("direction: DESC") == 4 and "property: started" in text
    assert "hosts.contains(this.host)" not in text


def test_the_per_host_base_filters_on_the_host():
    assert "hosts.contains(this.host)" in VIEWS[RUNS_HERE_BASE_PATH]
    assert "hosts.contains(this.host)" in VIEWS[RUNS_BOARD_HERE_PATH]


def test_the_board_groups_by_status_using_one_constant():
    text = VIEWS[RUNS_BOARD_PATH]
    assert f"type: {BOARD_VIEW_TYPE}" in text and "name: Board" in text
    assert "formulas:\n  outcome: note.status\n" in text
    assert "groupBy:\n      property: formula.outcome\n      direction: ASC\n" in text and "property: status" not in text
