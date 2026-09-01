from __future__ import annotations

import pytest

from nemofold.primitives import (
    AggregationBudget,
    Anchor,
    AnchoredStatement,
    aggregate_mapreduce,
    partition_statements,
)


def _statements(*pairs: tuple[str, str, int]) -> tuple[AnchoredStatement, ...]:
    return tuple(
        AnchoredStatement(text=text, anchor=Anchor(source_id=source, line=line))
        for text, source, line in pairs
    )


# --------------------------------------------------------------------------- #
# Partitioning is deterministic by construction
# --------------------------------------------------------------------------- #


def test_partitioning_is_stable_across_runs() -> None:
    statements = _statements(*[(f"Aussage {index}", "akte", index) for index in range(1, 26)])

    first = partition_statements(statements, 10)
    second = partition_statements(statements, 10)

    assert [len(part) for part in first] == [10, 10, 5]
    assert first == second
    # Input order is preserved, so partition 0 always holds the first ten.
    assert first[0][0].text == "Aussage 1"
    assert first[2][-1].text == "Aussage 25"


@pytest.mark.parametrize("size", [0, -1, True])
def test_partition_size_must_be_a_positive_integer(size) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        partition_statements((), size)


# --------------------------------------------------------------------------- #
# Anchors survive both stages
# --------------------------------------------------------------------------- #


def test_anchors_survive_two_stages_and_are_unioned() -> None:
    # The same statement appears three times: twice inside one partition and
    # once in another, so it has to be folded at both stages.
    statements = _statements(
        ("Der Wagen war blau.", "vernehmung-a", 4),
        ("Es regnete am Samstag.", "vernehmung-a", 6),
        ("Der Wagen war blau.", "vernehmung-a", 11),
        ("Der Wagen war blau.", "bericht", 2),
    )

    outcome = aggregate_mapreduce(statements, budget=AggregationBudget(partition_size=3))

    folded = next(item for item in outcome.results if item.text == "Der Wagen war blau.")
    assert folded.support == 3
    assert folded.anchor_total == 3
    assert sorted((a.source_id, a.line) for a in folded.anchors) == [
        ("bericht", 2),
        ("vernehmung-a", 4),
        ("vernehmung-a", 11),
    ]
    # It came from two different partitions, and says so.
    assert folded.partitions == (0, 1)
    assert [stage.name for stage in outcome.stages] == [
        "partition",
        "fold-partition",
        "fold-final",
    ]


def test_an_identical_anchor_is_not_counted_twice() -> None:
    statements = _statements(
        ("Gleiche Zeile.", "akte", 3),
        ("Gleiche Zeile.", "akte", 3),
    )

    outcome = aggregate_mapreduce(statements, budget=AggregationBudget(partition_size=1))

    folded = outcome.results[0]
    assert folded.support == 2
    assert folded.anchor_total == 1
    assert len(folded.anchors) == 1


def test_aggregation_is_deterministic_for_the_same_input() -> None:
    statements = _statements(
        *[(f"Aussage {index % 7}", f"akte-{index % 3}", index) for index in range(1, 40)]
    )

    first = aggregate_mapreduce(statements, budget=AggregationBudget(partition_size=5))
    second = aggregate_mapreduce(statements, budget=AggregationBudget(partition_size=5))

    assert [item.text for item in first.results] == [item.text for item in second.results]
    assert [item.anchors for item in first.results] == [item.anchors for item in second.results]


def test_results_keep_input_order_rather_than_a_ranking() -> None:
    statements = _statements(
        ("Selten gesagt.", "akte", 1),
        ("Oft gesagt.", "akte", 2),
        ("Oft gesagt.", "akte", 3),
        ("Oft gesagt.", "akte", 4),
    )

    outcome = aggregate_mapreduce(statements, budget=AggregationBudget(partition_size=2))

    assert [item.text for item in outcome.results] == ["Selten gesagt.", "Oft gesagt."]


# --------------------------------------------------------------------------- #
# Budgets bite, and say so
# --------------------------------------------------------------------------- #


def test_the_partition_ceiling_reports_what_it_left_out() -> None:
    statements = _statements(*[(f"Aussage {index}", "akte", index) for index in range(1, 21)])

    outcome = aggregate_mapreduce(
        statements, budget=AggregationBudget(partition_size=2, max_partitions=3)
    )

    assert outcome.partition_count == 3
    assert outcome.within_budget is False
    assert "7 partition(s) holding 14 statement(s) were not aggregated" in outcome.notes[0]
    assert outcome.stages[0].dropped == 7


def test_the_result_ceiling_reports_what_it_cut() -> None:
    statements = _statements(*[(f"Aussage {index}", "akte", index) for index in range(1, 11)])

    outcome = aggregate_mapreduce(
        statements, budget=AggregationBudget(partition_size=10, max_results=4)
    )

    assert len(outcome.results) == 4
    assert "6 aggregated statement(s) were cut by the result ceiling of 4" in outcome.notes[0]


def test_the_per_partition_ceiling_reports_what_it_cut() -> None:
    statements = _statements(*[(f"Aussage {index}", "akte", index) for index in range(1, 11)])

    outcome = aggregate_mapreduce(
        statements, budget=AggregationBudget(partition_size=5, max_per_partition=2)
    )

    assert outcome.stages[1].dropped == 6
    assert "cut by the per-partition ceiling of 2" in outcome.notes[0]


def test_a_run_inside_its_budget_reports_nothing() -> None:
    statements = _statements(("Eine Aussage.", "akte", 1))

    outcome = aggregate_mapreduce(statements)

    assert outcome.within_budget is True
    assert outcome.notes == ()


@pytest.mark.parametrize(
    "field", ["partition_size", "max_partitions", "max_per_partition", "max_results"]
)
def test_a_budget_refuses_a_useless_ceiling(field) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        AggregationBudget(**{field: 0})
