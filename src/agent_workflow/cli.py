from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict
import json
from pathlib import Path
import sys

from . import __version__
from .adapters.base import AdapterContext
from .adapters.registry import AdapterRegistry, builtin_registry
from .errors import AgentWorkflowError
from .doctor import run_doctor
from .layout import plan_neutral_init
from .migration.classification import (
    build_classification_request,
    load_classification_request,
    load_classification_response,
    load_migration_inventory,
)
from .migration.apply import apply_migration
from .migration.inventory import scan_migration_inventory
from .migration.mappings import map_native_artifacts
from .migration.model import ArtifactScope, MigrationInventory
from .migration.normalize import (
    NormalizationBatch,
    normalize_deterministic,
    resolve_normalized_collisions,
)
from .migration.planner import (
    MigrationOptions,
    MigrationPlanResult,
    build_migration_plan,
)
from .model import ProjectProfile, Scope, Severity
from .paths import HostPaths
from .plan import TransactionPlan
from .scan import scan_host
from .setup import SetupRequest, build_setup_plan, detect_setup_targets
from .transactions import apply_plan, rollback_transaction


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-workflow")
    parser.add_argument("--version", action="store_true")
    subcommands = parser.add_subparsers(dest="command")
    scan = subcommands.add_parser("scan")
    _add_host_arguments(scan)
    scan.add_argument("--json", action="store_true")
    scan.add_argument("--agents", action="store_true")
    _add_adapter_arguments(scan)

    setup_workflow = subcommands.add_parser("setup")
    setup_subcommands = setup_workflow.add_subparsers(
        dest="setup_command",
        required=True,
    )
    setup_detect = setup_subcommands.add_parser("detect")
    _add_setup_scope_arguments(setup_detect)
    _add_host_arguments(setup_detect)
    _add_adapter_arguments(setup_detect)

    setup_preview = setup_subcommands.add_parser("preview")
    _add_setup_scope_arguments(setup_preview)
    setup_preview.add_argument("--source-root")
    setup_preview.add_argument("--manage-syncprotect", action="store_true")
    setup_preview.add_argument("--output", required=True)
    _add_host_arguments(setup_preview)
    _add_adapter_arguments(setup_preview)

    setup_apply = setup_subcommands.add_parser("apply")
    setup_apply.add_argument("--plan", required=True)
    setup_apply.add_argument("--yes", action="store_true")

    plan = subcommands.add_parser("plan")
    plan_subcommands = plan.add_subparsers(dest="plan_command", required=True)
    init = plan_subcommands.add_parser("init")
    init.add_argument("--scope", choices=tuple(scope.value for scope in Scope), required=True)
    init.add_argument("--profile", choices=tuple(profile.value for profile in ProjectProfile))
    init.add_argument("--target", action="append", default=[])
    init.add_argument("--output", required=True)
    _add_host_arguments(init)

    setup = plan_subcommands.add_parser("setup")
    setup.add_argument(
        "--scope",
        choices=tuple(scope.value for scope in Scope),
        required=True,
    )
    setup.add_argument(
        "--profile",
        choices=tuple(profile.value for profile in ProjectProfile),
    )
    setup.add_argument("--target", action="append", default=[])
    setup.add_argument("--source-root")
    setup.add_argument("--manage-syncprotect", action="store_true")
    setup.add_argument("--output", required=True)
    _add_host_arguments(setup)
    _add_adapter_arguments(setup)

    apply = subcommands.add_parser("apply")
    apply.add_argument("plan")

    doctor = subcommands.add_parser("doctor")
    doctor.add_argument("--scope-root")
    doctor.add_argument(
        "--scope",
        choices=tuple(scope.value for scope in Scope),
    )
    _add_host_arguments(doctor)
    doctor.add_argument("--json", action="store_true")

    rollback = subcommands.add_parser("rollback")
    rollback.add_argument("journal")

    migrate = subcommands.add_parser("migrate")
    migrate_subcommands = migrate.add_subparsers(
        dest="migrate_command",
        required=True,
    )
    classify_request = migrate_subcommands.add_parser(
        "classify-request"
    )
    classify_request.add_argument("--inventory", required=True)
    classify_request.add_argument("--output", required=True)
    _add_host_arguments(classify_request)
    validate_response = migrate_subcommands.add_parser(
        "validate-response"
    )
    validate_response.add_argument("--request", required=True)
    validate_response.add_argument("--response", required=True)

    migration_scan = migrate_subcommands.add_parser("scan")
    _add_migration_scope_arguments(migration_scan)
    migration_scan.add_argument("--targets", nargs="+", required=True)
    migration_scan.add_argument("--output", required=True)
    _add_host_arguments(migration_scan)
    _add_adapter_arguments(migration_scan)

    normalize = migrate_subcommands.add_parser("normalize")
    normalize.add_argument("--inventory", required=True)
    normalize.add_argument("--output", required=True)
    normalize.add_argument("--include-native-cache", action="store_true")
    _add_host_arguments(normalize)

    migration_plan = migrate_subcommands.add_parser("plan")
    _add_migration_scope_arguments(migration_plan)
    migration_plan.add_argument("--targets", nargs="+", required=True)
    migration_plan.add_argument("--inventory", required=True)
    migration_plan.add_argument("--normalized", required=True)
    migration_plan.add_argument("--response")
    migration_plan.add_argument("--replace-native", action="store_true")
    migration_plan.add_argument(
        "--include-native-cache",
        action="store_true",
    )
    migration_plan.add_argument(
        "--imported-at",
        default="unspecified",
    )
    migration_plan.add_argument("--output", required=True)
    _add_host_arguments(migration_plan)
    _add_adapter_arguments(migration_plan)

    migration_apply = migrate_subcommands.add_parser("apply")
    migration_apply.add_argument("--plan", required=True)
    migration_apply.add_argument("--yes", action="store_true")

    migration_report = migrate_subcommands.add_parser("report")
    migration_report.add_argument("--plan", required=True)
    migration_report.add_argument("--json", action="store_true")
    migration_report.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)

    try:
        if args.version:
            print(f"agent-workflow {__version__}")
        elif args.command is None:
            parser.print_help()
        elif args.command == "scan":
            _handle_scan(args)
        elif (
            args.command == "setup"
            and args.setup_command == "detect"
        ):
            return _handle_setup_detect(args)
        elif (
            args.command == "setup"
            and args.setup_command == "preview"
        ):
            return _handle_setup_preview(args)
        elif (
            args.command == "setup"
            and args.setup_command == "apply"
        ):
            return _handle_setup_apply(args)
        elif args.command == "plan" and args.plan_command == "init":
            return _handle_plan_init(args)
        elif args.command == "plan" and args.plan_command == "setup":
            return _handle_plan_setup(args)
        elif args.command == "apply":
            _handle_apply(args)
        elif args.command == "doctor":
            return _handle_doctor(args)
        elif args.command == "rollback":
            _handle_rollback(args)
        elif (
            args.command == "migrate"
            and args.migrate_command == "classify-request"
        ):
            return _handle_migrate_classify_request(args)
        elif (
            args.command == "migrate"
            and args.migrate_command == "validate-response"
        ):
            return _handle_migrate_validate_response(args)
        elif (
            args.command == "migrate"
            and args.migrate_command == "scan"
        ):
            return _handle_migrate_scan(args)
        elif (
            args.command == "migrate"
            and args.migrate_command == "normalize"
        ):
            return _handle_migrate_normalize(args)
        elif (
            args.command == "migrate"
            and args.migrate_command == "plan"
        ):
            return _handle_migrate_plan(args)
        elif (
            args.command == "migrate"
            and args.migrate_command == "apply"
        ):
            return _handle_migrate_apply(args)
        elif (
            args.command == "migrate"
            and args.migrate_command == "report"
        ):
            return _handle_migrate_report(args)
        else:
            parser.print_help()
        return 0
    except AgentWorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.exit_code
    except (OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _add_host_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--home")
    parser.add_argument("--cwd")


def _add_adapter_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--adapter-dir", action="append", default=[])
    parser.add_argument(
        "--trust-adapter-code",
        action="append",
        default=[],
    )


def _add_setup_scope_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scope",
        choices=tuple(scope.value for scope in Scope),
        required=True,
    )
    parser.add_argument(
        "--profile",
        choices=tuple(profile.value for profile in ProjectProfile),
    )
    parser.add_argument("--project")
    parser.add_argument("--target", action="append", default=[])


