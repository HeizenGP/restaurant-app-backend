"""Safe backup/isolated restore tooling; credentials never enter argv/output."""

import argparse
import hashlib
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.engine import make_url  # noqa: E402

from app.shared.infrastructure.config.settings import get_settings  # noqa: E402

EMPTY_QUERY = """SELECT count(*) FROM pg_class c JOIN pg_namespace n
ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p','v','m','f','S')
AND n.nspname NOT IN ('pg_catalog','information_schema')
AND n.nspname NOT LIKE 'pg_toast%'"""


def connection_environment(variable):
    raw = os.environ.get(variable)
    if not raw:
        raise ValueError(f"Explicit {variable} required; no normal-DB fallback")
    try:
        url = make_url(raw)
    except Exception:
        raise ValueError("Invalid PostgreSQL URL (redacted)") from None
    if (
        url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}
        or not url.host
        or not url.database
    ):
        raise ValueError("Explicit PostgreSQL host/database required")
    if url.query:
        raise ValueError(
            "URL query options not supported; "
            "configure PGSSLMODE/PGSSLROOTCERT separately"
        )
    env = os.environ.copy()
    # Clear inherited libpq routing; an explicit URL is the ONLY destination.
    for name in ("PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR", "PGOPTIONS", "PGPASSWORD"):
        env.pop(name, None)
    env.update(
        PGHOST=url.host,
        PGPORT=str(url.port or 5432),
        PGDATABASE=url.database,
        PGCONNECT_TIMEOUT="5",
    )
    if url.username:
        env["PGUSER"] = url.username
    else:
        env.pop("PGUSER", None)
    if url.password:
        env["PGPASSWORD"] = url.password
    return url, env


def validate_restore_target(url, normal):
    name = (url.database or "").lower()
    if any(word in name for word in ("production", "prod")):
        raise ValueError("Production restores are never automated")
    parts = name.split("_")
    if not {"test", "restore", "staging"}.intersection(parts):
        raise ValueError("Restore requires a test/restore/staging database name marker")
    local = {"localhost", "127.0.0.1", "::1"}
    same_host = url.host == normal.host or {url.host, normal.host} <= local
    if (
        same_host
        and (url.port or 5432) == (normal.port or 5432)
        and url.database == normal.database
    ):
        raise ValueError("Refusing to restore the normal database")


def execute(arguments, env, **kwargs):
    try:
        result = subprocess.run(
            arguments,
            env=env,
            stderr=subprocess.PIPE,
            timeout=900,
            check=False,
            **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError(
            "PostgreSQL tool unavailable/timed out (diagnostics redacted)"
        ) from None
    if result.returncode:
        raise ValueError("PostgreSQL tool failed (diagnostics redacted)")
    return result


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def backup(output):
    _, env = connection_environment("BACKUP_DATABASE_URL")
    directory = output.resolve()
    if directory == ROOT or ROOT in directory.parents:
        raise ValueError("Backups must be outside the repository")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = directory / (
        datetime.now(UTC).strftime("restaurant-%Y%m%dT%H%M%S%fZ") + ".dump"
    )
    with destination.open("xb") as stream:
        os.chmod(destination, 0o600)
        execute(
            ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--no-password"],
            env,
            stdout=stream,
        )
    execute(["pg_restore", "--list", str(destination)], env, stdout=subprocess.DEVNULL)
    checksum = destination.with_suffix(".dump.sha256")
    with checksum.open("x", encoding="ascii") as stream:
        os.chmod(checksum, 0o600)
        stream.write(sha256(destination) + "  " + destination.name + "\n")
    print("PASS backup + archive list + SHA-256: " + str(destination))


def restore(archive, confirmed):
    if not confirmed:
        raise ValueError("Restore requires --confirm-isolated-empty")
    url, env = connection_environment("RESTORE_DATABASE_URL")
    validate_restore_target(url, get_settings().database_connection_url)
    archive = archive.resolve(strict=True)
    checksum_parts = (
        archive.with_suffix(archive.suffix + ".sha256")
        .read_text(encoding="ascii")
        .split()
    )
    if not checksum_parts:
        raise ValueError("Archive checksum missing")
    expected = checksum_parts[0]
    if len(expected) != 64 or sha256(archive) != expected:
        raise ValueError("Archive checksum mismatch")
    execute(["pg_restore", "--list", str(archive)], env, stdout=subprocess.DEVNULL)
    result = execute(
        [
            "psql",
            "-X",
            "--no-password",
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-c",
            EMPTY_QUERY,
        ],
        env,
        stdout=subprocess.PIPE,
    )
    if result.stdout.strip() != b"0":
        raise ValueError("Restore target must be EMPTY; no objects will be removed")
    execute(
        [
            "pg_restore",
            "--single-transaction",
            "--exit-on-error",
            "--no-owner",
            "--no-acl",
            "--no-password",
            "--dbname",
            url.database,
            str(archive),
        ],
        env,
        stdout=subprocess.DEVNULL,
    )
    print("PASS isolated restore; verify Alembic/data/readiness separately")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    dump = commands.add_parser("backup", help="Explicit BACKUP_DATABASE_URL only")
    dump.add_argument(
        "--output-dir", type=Path, default=Path.home() / "restaurant-backups"
    )
    load = commands.add_parser(
        "restore", help="Explicit RESTORE_DATABASE_URL, empty target only"
    )
    load.add_argument("archive", type=Path)
    load.add_argument("--confirm-isolated-empty", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "backup":
            backup(args.output_dir)
        else:
            restore(args.archive, args.confirm_isolated_empty)
    except (ValueError, OSError):
        # Never echo exception values, DSNs, passwords, tool output or tracebacks.
        print(
            "FAIL backup/restore: check explicit URL, target guard, checksum, "
            "tools and permissions; no credentials printed",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
