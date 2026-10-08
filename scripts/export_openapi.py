"""Export/check the API and inventory without migrations or startup DB access."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.contracts import contract_app, inventory, validate_contract  # noqa: E402


def artifacts():
    application = contract_app()
    schema = application.openapi()
    errors = validate_contract(application, schema)
    if errors:
        raise ValueError("; ".join(errors))
    return {
        ROOT / "docs/openapi.json": json.dumps(
            schema, indent=2, sort_keys=True, ensure_ascii=False
        )
        + "\n",
        ROOT / "docs/api-inventory.md": inventory(application, schema),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare without writing")
    args = parser.parse_args()
    for path, content in artifacts().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                print(f"STALE contract: {path.name}")
                return 1
        else:
            path.write_text(content, encoding="utf-8")
    print("PASS OpenAPI + route inventory" + (" check" if args.check else " export"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
