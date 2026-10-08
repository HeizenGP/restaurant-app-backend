from scripts.contracts import (
    PUBLIC_OPERATIONS,
    VERIFIED_WEBHOOKS,
    contract_app,
    validate_contract,
)


def test_every_operation_has_explicit_security_policy():
    app = contract_app()
    schema = app.openapi()
    observed_public = set()
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            key = method.upper(), path
            if not operation.get("security"):
                observed_public.add(key)
                assert key in PUBLIC_OPERATIONS | VERIFIED_WEBHOOKS
            if "/admin/" in path or "/kitchen/" in path:
                assert operation.get("security") == [{"HTTPBearer": []}]
    assert (
        observed_public
        == (PUBLIC_OPERATIONS - {("GET", "/"), ("GET", "/health")}) | VERIFIED_WEBHOOKS
    )


def test_new_unprotected_admin_and_debug_routes_are_rejected():
    app = contract_app()

    @app.get("/api/v1/admin/unprotected")
    @app.get("/api/v1/debug")
    async def unsafe():
        return {}

    assert len(validate_contract(app, app.openapi())) >= 2


def test_duplicate_routes_are_detected_before_openapi_can_hide_them():
    app = contract_app()

    @app.get("/api/v1/health")
    async def duplicate():
        return {}

    assert any("Duplicate route" in e for e in validate_contract(app, app.openapi()))
