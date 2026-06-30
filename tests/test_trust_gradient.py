"""TDD for HARNESS/trust_gradient.py: the Exp2 command-level trust-property gradient.

The pilot result. Across the constraint gradient (free_agent -> skill_reasoning -> skill_execution),
trust properties (pinning, provenance, auditability) climb while plan validity stays constant. Computed
deterministically from the emitted workflow text, so it needs no execution. Scorers are injected so the
aggregation is testable in isolation.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS")]

import trust_gradient as TG  # noqa: E402

# two arms, two reps each; emitted text is opaque to the aggregator (the injected scorers read it)
_ROWS = [
    {"arm": "free_agent", "rep": 0, "model": "m", "sample": "HG002",
     "pinned": False, "provenance_emitted": False, "vet_accepted": False, "emitted": "free0"},
    {"arm": "free_agent", "rep": 1, "model": "m", "sample": "HG002",
     "pinned": False, "provenance_emitted": False, "vet_accepted": False, "emitted": "free1"},
    {"arm": "skill_reasoning", "rep": 0, "model": "m", "sample": "HG002",
     "pinned": True, "provenance_emitted": True, "vet_accepted": False, "emitted": "skill0"},
    {"arm": "skill_reasoning", "rep": 1, "model": "m", "sample": "HG002",
     "pinned": False, "provenance_emitted": True, "vet_accepted": False, "emitted": "skill1"},
]


def _plan_stub(text):   # constant-valid, the real finding
    return "valid_plan"


def _inject_stub(text):
    return "clean"


def test_aggregate_counts_per_arm():
    agg = TG.aggregate_arms(_ROWS, plan_fn=_plan_stub, inject_fn=_inject_stub)
    assert agg["free_agent"]["n"] == 2
    assert agg["free_agent"]["pinned"] == 0
    assert agg["free_agent"]["provenance"] == 0
    assert agg["free_agent"]["auditable"] == 0
    assert agg["skill_reasoning"]["n"] == 2
    assert agg["skill_reasoning"]["pinned"] == 1          # 1 of 2
    assert agg["skill_reasoning"]["provenance"] == 2      # both
    assert agg["skill_reasoning"]["auditable"] == 0


def test_aggregate_collects_plan_and_injection_labels():
    agg = TG.aggregate_arms(_ROWS, plan_fn=_plan_stub, inject_fn=_inject_stub)
    assert agg["free_agent"]["plan_labels"] == {"valid_plan"}
    assert agg["free_agent"]["injection_labels"] == {"clean"}


def test_aggregate_orders_arms_by_constraint():
    # the gradient must present arms in increasing-constraint order for the table to read correctly
    agg = TG.aggregate_arms(_ROWS, plan_fn=_plan_stub, inject_fn=_inject_stub)
    order = list(agg.keys())
    assert order.index("free_agent") < order.index("skill_reasoning")


def test_render_markdown_is_deterministic_and_cites_caveats():
    agg = TG.aggregate_arms(_ROWS, plan_fn=_plan_stub, inject_fn=_inject_stub)
    md = TG.render_markdown(agg, skill_summary={"f1": 0.9906, "reproducible": True},
                            model="claude-sonnet-4-5", sample="HG002")
    assert "free_agent" in md and "skill_reasoning" in md
    assert "0.9906" in md
    # honest scope must be in the artifact, not just the chat
    assert "unmeasured" in md.lower()
    assert "n=2" in md or "n=3" in md or "per arm" in md.lower()


def test_parse_ancestry_table():
    rows = TG.parse_ancestry_table(
        "sample\tancestry\tprecision\trecall\tF1\tTP\tFP\tFN\tprovenance_hash\n"
        "HG002\tAJ\t0.9902\t0.9909\t0.9906\t81835\t807\t754\tabc123\n")
    assert rows[0]["sample"] == "HG002"
    assert abs(rows[0]["F1"] - 0.9906) < 1e-9
    assert rows[0]["FP"] == 807
