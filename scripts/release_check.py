"""Offline release preflight. Never connects to or changes a database."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.shared.infrastructure.config.settings import Settings  # noqa: E402
from scripts.export_openapi import artifacts  # noqa: E402

DOCUMENTS = (
    "phase12-report.md",
    "release-readiness.md",
    "release-runbook.md",
    "security-review.md",
    "security-checklist.md",
    "performance-report.md",
    "backup-restore-runbook.md",
    "api-guide.md",
    "release-traceability.md",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--production",
        action="store_true",
        help="Validate supplied deployment environment; no .env fallback",
    )
    args = parser.parse_args()
    failures = []
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        failures.append("Alembic must have one head")
    for path, content in artifacts().items():
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            failures.append(f"Stale artifact: {path.name}")
    for name in DOCUMENTS:
        if not (ROOT / "docs" / name).is_file():
            failures.append(f"Missing document: {name}")
    if args.production:
        try:
            Settings(_env_file=None, app_env="production")
        except ValidationError:
            failures.append("Invalid production settings (values redacted)")
    print("Application version: 0.1.0 (unchanged; no release tag)")
    print("Alembic heads: " + ", ".join(heads))
    for failure in failures:
        print("FAIL " + failure)
    if not failures:
        print("PASS offline release preflight; NOT provider/deployment approval")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
