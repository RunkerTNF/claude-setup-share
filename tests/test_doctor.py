from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict
import hashlib
import json
from pathlib import Path

import pytest

from agent_workflow.doctor import Diagnostic, run_doctor
from agent_workflow.model import Severity


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_manifest(root: Path, *, generated_files: dict[str, str], bootstrap_root: str | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generator_version": "0.1.0",
                "scope": "global",
                "profile": None,
                "targets": [],
                "generated_files": generated_files,
                "bootstrap_root": bootstrap_root,
            }
        ),
        encoding="utf-8",
    )


def write_core(root: Path) -> None:
    (root / "RULES.md").write_text("rules\n", encoding="utf-8")
    memory = root / "memory" / "MEMORY.md"
    memory.parent.mkdir()
    memory.write_text("memory\n", encoding="utf-8")


def test_diagnostic_is_immutable_and_json_friendly() -> None:
    diagnostic = Diagnostic(Severity.BLOCKING, "example.code", "path", "message")

    with pytest.raises(FrozenInstanceError):
        diagnostic.code = "changed"  # type: ignore[misc]
    assert asdict(diagnostic) == {
        "severity": Severity.BLOCKING,
        "code": "example.code",
        "path": "path",
        "message": "message",
    }


def test_doctor_reports_missing_and_drifted_canonical_generated_files(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    write_manifest(
        root,
        generated_files={
            "neutral:entry.md": "a" * 64,
            "neutral:missing.md": "b" * 64,
        },
    )
    write_core(root)
    (root / "entry.md").write_text("changed\n", encoding="utf-8")

    diagnostics = run_doctor(root)

    assert {item.code for item in diagnostics} >= {"generated.drift", "generated.missing"}


def test_doctor_returns_diagnostic_for_invalid_manifest_without_raising(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    (root / "manifest.json").write_text("not json", encoding="utf-8")

    assert {item.code for item in run_doctor(root)} == {"manifest.invalid", "core.missing"}


def test_doctor_reports_missing_required_core_files(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    write_manifest(root, generated_files={})

    assert {item.code for item in run_doctor(root)} == {"core.missing"}


def test_doctor_excludes_manifest_and_ephemeral_bootstrap_references(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    bootstrap = str(tmp_path / "disposable-bootstrap")
    write_manifest(root, generated_files={}, bootstrap_root=bootstrap)
    write_core(root)
    for relative_path in (
        "workflow/backups/old.md",
        "workflow/journals/old.md",
        "workflow/staging/old.md",
        "workflow/locks/old.md",
    ):
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(bootstrap, encoding="utf-8")

    assert run_doctor(root) == ()


def test_doctor_scans_user_skill_path_named_backups_for_bootstrap_reference(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    bootstrap = str(tmp_path / "disposable-bootstrap")
    write_manifest(root, generated_files={}, bootstrap_root=bootstrap)
    write_core(root)
    skill_file = root / "skills" / "backup-guide" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        "---\nname: backup-guide\ndescription: Describe backups.\n---\n",
        encoding="utf-8",
    )
    example = root / "skills" / "backup-guide" / "backups" / "example.md"
    example.parent.mkdir(parents=True)
    example.write_text(bootstrap, encoding="utf-8")

    assert [item.code for item in run_doctor(root)] == ["bootstrap.reference"]


def test_doctor_scans_non_transaction_lock_file_for_bootstrap_reference(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    bootstrap = str(tmp_path / "disposable-bootstrap")
    write_manifest(root, generated_files={}, bootstrap_root=bootstrap)
    write_core(root)
    (root / "notes.lock").write_text(bootstrap, encoding="utf-8")

    assert [item.code for item in run_doctor(root)] == ["bootstrap.reference"]


def test_doctor_detects_normalized_bootstrap_reference_in_generated_text(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    bootstrap = str(tmp_path / "Disposable-Bootstrap")
    write_manifest(
        root,
        generated_files={"neutral:entry.md": sha256(bootstrap.lower().replace("\\", "/"))},
        bootstrap_root=bootstrap,
    )
    write_core(root)
    (root / "entry.md").write_text(bootstrap.lower().replace("\\", "/"), encoding="utf-8")

    assert [item.code for item in run_doctor(root)] == ["bootstrap.reference"]


def test_doctor_detects_bootstrap_reference_in_generated_scope_file(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    bootstrap = str(tmp_path / "disposable-bootstrap")
    entry = tmp_path / "AGENTS.md"
    entry.write_text(bootstrap, encoding="utf-8")
    write_manifest(
        root,
        generated_files={"scope:AGENTS.md": sha256(bootstrap)},
        bootstrap_root=bootstrap,
    )
    write_core(root)

    assert [item.code for item in run_doctor(root)] == ["bootstrap.reference"]


def test_doctor_detects_bootstrap_reference_in_extensionless_generated_scope_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".agents"
    bootstrap = str(tmp_path / "disposable-bootstrap")
    entry = tmp_path / "INSTRUCTIONS"
    entry.write_text(bootstrap, encoding="utf-8")
    write_manifest(
        root,
        generated_files={"scope:INSTRUCTIONS": sha256(bootstrap)},
        bootstrap_root=bootstrap,
    )
    write_core(root)

    assert [item.code for item in run_doctor(root)] == ["bootstrap.reference"]


def test_doctor_skips_oversized_file_without_full_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / ".agents"
    bootstrap = str(tmp_path / "disposable-bootstrap")
    write_manifest(root, generated_files={}, bootstrap_root=bootstrap)
    write_core(root)
    oversized = root / "oversized.md"
    oversized.write_bytes(b"x" * (1024 * 1024 + 1))
    original_read_bytes = Path.read_bytes

    def fail_if_oversized(path: Path) -> bytes:
        if path == oversized:
            raise AssertionError("oversized file must not be fully read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_if_oversized)

    assert run_doctor(root) == ()


def test_doctor_reports_escaping_managed_symlink_without_reading_it(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    try:
        (root / "entry.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    write_manifest(root, generated_files={"neutral:entry.md": sha256("outside\n")})
    write_core(root)

    assert "generated.path" in {item.code for item in run_doctor(root)}


def test_doctor_lints_children_in_order_and_does_not_mutate_state(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    write_manifest(root, generated_files={})
    write_core(root)
    skills = root / "skills"
    skills.mkdir()
    (skills / "00-not-directory").write_text("not a skill", encoding="utf-8")
    invalid = skills / "z-last"
    invalid.mkdir()
    (invalid / "SKILL.md").write_text("not frontmatter", encoding="utf-8")
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    first = run_doctor(root)
    second = run_doctor(root)

    assert first == second
    assert list(first) == sorted(first, key=lambda item: (item.path, item.code, item.message))
    assert {item.code for item in first} == {"portable.frontmatter", "skills.invalid-entry"}
    after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert after == before


def test_doctor_reports_invalid_transaction_journal(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".agents"
    write_manifest(root, generated_files={})
    write_core(root)
    journal = root / "workflow" / "journals" / "broken.json"
    journal.parent.mkdir(parents=True)
    journal.write_text("{broken", encoding="utf-8")

    diagnostics = run_doctor(root)

    assert [item.code for item in diagnostics] == [
        "transaction.journal-invalid"
    ]


def test_doctor_warns_when_selected_adapter_is_unavailable(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".agents"
    write_manifest(root, generated_files={})
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    payload["targets"] = ["missing-agent"]
    (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    write_core(root)

    diagnostics = run_doctor(root)

    unavailable = next(
        item for item in diagnostics if item.code == "adapter.unavailable"
    )
    assert unavailable.severity is Severity.WARNING


def test_doctor_validates_selected_builtin_entrypoint(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    write_manifest(root, generated_files={})
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    payload["targets"] = ["codex"]
    (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    write_core(root)

    diagnostics = run_doctor(root)

    missing = next(
        item
        for item in diagnostics
        if item.code == "adapter.entrypoint-missing"
    )
    assert missing.severity is Severity.CONFLICT
