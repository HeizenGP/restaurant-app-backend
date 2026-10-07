"""Administrative contact is not proof of identity or telephone ownership."""

import re


def customer_fields(values: dict, *, creating: bool) -> dict:
    allowed = (
        {"full_name", "phone", "email"}
        if creating
        else {"full_name", "first_name", "last_name", "email"}
    )
    if not values or set(values) - allowed:
        raise ValueError("Unsupported customer fields")
    if creating and not {"full_name", "phone"} <= values.keys():
        raise ValueError("Name and phone are required")
    normalized = dict(values)
    for key, maximum in (("full_name", 180), ("first_name", 100), ("last_name", 120)):
        if key not in values:
            continue
        value = values[key]
        if value is None and key == "last_name":
            continue
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > maximum
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("Invalid customer name")
        normalized[key] = value.strip()
    if "phone" in values and (
        not isinstance(values["phone"], str)
        or not re.fullmatch(r"\+?[0-9]{9,15}", values["phone"])
    ):
        raise ValueError("Invalid phone")
    email = values.get("email")
    if email is not None:
        if (
            not isinstance(email, str)
            or len(email) > 254
            or email.count("@") != 1
            or any(c.isspace() or ord(c) < 32 for c in email)
            or not all(email.split("@"))
        ):
            raise ValueError("Invalid email")
        normalized["email"] = email.lower()
    if "full_name" in values and set(values) & {"first_name", "last_name"}:
        raise ValueError("Guest and registered names cannot be mixed")
    return normalized
