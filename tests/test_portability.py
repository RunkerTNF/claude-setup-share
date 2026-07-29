from __future__ import annotations

from pathlib import Path

import pytest

from agent_workflow.portability import lint_skill


def write_skill(skill: Path, body: str, *, name: str = "review") -> None:
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Review code changes.\n---\n\n{body}",
        encoding="utf-8",
    )


def test_portable_skill_accepts_standard_core_with_packaged_reference(tmp_path: Path) -> None:
    skill = tmp_path / "review"
    write_skill(skill, "Read references/checklist.md.")
    reference = skill / "references" / "checklist.md"
    reference.parent.mkdir()
    reference.write_text("- Check behavior\n", encoding="utf-8")

    assert lint_skill(skill) == ()


def test_portable_skill_accepts_bare_packaged_reference(tmp_path: Path) -> None:
    skill = tmp_path / "review"
    write_skill(skill, "Read checklist.md.")
    (skill / "checklist.md").write_text("- Check behavior\n", encoding="utf-8")

    assert lint_skill(skill) == ()


def test_lint_reports_missing_bare_packaged_reference(tmp_path: Path) -> None:
    skill = tmp_path / "review"
    write_skill(skill, "Read checklist.md.")

    assert [item.code for item in lint_skill(skill)] == ["portable.reference-missing"]


def test_ordinary_prose_filename_is_not_treated_as_a_packaged_reference(tmp_path: Path) -> None:
    skill = tmp_path / "review"
    write_skill(skill, "The example filename checklist.md documents the expected naming convention.")

    assert lint_skill(skill) == ()


def test_vendor_syntax_is_rejected_from_core_with_stable_codes(tmp_path: Path) -> None:
    skill = tmp_path / "review"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code.\nallowed-tools: Bash\n---\n\n"
        "Use ${CLAUDE_SKILL_DIR}.\n",
        encoding="utf-8",
    )

    assert {item.code for item in lint_skill(skill)} == {
        "portable.frontmatter",
        "portable.vendor-token",
    }


def test_unbraced_vendor_environment_token_is_rejected(tmp_path: Path) -> None:
    skill = tmp_path / "review"
    write_skill(skill, "Read $CLAUDE_PLUGIN_ROOT/references/checklist.md.")

    assert [item.code for item in lint_skill(skill)] == ["portable.vendor-token"]


def test_concrete_native_configuration_path_is_rejected_without_prose_name_false_positive(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "review"
    write_skill(skill, "Claude can read .claude/settings.json when native configuration is needed.")

    assert [item.code for item in lint_skill(skill)] == ["portable.vendor-token"]


def test_lint_rejects_missing_and_unsafe_references(tmp_path: Path) -> None:
    skill = tmp_path / "review"
    write_skill(skill, "Read references/missing.md and ../private.md.")

    diagnostics = lint_skill(skill)

    assert {item.code for item in diagnostics} == {
        "portable.reference-missing",
        "portable.reference-unsafe",
    }


def test_lint_reports_reference_cycles_between_packaged_markdown(tmp_path: Path) -> None:
    skill = tmp_path / "review"
    write_skill(skill, "Read references/first.md.")
    references = skill / "references"
    references.mkdir()
    (references / "first.md").write_text("See [second](second.md).\n", encoding="utf-8")
    (references / "second.md").write_text("See [first](first.md).\n", encoding="utf-8")

    assert [item.code for item in lint_skill(skill)] == ["portable.reference-cycle"]


def test_lint_rejects_referenced_non_python_script(tmp_path: Path) -> None:
    skill = tmp_path / "review"
    write_skill(skill, "Run scripts/check.sh deterministically.")
    scripts = skill / "scripts"
    scripts.mkdir()
    (scripts / "check.sh").write_text("#!/bin/sh\necho check\n", encoding="utf-8")

    assert [item.code for item in lint_skill(skill)] == ["portable.script"]


def test_lint_never_follows_an_escaping_reference_symlink(tmp_path: Path) -> None:
    skill = tmp_path / "review"
    write_skill(skill, "Read references/external.md.")
    references = skill / "references"
    references.mkdir()
    outside = tmp_path / "external.md"
    outside.write_text("outside\n", encoding="utf-8")
    try:
        (references / "external.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    assert [item.code for item in lint_skill(skill)] == ["portable.reference-unsafe"]
