"""Project sharing policies and managed ignore-file blocks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .adapters.rendered import safe_current_hash
from .model import Ownership, ProjectProfile
from .plan import WriteOperation


_BEGIN = "# BEGIN agent-workflow"
_END = "# END agent-workflow"


@dataclass(frozen=True)
class ProfilePolicy:
    profile: ProjectProfile
    gitignore_entries: tuple[str, ...]
    share_rules: bool
    share_memory: bool
    share_sessions: bool
    share_skills: bool


_POLICIES = {
    ProjectProfile.LOCAL: ProfilePolicy(
        profile=ProjectProfile.LOCAL,
        gitignore_entries=(
            ".agents/",
            "AGENTS.override.md",
            "CLAUDE.local.md",
        ),
        share_rules=False,
        share_memory=False,
        share_sessions=False,
        share_skills=False,
    ),
    ProjectProfile.SHARED: ProfilePolicy(
        profile=ProjectProfile.SHARED,
        gitignore_entries=(),
        share_rules=True,
        share_memory=True,
        share_sessions=True,
        share_skills=True,
    ),
    ProjectProfile.SPLIT: ProfilePolicy(
        profile=ProjectProfile.SPLIT,
        gitignore_entries=(
            ".agents/memory/",
            ".agents/sessions/",
            ".agents/overlays/",
            "AGENTS.override.md",
            "CLAUDE.local.md",
        ),
        share_rules=True,
        share_memory=False,
        share_sessions=False,
        share_skills=True,
    ),
}


def policy_for(profile: ProjectProfile) -> ProfilePolicy:
    """Return the immutable sharing policy for a project profile."""
    if not isinstance(profile, ProjectProfile):
        raise ValueError("project profile must be valid")
    return _POLICIES[profile]


def render_managed_ignore(existing: str, policy: ProfilePolicy) -> str:
    """Replace the agent-workflow block while preserving unrelated content."""
    if not isinstance(existing, str):
        raise ValueError("existing ignore content must be text")
    if not isinstance(policy, ProfilePolicy):
        raise ValueError("profile policy must be valid")

    lines = existing.splitlines(keepends=True)
    begin = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\r\n") == _BEGIN
    ]
    end = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\r\n") == _END
    ]
    if len(begin) != len(end) or len(begin) > 1:
        raise ValueError("invalid managed ignore block")
    if begin and begin[0] >= end[0]:
        raise ValueError("invalid managed ignore block")

    newline = "\r\n" if "\r\n" in existing else "\n"
    block = _render_block(policy, newline)
    if begin:
        return "".join(lines[: begin[0]]) + block + "".join(lines[end[0] + 1 :])
    if not block:
        return existing
    separator = "" if not existing or existing.endswith(("\n", "\r")) else newline
    return existing + separator + block


def plan_profile_files(
    project_root: Path,
    profile: ProjectProfile,
    manage_syncprotect: bool,
) -> tuple[WriteOperation, ...]:
    """Plan full-file writes for managed project ignore blocks."""
    project_root = Path(project_root)
    if (
        not project_root.is_absolute()
        or not project_root.is_dir()
        or project_root.is_symlink()
    ):
        raise ValueError("project root must be a safe existing directory")
    if not isinstance(manage_syncprotect, bool):
        raise ValueError("manage_syncprotect must be boolean")

    policy = policy_for(profile)
    operations: list[WriteOperation] = []
    for relative_path in (".gitignore", ".syncprotect"):
        target = project_root / relative_path
        if (
            relative_path == ".syncprotect"
            and not manage_syncprotect
            and not target.exists()
        ):
            continue
        existing = _read_existing_text(target, project_root)
        rendered = render_managed_ignore(existing, policy)
        if rendered == existing:
            continue
        operations.append(
            WriteOperation.from_bytes(
                root_id="scope",
                path=relative_path,
                content=rendered.encode("utf-8"),
                expected_sha256=safe_current_hash(target, project_root),
                ownership=Ownership.GENERATED,
            )
        )
    return tuple(operations)


def _render_block(policy: ProfilePolicy, newline: str) -> str:
    if not policy.gitignore_entries:
        return ""
    return newline.join(
        (_BEGIN, *policy.gitignore_entries, _END, "")
    )


def _read_existing_text(target: Path, project_root: Path) -> str:
    safe_current_hash(target, project_root)
    try:
        return target.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeError as error:
        raise ValueError(f"managed ignore file is not UTF-8: {target}") from error
    except OSError as error:
        raise ValueError(f"cannot read managed ignore file: {target}") from error
