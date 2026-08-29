from __future__ import annotations

import pytest

from nemofold.smart_inbox import RoutingRule, apply_move, plan_inbox, undo_move
from nemofold.storage_policy import PolicyRule, PolicySet


def test_inbox_plan_requires_confirmation_and_is_reversible(tmp_path) -> None:
    root = tmp_path / "home"
    inbox = root / "inbox"
    pdfs = root / "documents"
    inbox.mkdir(parents=True)
    pdfs.mkdir()
    source = inbox / "policy.pdf"
    source.write_bytes(b"synthetic pdf")
    policies = PolicySet(
        rules=(PolicyRule(scope=root, allowed_extensions=(".pdf",)),)
    )

    plans = plan_inbox(
        (source,),
        rules=(RoutingRule(suffixes=(".pdf",), target_dir=pdfs),),
        policies=policies,
    )

    assert len(plans) == 1 and plans[0].allowed is True
    with pytest.raises(PermissionError):
        apply_move(plans[0], approved=False)

    receipt = apply_move(plans[0], approved=True)
    assert source.exists() is False
    assert (pdfs / "policy.pdf").exists() is True
    assert receipt.status == "available"

    undo_move(receipt, approved=True)
    assert source.exists() is True
    assert (pdfs / "policy.pdf").exists() is False


def test_inbox_keeps_unmatched_file_as_explicitly_blocked_plan(tmp_path) -> None:
    root = tmp_path / "home"
    inbox = root / "inbox"
    target = root / "documents"
    inbox.mkdir(parents=True)
    target.mkdir()
    source = inbox / "photo.jpg"
    source.write_bytes(b"image")

    plans = plan_inbox(
        (source,),
        rules=(RoutingRule(suffixes=(".pdf",), target_dir=target),),
        policies=PolicySet(rules=(PolicyRule(scope=root),)),
    )

    assert plans[0].allowed is False
    assert plans[0].reasons == ("no_matching_route",)
