import json

from scripts.contracts import contract_app, validate_contract
from scripts.export_openapi import artifacts


def test_openapi_and_inventory_match_export():
    for path, content in artifacts().items():
        assert path.read_text(encoding="utf-8") == content


def test_openapi_contract_operations_bearer_sse_and_idempotency():
    app = contract_app()
    schema = app.openapi()
    assert not validate_contract(app, schema)
    assert schema["openapi"].startswith("3.")
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method != "post":
                continue
            if path in {
                "/api/v1/orders",
                "/api/v1/promotions/roulette/spins",
            } or path.endswith(("/online", "/online/process", "/process")):
                assert any(
                    p.get("name") == "Idempotency-Key" and p.get("required")
                    for p in operation.get("parameters", [])
                ), path
    assert json.loads(json.dumps(schema)) == schema
