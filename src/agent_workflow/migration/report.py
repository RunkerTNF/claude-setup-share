from __future__ import annotations

from dataclasses import dataclass
import json


@dataclass(frozen=True)
class MigrationReport:
    source_mappings: tuple[str, ...]
    source_files_preserved: tuple[str, ...]
    blocking_conflicts: tuple[str, ...]
    warnings: tuple[str, ...]
    sensitive_skips: tuple[str, ...]
    unsupported_fields: tuple[str, ...]
    deduplications: tuple[str, ...]
    expected_doctor_checks: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "source_mappings",
            "source_files_preserved",
            "blocking_conflicts",
            "warnings",
            "sensitive_skips",
            "unsupported_fields",
            "deduplications",
            "expected_doctor_checks",
        ):
            values = getattr(self, field_name)
            if (
                not isinstance(values, tuple)
                or any(
                    not isinstance(value, str) or "\x00" in value
                    for value in values
                )
            ):
                raise ValueError(
                    f"migration report {field_name} is invalid"
                )
            object.__setattr__(
                self,
                field_name,
                tuple(sorted(set(values))),
            )

    def payload(self) -> dict[str, object]:
        return {
            "source_mappings": list(self.source_mappings),
            "source_files_preserved": list(
                self.source_files_preserved
            ),
            "blocking_conflicts": list(self.blocking_conflicts),
            "warnings": list(self.warnings),
            "sensitive_skips": list(self.sensitive_skips),
            "unsupported_fields": list(self.unsupported_fields),
            "deduplications": list(self.deduplications),
            "expected_doctor_checks": list(
                self.expected_doctor_checks
            ),
        }

    @classmethod
    def from_payload(cls, payload: object) -> "MigrationReport":
        expected = {
            "source_mappings",
            "source_files_preserved",
            "blocking_conflicts",
            "warnings",
            "sensitive_skips",
            "unsupported_fields",
            "deduplications",
            "expected_doctor_checks",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("migration report fields are invalid")
        values: dict[str, tuple[str, ...]] = {}
        for key in expected:
            raw = payload[key]
            if not isinstance(raw, list) or any(
                not isinstance(item, str) for item in raw
            ):
                raise ValueError(
                    f"migration report {key} must be a string list"
                )
            values[key] = tuple(raw)
        return cls(**values)

    def to_json(self) -> str:
        return json.dumps(
            self.payload(),
            indent=2,
            sort_keys=True,
        ) + "\n"

    def to_markdown(self) -> str:
        sections = [
            ("Source mappings", self.source_mappings),
            ("Preserved source files", self.source_files_preserved),
            ("Blocking conflicts", self.blocking_conflicts),
            ("Warnings", self.warnings),
            ("Sensitive skips", self.sensitive_skips),
            ("Unsupported fields", self.unsupported_fields),
            ("Deduplications", self.deduplications),
            ("Expected doctor checks", self.expected_doctor_checks),
        ]
        lines = ["# Migration Preview", ""]
        for title, values in sections:
            lines.extend((f"## {title}", ""))
            if values:
                lines.extend(f"- {value}" for value in values)
            else:
                lines.append("- None")
            lines.append("")
        return "\n".join(lines)
