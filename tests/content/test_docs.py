from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import unquote


_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
_REMOTE_SCHEMES = ("http://", "https://", "mailto:")
_REQUIRED_DOCS = (
    "architecture.md",
    "adapter-authoring.md",
    "customization.md",
    "project-profiles.md",
    "safety.md",
    "troubleshooting.md",
)


def test_documentation_has_no_broken_local_links(
    repo_root: Path,
) -> None:
    errors = _check_markdown_links(
        repo_root,
        roots=("README.md", "INSTALL.md", "SETUP.md", "docs"),
    )
    assert errors == []


def test_readme_names_guaranteed_and_extensible_support(
    repo_root: Path,
) -> None:
    text = (repo_root / "README.md").read_text(encoding="utf-8")
    assert "Claude Code" in text
    assert "Codex" in text
    assert "adapter" in text.lower()
    assert "Pi" in text
    assert "Cursor" in text
    assert "гарантир" in text.lower() or "guaranteed" in text.lower()


def test_docs_explain_clone_is_disposable(repo_root: Path) -> None:
    for name in ("README.md", "INSTALL.md", "SETUP.md"):
        text = (repo_root / name).read_text(encoding="utf-8")
        assert "удал" in text.lower() or "delete" in text.lower(), name


def test_supporting_docs_cover_public_contract(repo_root: Path) -> None:
    docs = repo_root / "docs"
    for name in _REQUIRED_DOCS:
        assert (docs / name).is_file(), name

    architecture = (docs / "architecture.md").read_text(encoding="utf-8")
    authoring = (docs / "adapter-authoring.md").read_text(encoding="utf-8")
    profiles = (docs / "project-profiles.md").read_text(encoding="utf-8")
    safety = (docs / "safety.md").read_text(encoding="utf-8")

    assert ".agents" in architecture
    assert "generated" in architecture.lower()
    for token in (
        "adapter.json",
        "capabilities",
        "inventory_roots",
        "sensitive_keys",
        "supported_versions",
    ):
        assert token in authoring
    for profile in ("local", "shared", "split"):
        assert profile in profiles
    for token in ("preview", "rollback", "credentials", "no-clobber"):
        assert token in safety.lower()


def test_installation_docs_cover_fresh_migrate_and_reconfigure(
    repo_root: Path,
) -> None:
    text = (repo_root / "INSTALL.md").read_text(encoding="utf-8")
    for token in (
        "setup detect",
        "setup preview",
        "setup apply",
        "migrate scan",
        "--exclude-skill",
        "doctor",
        "rollback",
    ):
        assert token in text


def test_optional_personal_example_is_not_a_default(
    repo_root: Path,
) -> None:
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    customization = (
        repo_root / "docs" / "customization.md"
    ).read_text(encoding="utf-8")
    combined = f"{readme}\n{customization}".lower()

    assert "templates/examples/two-machine-workflow.md" in combined
    assert "не устанавли" in combined or "not installed" in combined


def _check_markdown_links(
    repo_root: Path,
    *,
    roots: tuple[str, ...],
) -> list[str]:
    files: list[Path] = []
    for root_name in roots:
        root = repo_root / root_name
        if root.is_dir():
            files.extend(sorted(root.rglob("*.md")))
        else:
            files.append(root)

    errors: list[str] = []
    for source in files:
        if not source.is_file():
            errors.append(f"{source.relative_to(repo_root)}: missing source")
            continue
        text = source.read_text(encoding="utf-8")
        for raw_target in _LINK.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if (
                not target
                or target.startswith("#")
                or target.casefold().startswith(_REMOTE_SCHEMES)
            ):
                continue
            path_part = unquote(target.split("#", 1)[0])
            destination = (source.parent / path_part).resolve(
                strict=False
            )
            try:
                destination.relative_to(repo_root.resolve())
            except ValueError:
                errors.append(
                    f"{source.relative_to(repo_root)}: escapes repo: "
                    f"{raw_target}"
                )
                continue
            if not destination.exists():
                errors.append(
                    f"{source.relative_to(repo_root)}: missing: "
                    f"{raw_target}"
                )
    return errors
