from agent_workflow.cli import build_parser, main


def test_parser_exposes_foundation_commands() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    assert "scan" in help_text
    assert "plan" in help_text
    assert "apply" in help_text
    assert "doctor" in help_text
    assert "rollback" in help_text


def test_main_returns_zero_for_version(capsys) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "agent-workflow 0.1.0"


def test_bare_plan_requires_a_plan_subcommand(capsys) -> None:
    """Removing the required nested command must not silently print help and succeed."""
    assert main(["plan"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "required" in captured.err


def test_parser_exposes_agent_scan_and_setup_plan() -> None:
    parser = build_parser()

    scan = parser.parse_args(["scan", "--agents", "--json"])
    setup = parser.parse_args(
        [
            "plan",
            "setup",
            "--scope",
            "global",
            "--target",
            "codex",
            "--output",
            "plan.json",
        ]
    )

    assert scan.agents is True
    assert setup.plan_command == "setup"
    assert setup.target == ["codex"]