def _add_migration_scope_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument(
        "--scope",
        choices=tuple(scope.value for scope in Scope),
        required=True,
    )
    parser.add_argument(
        "--profile",
        choices=tuple(profile.value for profile in ProjectProfile),
    )


def _host_paths(args: argparse.Namespace) -> HostPaths:
    home = Path(args.home) if args.home is not None else Path.home()
    cwd = Path(args.cwd) if args.cwd is not None else Path.cwd()
    return HostPaths.discover(home=home, cwd=cwd)


def _setup_paths(args: argparse.Namespace) -> HostPaths:
    if args.project is not None and args.cwd is not None:
        raise ValueError("use either --project or --cwd, not both")
    home = Path(args.home) if args.home is not None else Path.home()
    cwd = (
        Path(args.project)
        if args.project is not None
        else Path(args.cwd)
        if args.cwd is not None
        else Path.cwd()
    )
    return HostPaths.discover(home=home, cwd=cwd)


def _handle_scan(args: argparse.Namespace) -> None:
    paths = _host_paths(args)
    snapshot = scan_host(paths)
    detections = ()
    if args.agents:
        registry = _registry_for_cli(
            paths.home,
            tuple(Path(path) for path in args.adapter_dir),
            tuple(args.trust_adapter_code),
        )
        context = AdapterContext(
            home=paths.home,
            project_root=None,
            neutral_root=paths.home / ".agents",
            scope=Scope.GLOBAL,
            profile=None,
            generator_version=__version__,
        )
        detections = detect_setup_targets(context, registry)
    if args.json:
        payload = asdict(snapshot)
        if args.agents:
            payload["agents"] = [
                asdict(detection) for detection in detections
            ]
        _print_json(payload)
        return
    print(
        " ".join(
            (
                f"os={snapshot.os_name}",
                f"python={snapshot.python_version}",
                f"home={snapshot.home}",
                f"project_root={snapshot.project_root or '-'}",
            )
        )
    )
    for detection in detections:
        print(
            " ".join(
                (
                    f"agent={detection.adapter_id}",
                    f"installed={str(detection.installed).lower()}",
                    f"executable={detection.executable or '-'}",
                    f"version={detection.version or '-'}",
                    f"warning={detection.warning or '-'}",
                )
            )
        )


