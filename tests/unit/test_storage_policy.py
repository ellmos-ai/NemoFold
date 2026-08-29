from __future__ import annotations

from nemofold.storage_policy import PolicyRule, PolicySet, preview_storage


def test_most_specific_policy_overrides_global_rule(tmp_path) -> None:
    root = tmp_path / "home"
    insurance = root / "insurance"
    insurance.mkdir(parents=True)
    source = insurance / "Policy.PDF"
    source.write_bytes(b"synthetic")
    policies = PolicySet(
        rules=(
            PolicyRule(scope=root, naming_template="{stem}{suffix}"),
            PolicyRule(
                scope=insurance,
                naming_template="current_{stem}{suffix}",
                allowed_extensions=(".pdf",),
            ),
        )
    )

    resolved = policies.resolve(source)

    assert resolved.scope == insurance.resolve()
    assert resolved.render_name(source) == "current_Policy.pdf"


def test_preview_blocks_collision_disallowed_type_and_hard_delete(tmp_path) -> None:
    source = tmp_path / "incoming" / "note.txt"
    target_dir = tmp_path / "archive"
    source.parent.mkdir()
    target_dir.mkdir()
    source.write_text("hello", encoding="utf-8")
    (target_dir / "note.txt").write_text("existing", encoding="utf-8")

    collision = preview_storage(source, target_dir, PolicyRule(scope=tmp_path))
    wrong_type = preview_storage(
        source,
        target_dir,
        PolicyRule(scope=tmp_path, allowed_extensions=(".pdf",)),
    )
    hard_delete = preview_storage(
        source,
        target_dir,
        PolicyRule(scope=tmp_path, retention_action="hard_delete"),
    )

    assert collision.allowed is False and "target_collision" in collision.reasons
    assert wrong_type.allowed is False and "extension_not_allowed" in wrong_type.reasons
    assert hard_delete.allowed is False and "hard_delete_disabled" in hard_delete.reasons
