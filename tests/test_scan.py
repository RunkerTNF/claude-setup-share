from pathlib import Path

from agent_workflow.paths import HostPaths
from agent_workflow.scan import scan_host


def test_scan_is_read_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    home.mkdir()
    cwd.mkdir()
    before = sorted(tmp_path.rglob("*"))

    snapshot = scan_host(HostPaths.discover(home=home, cwd=cwd))

    assert snapshot.global_agents_exists is False
    assert sorted(tmp_path.rglob("*")) == before


def test_scan_reports_discovered_paths_and_agent_directories(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "repo"
    home_agents = home / ".agents"
    project_agents = project / ".agents"
    home_agents.mkdir(parents=True)
    project_agents.mkdir(parents=True)
    (project / ".git").mkdir()

    snapshot = scan_host(HostPaths.discover(home=home, cwd=project))

    assert snapshot.home == str(home.resolve())
    assert snapshot.cwd == str(project.resolve())
    assert snapshot.project_root == str(project.resolve())
    assert snapshot.global_agents_exists is True
    assert snapshot.project_agents_exists is True
