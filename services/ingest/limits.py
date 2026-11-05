"""Ingest limits (SEC-1.4), read from rules_constants.yaml."""

from dataclasses import dataclass

from services.rules_constants import rule_constants

MIB = 1024 * 1024


@dataclass(frozen=True)
class Limits:
    max_bytes: int
    max_files: int
    max_depth: int


def load_limits() -> Limits:
    constants = rule_constants("SEC-1.4")
    return Limits(
        max_bytes=int(constants["max_archive_unpacked_mb"]) * MIB,
        max_files=int(constants["max_archive_files"]),
        max_depth=int(constants["max_directory_depth"]),
    )
