"""Read-only validation for the portable core of an Agent Skill."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import re

from .doctor import Diagnostic
from .model import Severity, normalize_relative_path


_FRONTMATTER_FIELD = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):[ \t]*(.*?)$")
_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)(?:\s+[^)]*)?\)")
_URI_SCHEME = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*):")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_FILE_REFERENCE = re.compile(
    r"(?<![\w.$-])(?P<reference>(?:(?:\.\.?|[A-Za-z]:)?[\\/])?(?:[\w.-]+[\\/])+[\w.-]+\.[A-Za-z0-9]+)"
)
_BARE_FILE_REFERENCE = re.compile(r"(?<![\w.$/\\-])(?P<reference>[\w-]+\.[A-Za-z0-9]+)(?![\w-])")
_TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt"})
_VENDOR_PATTERNS = (
    re.compile(
        r"\$(?:\{(?:CLAUDE_SKILL_DIR|CLAUDE_PLUGIN_ROOT|CODEX_HOME)\}|(?:CLAUDE_SKILL_DIR|CLAUDE_PLUGIN_ROOT|CODEX_HOME)\b)",
        re.IGNORECASE,
    ),
    re.compile(r"(?<![\w.-])\.(?:claude|codex)(?:[\\/]|$)", re.IGNORECASE),
    re.compile(
        r"(?im)^\s*(?:Bash|Read|Write|Edit|Glob|Grep|Task)\s*\(\s*(?:[A-Za-z_][A-Za-z0-9_]*\s*=|[\"'{\[])"
    ),
    re.compile(r"(?im)^\s*(?:hooks?|permissions?|subagents?|allowed-tools?)\s*:\s*"),
)
_VENDOR_FRONTMATTER = frozenset({"allowed-tools", "tools", "hooks", "permissions", "subagents"})


def lint_skill(skill_dir: Path) -> tuple[Diagnostic, ...]:
    """Return deterministic, blocking portability diagnostics without modifying the skill."""
    skill_dir = Path(skill_dir)
    diagnostics: list[Diagnostic] = []
    skill_file = skill_dir / "SKILL.md"
    if not _safe_file(skill_file, skill_dir):
        diagnostics.append(_diagnostic("portable.missing-skill", "SKILL.md", "missing safe SKILL.md"))
        return _ordered(diagnostics)

    try:
        skill_text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        diagnostics.append(_diagnostic("portable.missing-skill", "SKILL.md", "cannot read SKILL.md"))
        return _ordered(diagnostics)

    metadata, body, frontmatter_valid = _parse_frontmatter(skill_text)
    if not frontmatter_valid or not _valid_metadata(metadata, skill_dir.name):
        diagnostics.append(
            _diagnostic("portable.frontmatter", "SKILL.md", "invalid portable skill frontmatter")
        )
    if _contains_vendor_syntax(skill_text, metadata):
        diagnostics.append(
            _diagnostic("portable.vendor-token", "SKILL.md", "vendor-specific syntax in portable core")
        )

    graph: dict[str, set[str]] = {"SKILL.md": set()}
    visited: set[str] = set()
    _scan_references(
        root=skill_dir,
        current=skill_file,
        text=body,
        graph=graph,
        visited=visited,
        diagnostics=diagnostics,
    )
    for cycle in _cycles(graph):
        diagnostics.append(
            _diagnostic(
                "portable.reference-cycle",
                cycle[0],
                f"packaged text reference cycle: {' -> '.join(cycle)}",
            )
        )
    return _ordered(diagnostics)


def parse_portable_skill_frontmatter(text: str) -> tuple[str, str, str]:
    """Return portable skill metadata and body, rejecting invalid frontmatter."""
    metadata, body, valid = _parse_frontmatter(text)
    name = metadata.get("name")
    description = metadata.get("description")
    if (
        not valid
        or set(metadata) != {"name", "description"}
        or not isinstance(name, str)
        or _SKILL_NAME.fullmatch(name) is None
        or not isinstance(description, str)
        or not description.strip()
    ):
        raise ValueError("invalid portable skill frontmatter")
    return name, description, body


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str, bool]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return {}, text, False
    metadata: dict[str, str] = {}
    valid = True
    for index, line in enumerate(lines[1:], start=1):
        stripped = line.rstrip("\r\n")
        if stripped == "---":
            return metadata, "".join(lines[index + 1 :]), valid
        field = _FRONTMATTER_FIELD.fullmatch(stripped)
        if field is None:
            valid = False
            continue
        key, value = field.groups()
        if key not in {"name", "description"} or key in metadata or not value:
            valid = False
            continue
        metadata[key] = value
    return metadata, text, False


def _valid_metadata(metadata: dict[str, str], directory_name: str) -> bool:
    name = metadata.get("name")
    return (
        set(metadata) == {"name", "description"}
        and isinstance(name, str)
        and _SKILL_NAME.fullmatch(name) is not None
        and name == directory_name
        and bool(metadata["description"].strip())
    )


def _contains_vendor_syntax(text: str, metadata: dict[str, str]) -> bool:
    # Unknown vendor fields are retained by neither parser output nor metadata, so inspect lines too.
    if any(pattern.search(text) for pattern in _VENDOR_PATTERNS):
        return True
    return any(
        line.partition(":")[0].strip().casefold() in _VENDOR_FRONTMATTER
        for line in text.splitlines()
    )


def _scan_references(
    *,
    root: Path,
    current: Path,
    text: str,
    graph: dict[str, set[str]],
    visited: set[str],
    diagnostics: list[Diagnostic],
) -> None:
    current_key = _relative(current, root)
    if current_key in visited:
        return
    visited.add(current_key)
    graph.setdefault(current_key, set())
    for reference in _references(text):
        target = _reference_target(root, current.parent, reference)
        if target is None:
            diagnostics.append(
                _diagnostic("portable.reference-unsafe", current_key, f"unsafe reference: {reference}")
            )
            continue
        target_key = _relative(target, root)
        if not _safe_file(target, root):
            code = "portable.reference-unsafe" if target.exists() or target.is_symlink() else "portable.reference-missing"
            diagnostics.append(_diagnostic(code, current_key, f"missing safe reference: {reference}"))
            continue
        if target.suffix.casefold() in _TEXT_SUFFIXES:
            graph[current_key].add(target_key)
            try:
                target_text = target.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                diagnostics.append(
                    _diagnostic("portable.reference-missing", current_key, f"cannot read reference: {reference}")
                )
                continue
            if _contains_vendor_syntax(target_text, {}):
                diagnostics.append(
                    _diagnostic("portable.vendor-token", target_key, "vendor-specific syntax in portable core")
                )
            _scan_references(
                root=root,
                current=target,
                text=target_text,
                graph=graph,
                visited=visited,
                diagnostics=diagnostics,
            )
        elif target.parent.name.casefold() == "scripts" and target.suffix.casefold() != ".py":
            diagnostics.append(
                _diagnostic(
                    "portable.script",
                    target_key,
                    "deterministic portable scripts must be Python",
                )
            )


def _references(text: str) -> tuple[str, ...]:
    found: set[str] = set()
    markdown_target_spans: list[tuple[int, int]] = []
    for match in _MARKDOWN_LINK.finditer(text):
        markdown_target_spans.append(match.span(1))
        candidate = match.group(1).strip().strip("<>")
        local_reference = _markdown_local_reference(candidate)
        if local_reference is not None:
            found.add(local_reference)
    for match in _FILE_REFERENCE.finditer(text):
        if _inside_markdown_target(match, markdown_target_spans):
            continue
        candidate = match.group("reference").strip().rstrip(".,;:!?")
        if (
            candidate
            and not _is_external(candidate)
            and not _is_vendor_path(candidate)
            and not _is_neutral_runtime_path(candidate)
            and not _follows_vendor_environment_token(text, match.start())
            and not _follows_home_runtime_token(
                text,
                match.start(),
                candidate,
            )
        ):
            found.add(candidate)
    for match in _BARE_FILE_REFERENCE.finditer(text):
        if _inside_markdown_target(match, markdown_target_spans):
            continue
        candidate = match.group("reference")
        if _looks_like_bare_reference(text, match.start()):
            found.add(candidate)
    return tuple(sorted(found, key=str.casefold))


def _is_external(reference: str) -> bool:
    if reference.startswith(("#", "?")):
        return True
    scheme = _URI_SCHEME.match(reference)
    return (
        scheme is not None
        and scheme.group("scheme").casefold() != "file"
        and _WINDOWS_DRIVE.match(reference) is None
    )


def _markdown_local_reference(target: str) -> str | None:
    if not target or _is_external(target):
        return None
    path = target.split("#", 1)[0].split("?", 1)[0]
    return path or None


def _inside_markdown_target(
    match: re.Match[str], target_spans: list[tuple[int, int]]
) -> bool:
    start, end = match.span()
    return any(start >= target_start and end <= target_end for target_start, target_end in target_spans)


def _is_vendor_path(reference: str) -> bool:
    return re.match(r"^\.(?:claude|codex)(?:[\\/]|$)", reference, re.IGNORECASE) is not None


def _is_neutral_runtime_path(reference: str) -> bool:
    try:
        normalized = normalize_relative_path(reference)
    except ValueError:
        return False
    parts = normalized.split("/")
    return len(parts) > 1 and parts[0].casefold() == ".agents"


def _follows_vendor_environment_token(text: str, start: int) -> bool:
    return re.search(
        r"\$(?:\{(?:CLAUDE_SKILL_DIR|CLAUDE_PLUGIN_ROOT|CODEX_HOME)\}|(?:CLAUDE_SKILL_DIR|CLAUDE_PLUGIN_ROOT|CODEX_HOME)\b)[\\/]$",
        text[:start],
        re.IGNORECASE,
    ) is not None


def _follows_home_runtime_token(
    text: str,
    start: int,
    reference: str,
) -> bool:
    if (
        not text[:start].endswith("~")
        or not reference.startswith(("/", "\\"))
    ):
        return False
    try:
        normalize_relative_path(reference.lstrip("/\\"))
    except ValueError:
        return False
    return True


def _looks_like_bare_reference(text: str, start: int) -> bool:
    return re.search(
        r"(?:^|[\n.;:])\s*(?:read|see|open|run|use|follow)\s+(?:the\s+)?$",
        text[:start],
        re.IGNORECASE,
    ) is not None


def _reference_target(root: Path, parent: Path, reference: str) -> Path | None:
    try:
        normalized = normalize_relative_path(reference)
    except ValueError:
        return None
    target = parent.joinpath(*normalized.split("/"))
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return None
    return target


def _safe_file(path: Path, root: Path) -> bool:
    try:
        root_resolved = root.resolve(strict=False)
        path.resolve(strict=False).relative_to(root_resolved)
        if not path.is_file() or path.is_symlink():
            return False
        relative = path.relative_to(root)
        cursor = root
        if cursor.is_symlink():
            return False
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return False
        return True
    except (OSError, ValueError):
        return False


def _cycles(graph: dict[str, set[str]]) -> Iterable[tuple[str, ...]]:
    state: dict[str, int] = {}
    stack: list[str] = []
    reported: set[frozenset[str]] = set()
    for node in sorted(graph, key=str.casefold):
        if state.get(node, 0) != 0:
            continue
        yield from _visit(node, graph, state, stack, reported)


def _visit(
    node: str,
    graph: dict[str, set[str]],
    state: dict[str, int],
    stack: list[str],
    reported: set[frozenset[str]],
) -> Iterable[tuple[str, ...]]:
    state[node] = 1
    stack.append(node)
    for child in sorted(graph.get(node, ()), key=str.casefold):
        child_state = state.get(child, 0)
        if child_state == 0:
            yield from _visit(child, graph, state, stack, reported)
        elif child_state == 1:
            cycle = tuple(stack[stack.index(child) :])
            identity = frozenset(cycle)
            if identity not in reported:
                reported.add(identity)
                yield cycle
    stack.pop()
    state[node] = 2


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(Severity.BLOCKING, code, path, message)


def _ordered(diagnostics: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(set(diagnostics), key=lambda item: (item.path, item.code, item.message)))
