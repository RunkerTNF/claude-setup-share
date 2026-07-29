from __future__ import annotations

import json
from pathlib import Path

from agent_workflow.cli import main


def test_plan_apply_doctor_and_rollback(tmp_path: Path) -> None:
    """A removed command dispatch must fail this complete user workflow."""
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    plan_file = tmp_path / "plan.json"
    home.mkdir()
    repo.mkdir()

    assert main(
        [
            "plan",
            "init",
            "--scope",
            "global",
            "--home",
            str(home),
            "--cwd",
            str(repo),
            "--output",
            str(plan_file),
        ]
    ) == 0
    assert plan_file.is_file()
    assert not (home / ".agents").exists()

    assert main(["apply", str(plan_file)]) == 0
    scope_root = home / ".agents"
    assert (scope_root / "RULES.md").is_file()
    assert main(["doctor", "--scope-root", str(scope_root)]) == 0

    journals = list((scope_root / "workflow" / "journals").glob("*.json"))
    assert len(journals) == 1
    assert main(["rollback", str(journals[0])]) == 0
    assert not (scope_root / "RULES.md").exists()


def test_scan_and_doctor_json_are_machine_readable(tmp_path: Path, capsys) -> None:
    """Dropping JSON mode must break integrations that parse CLI output."""
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()

    assert main(["scan", "--home", str(home), "--cwd", str(cwd), "--json"]) == 0
    scan = json.loads(capsys.readouterr().out)
    assert scan["home"] == str(home.resolve())
    assert scan["cwd"] == str(cwd.resolve())
    assert scan["global_agents_exists"] is False

    assert main(["doctor", "--scope-root", str(home / ".agents"), "--json"]) == 2
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["blocking"] is True
    assert doctor["diagnostics"][0]["code"] == "scope.invalid"


def test_cli_maps_invalid_plan_and_conflict_without_writing_targets(tmp_path: Path) -> None:
    """Wrong error mapping could turn malformed input into writes or success."""
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not JSON", encoding="utf-8")
    assert main(["apply", str(malformed)]) == 2

    invalid_schema = tmp_path / "invalid-schema.json"
    invalid_schema.write_text("{}", encoding="utf-8")
    assert main(["apply", str(invalid_schema)]) == 2

    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    plan_file = tmp_path / "conflict.json"
    scope_root = home / ".agents"
    scope_root.mkdir(parents=True)
    cwd.mkdir()
    (scope_root / "RULES.md").write_text("unmanaged rules\n", encoding="utf-8")

    assert main(
        [
            "plan",
            "init",
            "--scope",
            "global",
            "--home",
            str(home),
            "--cwd",
            str(cwd),
            "--output",
            str(plan_file),
        ]
    ) == 3
    assert main(["apply", str(plan_file)]) == 3
    assert (scope_root / "RULES.md").read_text(encoding="utf-8") == "unmanaged rules\n"
    assert not (scope_root / "manifest.json").exists()

    valid_home = tmp_path / "valid-home"
    valid_plan = tmp_path / "valid-plan.json"
    valid_home.mkdir()
    assert main(
        [
            "plan",
            "init",
            "--scope",
            "global",
            "--home",
            str(valid_home),
            "--cwd",
            str(cwd),
            "--output",
            str(valid_plan),
        ]
    ) == 0
    payload = json.loads(valid_plan.read_text(encoding="utf-8"))
    payload["operations"][0]["path"] = "../RULES.md"
    invalid_path = tmp_path / "invalid-path.json"
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["apply", str(invalid_path)]) == 2
    assert not (valid_home / ".agents").exists()


def test_project_init_requires_profile_and_discovered_repository(tmp_path: Path) -> None:
    """Skipping CLI boundary validation could create a project workflow in any directory."""
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    output = tmp_path / "project-plan.json"
    home.mkdir()
    cwd.mkdir()

    assert main(
        [
            "plan",
            "init",
            "--scope",
            "project",
            "--home",
            str(home),
            "--cwd",
            str(cwd),
            "--output",
            str(output),
        ]
    ) == 2
    assert not output.exists()

    (cwd / ".git").mkdir()
    assert main(
        [
            "plan",
            "init",
            "--scope",
            "project",
            "--profile",
            "local",
            "--home",
            str(home),
            "--cwd",
            str(cwd),
            "--output",
            str(output),
        ]
    ) == 0
    assert output.is_file()
