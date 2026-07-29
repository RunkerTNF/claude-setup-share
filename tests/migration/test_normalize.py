from __future__ import annotations

from pathlib import Path

from agent_workflow.migration.model import ArtifactKind
from agent_workflow.migration.normalize import (
    NormalizationBatch,
    merge_memory_index,
    normalize_deterministic,
    resolve_normalized_collisions,
)
from tests.migration.helpers import (
    claude_command_fixture,
    memory_fixture,
    standard_skill_fixture,
)


def test_standard_skill_is_copied_byte_for_byte(tmp_path: Path) -> None:
    record, source = standard_skill_fixture(tmp_path, name="wrap")

    normalized = normalize_deterministic(record, source)

    assert normalized is not None
    assert normalized.kind is ArtifactKind.SKILL
    assert normalized.root_id == "neutral"
    assert normalized.relative_destination == "skills/wrap"
    assert normalized.files["SKILL.md"] == (source / "SKILL.md").read_bytes()
    assert normalized.files["references/checklist.md"] == (
        source / "references" / "checklist.md"
    ).read_bytes()
    assert normalized.adopt_existing is True


def test_claude_command_becomes_a_portable_skill(tmp_path: Path) -> None:
    record, source = claude_command_fixture(
        tmp_path,
        name="pick",
        body="Resolve a backlog item and start it.",
    )

    normalized = normalize_deterministic(record, source)

    assert normalized is not None
    assert normalized.root_id == "neutral"
    assert normalized.relative_destination == "skills/pick"
    text = normalized.files["SKILL.md"].decode()
    assert "name: pick" in text
    assert "description: Resolve a backlog item and start it." in text
    assert "Resolve a backlog item and start it." in text
    assert ".claude" not in text


def test_manual_memory_keeps_provenance_and_source_hash(
    tmp_path: Path,
) -> None:
    record, source = memory_fixture(tmp_path, "preferences.md")

    normalized = normalize_deterministic(record, source)

    assert normalized is not None
    assert normalized.root_id == "neutral"
    assert normalized.relative_destination.startswith("memory/")
    assert normalized.provenance.source_sha256 == record.sha256
    assert normalized.provenance.source_agent == record.agent_id
    text = normalized.files[normalized.destination_name].decode()
    assert f"source-sha256: {record.sha256}" in text
    assert "Prefer reversible changes." in text


def test_memory_index_is_sorted_and_idempotent(tmp_path: Path) -> None:
    first_record, first_source = memory_fixture(tmp_path / "one", "zeta.md")
    second_record, second_source = memory_fixture(
        tmp_path / "two", "alpha.md"
    )
    first = normalize_deterministic(first_record, first_source)
    second = normalize_deterministic(second_record, second_source)

    output = merge_memory_index((first, second))

    assert output == merge_memory_index((second, first))
    assert output.index(b"alpha-from-codex.md") < output.index(
        b"zeta-from-codex.md"
    )
    assert first_record.sha256.encode() in output
    assert second_record.sha256.encode() in output


def test_different_collision_is_suffixed_and_remains_blocking(
    tmp_path: Path,
) -> None:
    first_record, first_source = claude_command_fixture(
        tmp_path / "one", name="pick", body="Pick the first item."
    )
    second_record, second_source = claude_command_fixture(
        tmp_path / "two", name="pick", body="Pick the second item."
    )
    first = normalize_deterministic(first_record, first_source)
    second = normalize_deterministic(second_record, second_source)

    batch = resolve_normalized_collisions((first, second))

    assert {
        item.relative_destination for item in batch.artifacts
    } == {"skills/pick", "skills/pick-from-claude"}
    assert len(batch.conflicts) == 1
    assert batch.deduplications == ()


def test_normalization_batch_round_trips_without_absolute_paths(
    tmp_path: Path,
) -> None:
    record, source = claude_command_fixture(
        tmp_path,
        name="pick",
        body="Pick one item.\n",
    )
    batch = resolve_normalized_collisions(
        (normalize_deterministic(record, source),)
    )

    serialized = batch.to_json()
    restored = NormalizationBatch.from_json(serialized)

    assert restored.to_json() == serialized
    assert str(tmp_path) not in serialized