def _handle_plan_init(args: argparse.Namespace) -> int:
    scope = Scope(args.scope)
    profile = ProjectProfile(args.profile) if args.profile is not None else None
    if scope is Scope.GLOBAL and profile is not None:
        raise ValueError("global scope does not accept a project profile")
    if scope is Scope.PROJECT and profile is None:
        raise ValueError("project scope requires --profile")
    plan = plan_neutral_init(
        _host_paths(args),
        scope=scope,
        profile=profile,
        targets=tuple(args.target),
    )
    output = Path(args.output)
    output.write_text(plan.to_json(), encoding="utf-8")
    print(
        f"wrote plan: {output} "
        f"({len(plan.operations)} operations, {len(plan.conflicts)} conflicts)"
    )
    return 3 if plan.conflicts else 0


def _handle_setup_detect(args: argparse.Namespace) -> int:
    paths = _setup_paths(args)
    scope, profile = _setup_scope(args, paths)
    registry = _registry_for_cli(
        paths.home,
        tuple(Path(path) for path in args.adapter_dir),
        tuple(args.trust_adapter_code),
    )
    context = AdapterContext(
        home=paths.home,
        project_root=(
            paths.project_root if scope is Scope.PROJECT else None
        ),
        neutral_root=(
            paths.home / ".agents"
            if scope is Scope.GLOBAL
            else paths.project_root / ".agents"
        ),
        scope=scope,
        profile=profile,
        generator_version=__version__,
    )
    detections = detect_setup_targets(context, registry)
    print("Detected adapters:")
    for detection in detections:
        state = "installed" if detection.installed else "not-installed"
        warning = f"; {detection.warning}" if detection.warning else ""
        print(f"- {detection.adapter_id}: {state}{warning}")
    return 0


def _handle_setup_preview(args: argparse.Namespace) -> int:
    paths = _setup_paths(args)
    scope, profile = _setup_scope(args, paths)
    registry = _registry_for_cli(
        paths.home,
        tuple(Path(path) for path in args.adapter_dir),
        tuple(args.trust_adapter_code),
    )
    targets = tuple(args.target)
    if not targets:
        context = AdapterContext(
            home=paths.home,
            project_root=(
                paths.project_root
                if scope is Scope.PROJECT
                else None
            ),
            neutral_root=(
                paths.home / ".agents"
                if scope is Scope.GLOBAL
                else paths.project_root / ".agents"
            ),
            scope=scope,
            profile=profile,
            generator_version=__version__,
        )
        targets = tuple(
            item.adapter_id
            for item in detect_setup_targets(context, registry)
            if item.installed
        )
    request = SetupRequest(
        home=paths.home,
        project_root=(
            paths.project_root if scope is Scope.PROJECT else None
        ),
        source_root=(
            Path(args.source_root)
            if args.source_root is not None
            else Path.cwd()
        ),
        scope=scope,
        profile=profile,
        targets=targets,
        manage_syncprotect=args.manage_syncprotect,
        adapter_sources=tuple(
            Path(path) for path in args.adapter_dir
        ),
        trusted_adapter_ids=tuple(args.trust_adapter_code),
    )
    plan = build_setup_plan(request)
    output = Path(args.output)
    output.write_text(plan.to_json(), encoding="utf-8")
    print("Setup preview:")
    print(plan.to_json(), end="")
    print(
        f"wrote setup plan: {output} "
        f"({len(plan.operations)} operations, "
        f"{len(plan.conflicts)} conflicts, "
        f"{len(plan.warnings)} warnings)"
    )
    return 3 if plan.conflicts else 0


