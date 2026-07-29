from __future__ import annotations

from dataclasses import dataclass
import platform
import sys

from .paths import HostPaths


@dataclass(frozen=True)
class HostSnapshot:
    os_name: str
    python_version: str
    home: str
    cwd: str
    project_root: str | None
    global_agents_exists: bool
    project_agents_exists: bool


def scan_host(paths: HostPaths) -> HostSnapshot:
    return HostSnapshot(
        os_name=platform.system().lower(),
        python_version=".".join(map(str, sys.version_info[:3])),
        home=str(paths.home),
        cwd=str(paths.cwd),
        project_root=str(paths.project_root) if paths.project_root else None,
        global_agents_exists=(paths.home / ".agents").exists(),
        project_agents_exists=bool(
            paths.project_root and (paths.project_root / ".agents").exists()
        ),
    )
