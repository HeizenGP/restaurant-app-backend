from scripts.contracts import contract_app

PRIVATE = {
    "password_hash",
    "refresh_token_hash",
    "otp_code",
    "code_hash",
    "jwt_secret",
    "otp_pepper",
    "push_token",
    "request_fingerprint",
    "request_key_hash",
    "idempotency_key_hash",
    "random_draw",
}


def property_names(schema, schemas, visited=None):
    visited = set() if visited is None else visited
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        if name in visited:
            return set()
        visited.add(name)
        return property_names(schemas[name], schemas, visited)
    result = set(schema.get("properties", {}))
    for value in schema.get("properties", {}).values():
        result |= property_names(value, schemas, visited)
    for key in ("anyOf", "oneOf", "allOf"):
        for value in schema.get(key, []):
            result |= property_names(value, schemas, visited)
    if "items" in schema:
        result |= property_names(schema["items"], schemas, visited)
    return result


def test_all_response_schemas_omit_storage_secrets():
    api = contract_app().openapi()
    schemas = api["components"]["schemas"]
    for path, methods in api["paths"].items():
        for operation in methods.values():
            for response in operation["responses"].values():
                for media in response.get("content", {}).values():
                    fields = property_names(media.get("schema", {}), schemas)
                    assert not fields & PRIVATE, (path, fields & PRIVATE)
                    if "realtime" in path or "/kitchen/" in path:
                        assert not fields & {
                            "email",
                            "phone",
                            "address_line",
                            "provider_reference",
                            "recipient_document_number",
                        }, path


def test_request_push_token_is_allowed_but_response_is_not():
    api = contract_app().openapi()
    schemas = api["components"]["schemas"]
    assert "push_token" in schemas["DeviceRequest"]["properties"]
    assert "push_token" not in schemas["DeviceResponse"]["properties"]
