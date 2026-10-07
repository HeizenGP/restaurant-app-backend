from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.application.admin_ports import AdministrativeCustomer
from app.shared.application.administration import (
    AdministrationConflict,
    AdministrationInvalid,
)

VISIBLE = (
    "(c.created_by_branch_id=:branch OR EXISTS (SELECT 1 FROM orders o WHERE "
    "o.customer_id=c.id AND o.branch_id=:branch))"
)
FIELDS = (
    "c.id,c.full_name,c.phone,c.email,(c.user_id IS NULL) AS is_guest,"
    "c.phone_verified_at,c.created_at,c.updated_at,u.first_name,u.last_name"
)
CUSTOMERS_FROM = "FROM customers c LEFT JOIN users u ON u.id=c.user_id"


class SQLAlchemyCustomerAdministrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_customers(
        self, branch_id: UUID, search: str | None, limit: int, offset: int
    ) -> list[AdministrativeCustomer]:
        params = {"branch": branch_id, "limit": limit, "offset": offset}
        search_clause = ""
        if search:
            # Escape LIKE metacharacters: this is a literal bounded prefix search.
            params["search"] = (
                search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%"
            )
            params["search"] = params["search"].lower()
            search_clause = (
                " AND (lower(c.full_name) LIKE :search OR c.phone LIKE :search "
                "OR lower(c.email::text) LIKE :search)"
            )
        rows = await self.session.execute(
            text(
                f"SELECT {FIELDS} {CUSTOMERS_FROM} WHERE "
                f"{VISIBLE}{search_clause} ORDER BY c.created_at DESC,c.id DESC "
                f"LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        return [AdministrativeCustomer(**row) for row in rows.mappings()]

    async def get_customer(
        self, branch_id: UUID, customer_id: UUID, *, lock: bool = False
    ) -> AdministrativeCustomer | None:
        rows = await self.session.execute(
            text(
                f"SELECT {FIELDS} {CUSTOMERS_FROM} WHERE c.id=:id AND {VISIBLE}"
                + (" FOR UPDATE OF c" if lock else "")
            ),
            {"branch": branch_id, "id": customer_id},
        )
        row = rows.mappings().one_or_none()
        return AdministrativeCustomer(**row) if row else None

    async def create_customer(
        self, branch_id: UUID, values: dict
    ) -> AdministrativeCustomer:
        duplicate = await self.session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM customers WHERE phone=:phone) OR "
                "EXISTS(SELECT 1 FROM users WHERE phone=:phone)"
            ),
            {"phone": values["phone"]},
        )
        if duplicate:
            raise AdministrationConflict(
                "CUSTOMER_PHONE_ALREADY_EXISTS", "Phone already belongs to an identity"
            )
        try:
            id_ = await self.session.scalar(
                text(
                    "INSERT INTO customers(full_name,phone,email,"
                    "created_by_branch_id) VALUES (:full_name,:phone,:email,"
                    ":branch) RETURNING id"
                ),
                {**values, "email": values.get("email"), "branch": branch_id},
            )
        except IntegrityError:
            raise AdministrationConflict(
                "CUSTOMER_PHONE_ALREADY_EXISTS", "Phone already belongs to an identity"
            ) from None
        return await self.get_customer(branch_id, id_)

    async def update_customer(
        self, branch_id: UUID, customer_id: UUID, values: dict
    ) -> AdministrativeCustomer:
        # Caller holds Customer UPDATE; identity owners use the same Customer ->
        # User order.
        identity = (
            await self.session.execute(
                text("SELECT user_id FROM customers WHERE id=:id FOR UPDATE"),
                {"id": customer_id},
            )
        ).one()
        user_id = identity.user_id
        if user_id:
            if "full_name" in values:
                raise AdministrationInvalid(
                    "INVALID_REQUEST_DATA",
                    "Registered customers use first_name and last_name",
                )
            user = (
                (
                    await self.session.execute(
                        text(
                            "SELECT first_name,last_name,email,phone FROM users "
                            "WHERE id=:id FOR UPDATE"
                        ),
                        {"id": user_id},
                    )
                )
                .mappings()
                .one()
            )
            merged = {**user, **values}
            if merged["email"] is None and merged["phone"] is None:
                raise AdministrationInvalid(
                    "INVALID_REQUEST_DATA", "User must retain a contact identifier"
                )
            full_name = " ".join(
                x for x in (merged["first_name"], merged["last_name"]) if x
            )
            if not full_name or len(full_name) > 180:
                raise AdministrationInvalid(
                    "INVALID_REQUEST_DATA", "Full name must contain 1 to 180 characters"
                )
            if "email" in values and values["email"] is not None:
                if await self.session.scalar(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM users WHERE email=:email "
                        "AND id<>:id)"
                    ),
                    {"email": values["email"], "id": user_id},
                ):
                    raise AdministrationConflict(
                        "CUSTOMER_EMAIL_ALREADY_EXISTS",
                        "Email already belongs to an identity",
                    )
            try:
                await self.session.execute(
                    text(
                        "UPDATE users SET first_name=:first_name,last_name=:last_name,"
                        "email_verified_at=CASE WHEN email IS DISTINCT FROM "
                        "CAST(:email AS citext) THEN NULL ELSE email_verified_at END,"
                        "email=:email WHERE id=:id"
                    ),
                    {**merged, "id": user_id},
                )
            except IntegrityError:
                raise AdministrationConflict(
                    "CUSTOMER_EMAIL_ALREADY_EXISTS",
                    "Email already belongs to an identity",
                ) from None
            changes = {"full_name": full_name, "email": merged["email"]}
        else:
            if set(values) - {"full_name", "email"}:
                raise AdministrationInvalid(
                    "INVALID_REQUEST_DATA", "Guests use full_name and email"
                )
            changes = values
        # Column names come only from the owned allowlist, never arbitrary request
        # fields.
        await self.session.execute(
            text(
                "UPDATE customers SET "
                + ",".join(f"{key}=:{key}" for key in changes)
                + " WHERE id=:id"
            ),
            {**changes, "id": customer_id},
        )
        return await self.get_customer(branch_id, customer_id)

    async def delete_customer(self, branch_id: UUID, customer_id: UUID) -> None:
        row = (
            await self.session.execute(
                text(
                    "SELECT user_id,created_by_branch_id,phone,phone_verified_at "
                    "FROM customers WHERE "
                    "id=:id FOR UPDATE"
                ),
                {"id": customer_id},
            )
        ).one()
        if row.user_id:
            raise AdministrationConflict(
                "REGISTERED_CUSTOMER_CANNOT_BE_DELETED",
                "Registered customer identities cannot be deleted",
            )
        if row.created_by_branch_id != branch_id:
            raise AdministrationConflict(
                "CUSTOMER_HAS_HISTORY",
                "Only unused admin-created guests can be deleted",
            )
        if row.phone_verified_at is not None:
            raise AdministrationConflict(
                "CUSTOMER_HAS_HISTORY", "Customer has authentication history"
            )
        # Deliberately also preserve addresses and OTP history despite legacy
        # CASCADE/SET NULL.
        for table in (
            "orders",
            "carts",
            "customer_addresses",
            "otp_challenges",
            "customer_notifications",
            "notification_devices",
            "cancellation_requests",
        ):
            condition = "customer_id=:id"
            params = {"id": customer_id}
            if await self.session.scalar(
                text(f"SELECT EXISTS(SELECT 1 FROM {table} WHERE {condition})"),
                params,
            ):
                raise AdministrationConflict(
                    "CUSTOMER_HAS_HISTORY", "Customer has persisted history"
                )
        try:
            await self.session.execute(
                text("DELETE FROM customers WHERE id=:id"), {"id": customer_id}
            )
        except IntegrityError:
            raise AdministrationConflict(
                "CUSTOMER_HAS_HISTORY", "Customer has persisted history"
            ) from None

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
