import os
import subprocess
import sys

import pytest

from scripts.export_openapi import ROOT


@pytest.mark.parametrize("script", ["release_check.py", "export_openapi.py"])
def test_offline_scripts_ignore_invalid_deployment_env_but_check_it_explicitly(script):
    environment = os.environ.copy()
    for name in ("JWT_SECRET", "OTP_PEPPER", "DB_PASSWORD"):
        environment.pop(name, None)
    environment.update(
        APP_ENV="production",
        APP_DEBUG="false",
        DATABASE_URL="postgresql://test:TEST_PRIVATE_SENTINEL@localhost/invalid",
    )
    arguments = ["--production"] if script == "release_check.py" else ["--check"]
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = result.stdout + result.stderr
    assert "TEST_PRIVATE_SENTINEL" not in output and "Traceback" not in output
    if script == "release_check.py":
        assert result.returncode == 1
        assert "Invalid production settings (values redacted)" in output
    else:
        assert result.returncode == 0
        assert "PASS OpenAPI" in output
