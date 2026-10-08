import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from scripts import postgres_backup as tool


def archive(tmp_path):
    dump = tmp_path / "TEST.dump"
    dump.write_bytes(b"TEST synthetic archive, never production data")
    dump.with_suffix(".dump.sha256").write_text(tool.sha256(dump), encoding="ascii")
    return dump


@pytest.fixture
def restore_environment(monkeypatch):
    monkeypatch.setenv(
        "RESTORE_DATABASE_URL", "postgresql://test:TEST@localhost/isolated_restore"
    )
    monkeypatch.setattr(
        tool,
        "get_settings",
        lambda: SimpleNamespace(
            database_connection_url=make_url("postgresql://u:p@localhost/restaurant_db")
        ),
    )


def test_restore_requires_explicit_confirmation_before_any_io(monkeypatch, tmp_path):
    monkeypatch.setattr(tool, "execute", lambda *a, **k: pytest.fail("Unsafe IO"))
    with pytest.raises(ValueError, match="confirm-isolated-empty"):
        tool.restore(tmp_path / "missing.dump", False)


@pytest.mark.parametrize("checksum", ["", "0" * 64, "corrupt"])
def test_corrupt_checksum_prevents_database_access(
    restore_environment, tmp_path, monkeypatch, checksum
):
    dump = archive(tmp_path)
    dump.with_suffix(".dump.sha256").write_text(checksum, encoding="ascii")
    monkeypatch.setattr(tool, "execute", lambda *a, **k: pytest.fail("Unsafe IO"))
    with pytest.raises(ValueError, match="checksum"):
        tool.restore(dump, True)


@pytest.mark.parametrize("relation_count", [b"1\n", b"60\n", b"unexpected"])
def test_nonempty_or_unparseable_target_is_never_restored(
    restore_environment, tmp_path, monkeypatch, relation_count
):
    calls = []

    def execute(args, env, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=relation_count)

    monkeypatch.setattr(tool, "execute", execute)
    with pytest.raises(ValueError, match="EMPTY"):
        tool.restore(archive(tmp_path), True)
    assert len(calls) == 2 and calls[-1][0] == "psql"
    assert all("--clean" not in c and "--create" not in c for c in calls)


def test_empty_isolated_restore_uses_single_transaction_no_drop_flags(
    restore_environment, tmp_path, monkeypatch
):
    calls = []

    def execute(args, env, **kwargs):
        calls.append(args)
        assert "TEST" not in " ".join(args)
        assert env["PGPASSWORD"] == "TEST"
        return SimpleNamespace(stdout=b"0\n")

    dump = archive(tmp_path)
    # The TEST filename is harmless; only credentials must not enter argv.
    dump = dump.rename(tmp_path / "archive.dump")
    dump.with_suffix(".dump.sha256").write_text(tool.sha256(dump), encoding="ascii")
    monkeypatch.setattr(tool, "execute", execute)
    tool.restore(dump, True)
    assert "--single-transaction" in calls[-1]
    assert "--exit-on-error" in calls[-1]
    assert all("--clean" not in c and "--create" not in c for c in calls)


@pytest.mark.parametrize(
    "failure", [OSError("TEST secret"), subprocess.TimeoutExpired("psql", 1)]
)
def test_tool_failures_redacted(monkeypatch, failure):
    def broken(*args, **kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", broken)
    with pytest.raises(ValueError) as exc:
        tool.execute(["psql"], {})
    assert "TEST secret" not in str(exc.value)


def test_backup_never_accepts_repository_output(monkeypatch):
    monkeypatch.setenv("BACKUP_DATABASE_URL", "postgresql://u:p@localhost/source")
    with pytest.raises(ValueError, match="outside"):
        tool.backup(tool.ROOT / "backups")


def test_backup_requires_explicit_url_no_normal_fallback(monkeypatch):
    monkeypatch.delenv("BACKUP_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="Explicit"):
        tool.connection_environment("BACKUP_DATABASE_URL")


def test_successful_backup_checksum_and_restricted_file_permissions(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("BACKUP_DATABASE_URL", "postgresql://u:TEST@localhost/source")

    def execute(args, env, **kwargs):
        assert "TEST" not in " ".join(args)
        if args[0] == "pg_dump":
            kwargs["stdout"].write(b"TEST archive")
            assert "--format=custom" in args
        return SimpleNamespace(stdout=b"")

    monkeypatch.setattr(tool, "execute", execute)
    tool.backup(tmp_path)
    dump = next(tmp_path.glob("*.dump"))
    checksum = dump.with_suffix(".dump.sha256")
    assert checksum.read_text().split()[0] == tool.sha256(dump)
    assert dump.stat().st_mode & 0o777 == 0o600
    assert checksum.stat().st_mode & 0o777 == 0o600