def _handle_setup_apply(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    plan = TransactionPlan.from_json(
        plan_path.read_text(encoding="utf-8")
    )
    if not args.yes:
        answer = input("Apply this exact setup plan? [y/N] ")
        if answer.strip().casefold() not in {"y", "yes"}:
            print("setup cancelled; no changes applied")
            return 1
    journal = apply_plan(plan)
    print(
        f"applied transaction {journal.transaction_id}: "
        f"{journal.status}; journal: {journal.journal_path}"
    )
    return _report_doctor(Path(plan.scope_root), json_output=False)


def _setup_scope(
    args: argparse.Namespace,
    paths: HostPaths,
) -> tuple[Scope, ProjectProfile | None]:
    scope = Scope(args.scope)
    profile = (
        ProjectProfile(args.profile)
        if args.profile is not None
        else None
    )
    if scope is Scope.GLOBAL:
        if profile is not None or args.project is not None:
            raise ValueError(
                "global setup does not accept --profile or --project"
            )
    else:
        if profile is None:
            raise ValueError("project setup requires --profile")
        if paths.project_root is None:
            raise ValueError(
                "project setup requires a discovered project root"
            )
    return scope, profile


def _handle_plan_setup(args: argparse.Namespace) -> int:
    scope = Scope(args.scope)
    profile = (
        ProjectProfile(args.profile)
        if args.profile is not None
        else None
    )
    if scope is Scope.GLOBAL and profile is not None:
        raise ValueError("global scope does not accept a project profile")
    if scope is Scope.PROJECT and profile is None:
        raise ValueError("project scope requires --profile")
    paths = _host_paths(args)
    request = SetupRequest(
        home=paths.home,
        project_root=(
            paths.project_root if scope is Scope.PROJECT else None
        ),
        source_root=(
            Path(args.source_root)
            if args.source_root is not None
            else Path.cwd()
        ),
        scope=scope,
        profile=profile,
        targets=tuple(args.target),
        manage_syncprotect=args.manage_syncprotect,
        adapter_sources=tuple(
            Path(path) for path in args.adapter_dir
        ),
        trusted_adapter_ids=tuple(args.trust_adapter_code),
    )
    plan = build_setup_plan(request)
    output = Path(args.output)
    output.write_text(plan.to_json(), encoding="utf-8")
    print(
        f"wrote setup plan: {output} "
        f"({len(plan.operations)} operations, "
        f"{len(plan.conflicts)} conflicts, "
        f"{len(plan.warnings)} warnings)"
    )
    return 3 if plan.conflicts else 0


def _handle_apply(args: argparse.Namespace) -> None:
    plan = TransactionPlan.from_json(Path(args.plan).read_text(encoding="utf-8"))
    journal = apply_plan(plan)
    print(f"applied transaction {journal.transaction_id}: {journal.status}; journal: {journal.journal_path}")


def _handle_doctor(args: argparse.Namespace) -> int:
    if args.scope_root is not None and args.scope is not None:
        raise ValueError("use either --scope-root or --scope, not both")
    if args.scope_root is not None:
        scope_root = Path(args.scope_root)
    elif args.scope is not None:
        paths = _host_paths(args)
        scope = Scope(args.scope)
        if scope is Scope.GLOBAL:
            scope_root = paths.home / ".agents"
        else:
            if paths.project_root is None:
                raise ValueError(
                    "project doctor requires a discovered project root"
                )
            scope_root = paths.project_root / ".agents"
    else:
        raise ValueError("doctor requires --scope-root or --scope")
    return _report_doctor(scope_root, json_output=args.json)


def _report_doctor(scope_root: Path, *, json_output: bool) -> int:
    diagnostics = run_doctor(scope_root)
    if json_output:
        _print_json(
            {
                "blocking": any(item.severity is Severity.BLOCKING for item in diagnostics),
                "diagnostics": [
                    {
                        "severity": item.severity.value,
                        "code": item.code,
                        "path": item.path,
                        "message": item.message,
                    }
                    for item in diagnostics
                ],
            }
        )
    elif diagnostics:
        for item in diagnostics:
            print(f"{item.severity.value}: {item.code}: {item.path}: {item.message}")
    else:
        print("doctor: clean")
    return 2 if any(item.severity is Severity.BLOCKING for item in diagnostics) else 0


def _handle_rollback(args: argparse.Namespace) -> None:
    journal = rollback_transaction(Path(args.journal))
    print(f"rolled back transaction {journal.transaction_id}: {journal.status}; journal: {journal.journal_path}")


def _handle_migrate_classify_request(
    args: argparse.Namespace,
) -> int:
    paths = _host_paths(args)
    inventory = load_migration_inventory(
        Path(args.inventory),
        home=paths.home,
        project_root=paths.project_root,
    )
    request = build_classification_request(inventory)
    output = Path(args.output)
    output.write_text(request.to_json(), encoding="utf-8")
    print(
        f"wrote classification request: {output} "
        f"({len(request.artifacts)} artifacts)"
    )
    return 0


def _handle_migrate_validate_response(
    args: argparse.Namespace,
) -> int:
    request = load_classification_request(Path(args.request))
    response = load_classification_response(
        Path(args.response),
        request,
    )
    print(
        "classification response valid: "
        f"{len(response.decisions)} decisions"
    )
    return 0


def _handle_migrate_scan(args: argparse.Namespace) -> int:
    paths = _host_paths(args)
    scope, profile = _migration_scope(args, paths)
    registry = _registry_for_cli(
        paths.home,
        tuple(Path(path) for path in args.adapter_dir),
        tuple(args.trust_adapter_code),
    )
    adapters = registry.require(tuple(args.targets))
    context = AdapterContext(
        home=paths.home,
        project_root=(
            paths.project_root if scope is Scope.PROJECT else None
        ),
        neutral_root=(
            paths.home / ".agents"
            if scope is Scope.GLOBAL
            else paths.project_root / ".agents"
        ),
        scope=scope,
        profile=profile,
        generator_version=__version__,
    )
    scanned = scan_migration_inventory(context, adapters)
    artifact_scope = ArtifactScope(scope.value)
    inventory = MigrationInventory(
        schema_version=1,
        roots=tuple(
            root
            for root in scanned.roots
            if f":{scope.value}:" in root
        ),
        artifacts=tuple(
            record
            for record in scanned.artifacts
            if record.scope is artifact_scope
        ),
        warnings=scanned.warnings,
    )
    output = Path(args.output)
    output.write_text(inventory.to_json(), encoding="utf-8")
    print(
        f"wrote migration inventory: {output} "
        f"({len(inventory.artifacts)} artifacts, "
        f"{len(inventory.warnings)} warnings)"
    )
    return 0


def _handle_migrate_normalize(args: argparse.Namespace) -> int:
    paths = _host_paths(args)
    inventory = load_migration_inventory(
        Path(args.inventory),
        home=paths.home,
        project_root=paths.project_root,
    )
    artifacts = []
    for record in inventory.artifacts:
        source_root = (
            paths.home
            if record.scope is ArtifactScope.GLOBAL
            else paths.project_root
        )
        if source_root is None:
            raise ValueError(
                "project artifact requires a discovered project root"
            )
        artifacts.append(
            normalize_deterministic(
                record,
                source_root,
                include_native_cache=args.include_native_cache,
            )
        )
    batch = resolve_normalized_collisions(artifacts)
    output = Path(args.output)
    output.write_text(batch.to_json(), encoding="utf-8")
    print(
        f"wrote normalized artifacts: {output} "
        f"({len(batch.artifacts)} artifacts, "
        f"{len(batch.conflicts)} conflicts)"
    )
    return 3 if batch.conflicts else 0


def _handle_migrate_plan(args: argparse.Namespace) -> int:
    paths = _host_paths(args)
    scope, profile = _migration_scope(args, paths)
    inventory = load_migration_inventory(
        Path(args.inventory),
        home=paths.home,
        project_root=paths.project_root,
    )
    normalized = NormalizationBatch.from_json(
        Path(args.normalized).read_text(encoding="utf-8")
    )
    classification_request = build_classification_request(inventory)
    if classification_request.artifacts and args.response is None:
        raise ValueError(
            "ambiguous artifacts require a validated response"
        )
    decisions = (
        load_classification_response(
            Path(args.response),
            classification_request,
        )
        if args.response is not None
        else None
    )
    registry = _registry_for_cli(
        paths.home,
        tuple(Path(path) for path in args.adapter_dir),
        tuple(args.trust_adapter_code),
    )
    target_adapters = registry.require(tuple(args.targets))
    mapped = []
    source_ids = sorted(
        {
            record.agent_id
            for record in inventory.artifacts
            if record.scope.value == scope.value
        }
    )
    for source_id in source_ids:
        source_adapter = registry.require((source_id,))[0]
        mapped.extend(
            map_native_artifacts(
                (
                    record
                    for record in inventory.artifacts
                    if record.agent_id == source_id
                    and record.scope.value == scope.value
                ),
                source_adapter,
                target_adapters,
            )
        )
    result = build_migration_plan(
        inventory=inventory,
        normalized=normalized,
        decisions=decisions,
        mappings=tuple(mapped),
        options=MigrationOptions(
            home=paths.home,
            project_root=(
                paths.project_root
                if scope is Scope.PROJECT
                else None
            ),
            scope=scope,
            profile=profile,
            targets=tuple(args.targets),
            replace_native=args.replace_native,
            imported_at=args.imported_at,
            include_native_cache=args.include_native_cache,
        ),
    )
    output = Path(args.output)
    output.write_text(result.to_json(), encoding="utf-8")
    print(
        f"wrote migration plan: {output} "
        f"({len(result.import_plan.operations)} import operations, "
        f"{len(result.blocking_conflicts)} conflicts)"
    )
    return 3 if result.blocking_conflicts else 0


def _handle_migrate_apply(args: argparse.Namespace) -> int:
    result = MigrationPlanResult.from_json(
        Path(args.plan).read_text(encoding="utf-8")
    )
    confirmed = args.yes
    if not confirmed:
        answer = input(
            "Apply the materialized migration plan? [y/N] "
        )
        confirmed = answer.strip().casefold() in {"y", "yes"}
        if not confirmed:
            print("migration cancelled; no changes applied")
            return 1
    applied = apply_migration(
        result,
        confirm_replacement=confirmed,
    )
    print(
        "migration applied; "
        f"backups={','.join(applied.backup_locations) or '-'}; "
        f"rollback={','.join(applied.rollback_locations) or '-'}"
    )
    return 0


def _handle_migrate_report(args: argparse.Namespace) -> int:
    result = MigrationPlanResult.from_json(
        Path(args.plan).read_text(encoding="utf-8")
    )
    content = (
        result.report.to_json()
        if args.json
        else result.report.to_markdown()
    )
    if args.output is not None:
        output = Path(args.output)
        output.write_text(content, encoding="utf-8")
        print(f"wrote migration report: {output}")
    else:
        print(content, end="")
    return 0


def _migration_scope(
    args: argparse.Namespace,
    paths: HostPaths,
) -> tuple[Scope, ProjectProfile | None]:
    scope = Scope(args.scope)
    profile = (
        ProjectProfile(args.profile)
        if args.profile is not None
        else None
    )
    if scope is Scope.GLOBAL and profile is not None:
        raise ValueError(
            "global migration does not accept a project profile"
        )
    if scope is Scope.PROJECT:
        if profile is None:
            raise ValueError(
                "project migration requires --profile"
            )
        if paths.project_root is None:
            raise ValueError(
                "project migration requires a discovered project root"
            )
    return scope, profile


def _print_json(payload: object) -> None:
    print(json.dumps(payload, sort_keys=True))


def _registry_for_cli(
    home: Path,
    adapter_sources: tuple[Path, ...],
    trusted_adapter_ids: tuple[str, ...],
) -> AdapterRegistry:
    if trusted_adapter_ids and not adapter_sources:
        raise ValueError(
            "adapter code trust requires an explicit --adapter-dir"
        )
    roots = adapter_sources
    if not roots:
        managed = home / ".agents" / "workflow" / "adapters"
        if managed.is_dir() and not managed.is_symlink():
            roots = (managed,)
    external = (
        AdapterRegistry.from_directories(
            roots,
            trusted_adapter_ids if adapter_sources else (),
        )
        if roots
        else AdapterRegistry.from_pairs(())
    )
    return AdapterRegistry.combine((builtin_registry(), external))
