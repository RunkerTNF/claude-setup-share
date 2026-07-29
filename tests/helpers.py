from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from agent_workflow.doctor import run_doctor
from agent_workflow.model import ProjectProfile, Scope
from agent_workflow.portability import parse_portable_skill_frontmatter
from agent_workflow.setup import SetupRequest, build_setup_plan
from agent_workflow.transactions import apply_plan


_EPHEMERAL_PARTS = (
    (".agents", "workflow", "backups"),
    (".agents", "workflow", "journals"),
    (".agents", "workflow", "staging"),
    (".agents", "workflow", "locks"),
    (".git",),
)
_BACKLOG_TAG = re.compile(
    r"\[(?:backlog(?::[a-z-]+)?|no-backlog)\]"
)


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    description: str
    body: str
    emitted_tags: frozenset[str]
    accepted_tags: frozenset[str]


def load_skill(repo_root: Path, name: str) -> LoadedSkill:
    source = (
        repo_root / "skills" / name / "SKILL.md"
    ).read_text(encoding="utf-8")
    parsed_name, description, body = parse_portable_skill_frontmatter(
        source
    )
    return LoadedSkill(
        name=parsed_name,
        description=description,
        body=body,
        emitted_tags=_section_tags(body, "Emitted backlog tags"),
        accepted_tags=_section_tags(body, "Accepted backlog tags"),
    )


def _section_tags(body: str, heading: str) -> frozenset[str]:
    match = re.search(
        rf"(?ms)^## {re.escape(heading)}\s*$"
        r"(?P<section>.*?)(?=^## |\Z)",
        body,
    )
    if match is None:
        return frozenset()
    return frozenset(
        _BACKLOG_TAG.findall(match.group("section"))
    )


def materialize_bootstrap_repo(destination: Path) -> Path:
    source = Path(__file__).resolve().parents[1]
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".pytest_cache",
            ".venv",
            ".worktrees",
            "__pycache__",
            "*.pyc",
        ),
    )
    return destination


def run_bootstrap(
    clone: Path,
    *,
    home: Path,
    targets: tuple[str, ...] = (),
    apply: bool = False,
    extra_args: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(clone / "scripts" / "bootstrap.py"),
        "--home",
        str(home),
    ]
    for target in targets:
        command.extend(("--target", target))
    if apply:
        command.extend(("--apply", "--yes"))
    command.extend(extra_args)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return subprocess.run(
        command,
        cwd=clone,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def run_installed_manager(
    home: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    archive = home / ".agents" / "workflow" / "agent-workflow.pyz"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            str(archive),
            *arguments,
            "--home",
            str(home),
        ],
        cwd=home.parent,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
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


def update_tree_golden(actual: Path, expected: Path) -> None:
    actual_files = _tree_files(actual)
    expected_files = _tree_files(expected) if expected.is_dir() else {}
    for relative_path in sorted(set(expected_files) - set(actual_files)):
        (expected / relative_path).unlink()

    expected.mkdir(parents=True, exist_ok=True)
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
    for relative_path, content in sorted(actual_files.items()):
        destination = expected / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            destination.write_bytes(content)
            continue
        for source, placeholder in replacements:
            text = text.replace(source, placeholder)
        destination.write_bytes(text.encode("utf-8"))


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
