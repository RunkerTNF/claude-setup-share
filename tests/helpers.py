from __future__ import annotations

from pathlib import Path

from agent_workflow.doctor import run_doctor
from agent_workflow.model import ProjectProfile, Scope
from agent_workflow.setup import SetupRequest, build_setup_plan
from agent_workflow.transactions import apply_plan


_EPHEMERAL_PARTS = (
    (".agents", "workflow", "backups"),
    (".agents", "workflow", "journals"),
    (".agents", "workflow", "staging"),
    (".agents", "workflow", "locks"),
    (".git",),
)


def apply_setup_fixture(
    tmp_path: Path,
    *,
    agent: str,
    profile: str | None,
) -> Path:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    source = Path.cwd()
    global_request = SetupRequest(
        home=home,
        project_root=None,
        source_root=source,
        scope=Scope.GLOBAL,
        profile=None,
        targets=(agent,),
        manage_syncprotect=False,
        adapter_sources=(),
        trusted_adapter_ids=(),
    )
    apply_plan(build_setup_plan(global_request))
    assert run_doctor(home / ".agents") == ()
    if profile is None:
        return home

    project.mkdir()
    (project / ".git").mkdir()
    project_request = SetupRequest(
        home=home,
        project_root=project,
        source_root=source,
        scope=Scope.PROJECT,
        profile=ProjectProfile(profile),
        targets=(agent,),
        manage_syncprotect=False,
        adapter_sources=(),
        trusted_adapter_ids=(),
    )
    apply_plan(build_setup_plan(project_request))
    assert run_doctor(project / ".agents") == ()
    return project


def assert_tree_matches(actual: Path, expected: Path) -> None:
    if not expected.is_dir():
        raise AssertionError(f"missing expected golden tree: {expected}")
    actual_files = _tree_files(actual)
    expected_files = _tree_files(expected)
    assert set(actual_files) == set(expected_files)

    home = actual if actual.name == "home" else actual.parent / "home"
    project = (
        actual if actual.name == "project" else actual.parent / "project"
    )
    replacements = (
        (str(home), "{{HOME}}"),
        (home.as_posix(), "{{HOME}}"),
        (str(project), "{{PROJECT}}"),
        (project.as_posix(), "{{PROJECT}}"),
    )
    for relative_path in sorted(actual_files):
        actual_content = actual_files[relative_path]
        expected_content = expected_files[relative_path]
        try:
            actual_text = actual_content.decode("utf-8")
            expected_text = expected_content.decode("utf-8")
        except UnicodeDecodeError:
            assert actual_content == expected_content, relative_path
            continue
        for source, placeholder in replacements:
            actual_text = actual_text.replace(source, placeholder)
        assert actual_text == expected_text, relative_path


def _tree_files(root: Path) -> dict[str, bytes]:
    output: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        parts = tuple(part.casefold() for part in relative.parts)
        if relative.name == ".workflow.lock" or any(
            parts[: len(prefix)] == prefix
            for prefix in _EPHEMERAL_PARTS
        ):
            continue
        output[relative.as_posix()] = path.read_bytes()
    return output
