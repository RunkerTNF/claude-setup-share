import json

import pytest

from agent_workflow.model import Ownership
from agent_workflow.plan import DeleteOperation, TransactionPlan, WriteOperation


def test_binary_write_round_trip() -> None:
    operation = WriteOperation.from_bytes(
        root_id="neutral",
        path="workflow/agent-workflow.pyz",
        content=b"\x00zip",
        expected_sha256=None,
        ownership=Ownership.GENERATED,
    )
    plan = TransactionPlan.new(
        scope_root="/tmp/home/.agents",
        target_roots={"neutral": "/tmp/home/.agents", "scope": "/tmp/home"},
        allowed_roots=("/tmp/home",),
        operations=(operation,),
    )
    restored = TransactionPlan.from_json(plan.to_json())
    assert restored.operations[0].content_bytes() == b"\x00zip"


def test_delete_round_trip_is_tagged() -> None:
    operation = DeleteOperation(
        root_id="scope",
        path="legacy/CLAUDE.md",
        expected_sha256="a" * 64,
        ownership=Ownership.GENERATED,
    )
    plan = TransactionPlan.new(
        scope_root="/tmp/project/.agents",
        target_roots={"neutral": "/tmp/project/.agents", "scope": "/tmp/project"},
        allowed_roots=("/tmp/project",),
        operations=(operation,),
    )

    restored = TransactionPlan.from_json(plan.to_json())

    assert isinstance(restored.operations[0], DeleteOperation)
    assert restored.operations[0].path == "legacy/CLAUDE.md"


def test_plan_id_is_deterministic_and_target_roots_are_immutable() -> None:
    roots = {"scope": "/tmp/project", "neutral": "/tmp/project/.agents"}
    first = TransactionPlan.new(
        scope_root="/tmp/project/.agents",
        target_roots=roots,
        allowed_roots=("/tmp/project",),
        operations=(),
    )
    second = TransactionPlan.new(
        scope_root="/tmp/project/.agents",
        target_roots={"neutral": "/tmp/project/.agents", "scope": "/tmp/project"},
        allowed_roots=("/tmp/project",),
        operations=(),
    )
    roots["scope"] = "/elsewhere"

    assert first.plan_id == second.plan_id
    assert dict(first.target_roots) == {
        "neutral": "/tmp/project/.agents",
        "scope": "/tmp/project",
    }
    with pytest.raises(TypeError):
        first.target_roots["scope"] = "/elsewhere"
    assert "created_at" not in json.loads(first.to_json())


def test_plan_json_rejects_unknown_keys_and_unsafe_or_duplicate_targets() -> None:
    operation = WriteOperation.from_bytes(
        root_id="neutral",
        path="a.txt",
        content=b"a",
        expected_sha256=None,
        ownership=Ownership.GENERATED,
    )
    plan = TransactionPlan.new(
        scope_root="/tmp/project/.agents",
        target_roots={"neutral": "/tmp/project/.agents", "scope": "/tmp/project"},
        allowed_roots=("/tmp/project",),
        operations=(operation,),
    )
    payload = json.loads(plan.to_json())
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="unknown plan keys"):
        TransactionPlan.from_json(json.dumps(payload))

    payload.pop("unexpected")
    payload["operations"][0]["path"] = r"C:\\escape.txt"
    with pytest.raises(ValueError, match="safe relative path"):
        TransactionPlan.from_json(json.dumps(payload))


def test_plan_rejects_invalid_hash_and_missing_delete_hash() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        DeleteOperation(
            root_id="scope",
            path="legacy/CLAUDE.md",
            expected_sha256="ABC",
            ownership=Ownership.GENERATED,
        )

    payload = {
        "schema_version": 1,
        "plan_id": "5ba04cd0-2a5d-5971-861f-6cc47d88b87e",
        "scope_root": "/tmp/project/.agents",
        "target_roots": {"neutral": "/tmp/project/.agents", "scope": "/tmp/project"},
        "allowed_roots": ["/tmp/project"],
        "operations": [
            {
                "kind": "delete",
                "root_id": "scope",
                "path": "legacy/CLAUDE.md",
                "expected_sha256": None,
                "ownership": "generated",
            }
        ],
        "conflicts": [],
        "warnings": [],
    }
    with pytest.raises(ValueError, match="delete operation requires an expected SHA-256"):
        TransactionPlan.from_json(json.dumps(payload))
