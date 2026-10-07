from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branches.infrastructure.persistence.models import (
    BranchHourModel,
    BranchModel,
)
from app.modules.branches.infrastructure.persistence.repositories import (
    administrative_branch_query,
)
from app.shared.application.administration import AdministrationConflict


class SQLAlchemyBranchAdministrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_branches(self, user_id: UUID, limit: int, offset: int) -> list[dict]:
        rows = (
            await self.session.execute(
                select(BranchModel)
                .where(
                    BranchModel.id.in_(
                        administrative_branch_query(user_id, "BRANCH_VIEW")
                        .with_only_columns(BranchModel.id)
                        .order_by(None)
                    )
                )
                .order_by(BranchModel.name, BranchModel.id)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return [row.model_dump() for row in rows]

    async def get_branch(self, branch_id: UUID, *, lock: bool = False) -> dict | None:
        query = select(BranchModel).where(BranchModel.id == branch_id)
        if lock:
            query = query.with_for_update()
        row = (
            await self.session.execute(query.execution_options(populate_existing=True))
        ).scalar_one_or_none()
        if row is None:
            return None
        hours = (
            await self.session.execute(
                select(BranchHourModel)
                .where(BranchHourModel.branch_id == branch_id)
                .order_by(BranchHourModel.day_of_week)
            )
        ).scalars()
        return {
            **row.model_dump(),
            "hours": [
                {
                    "day_of_week": h.day_of_week,
                    "open_time": h.open_time,
                    "close_time": h.close_time,
                    "is_closed": h.is_closed,
                }
                for h in hours
            ],
        }

    async def create_branch(self, values: dict) -> dict:
        if await self.session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM branches WHERE lower(code)=lower(:code))"
            ),
            {"code": values["code"]},
        ):
            raise AdministrationConflict(
                "BRANCH_CODE_ALREADY_EXISTS", "Branch code already exists"
            )
        row = BranchModel(**values)
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError:
            raise AdministrationConflict(
                "BRANCH_CODE_ALREADY_EXISTS", "Branch code already exists"
            ) from None
        return row.model_dump()

    async def update_branch(self, branch_id: UUID, values: dict) -> dict:
        row = await self.session.get(BranchModel, branch_id)
        for name, value in values.items():
            setattr(row, name, value)
        await self.session.flush()
        return await self.get_branch(branch_id)

    async def replace_hours(self, branch_id: UUID, hours: list[dict]) -> list[dict]:
        for hour in hours:
            await self.session.execute(
                text(
                    "INSERT INTO branch_hours(branch_id,day_of_week,open_time,"
                    "close_time,is_closed) "
                    "VALUES (:branch,:day_of_week,:open_time,:close_time,:is_closed) "
                    "ON CONFLICT(branch_id,day_of_week) DO UPDATE SET "
                    "open_time=EXCLUDED.open_time,close_time=EXCLUDED.close_time,is_closed=EXCLUDED.is_closed"
                ),
                {"branch": branch_id, **hour},
            )
        return hours

    async def assign_creator(self, branch_id: UUID, user_id: UUID) -> None:
        await self.session.execute(
            text(
                "INSERT INTO staff_assignments(user_id,branch_id,role_id,"
                "employee_code) "
                "SELECT :user,:branch,id,'ADMIN-OWNER' FROM roles WHERE "
                "code='ADMIN' AND scope='BRANCH'"
            ),
            {"user": user_id, "branch": branch_id},
        )
        if not await self.session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM staff_assignments WHERE "
                "branch_id=:branch AND user_id=:user)"
            ),
            {"branch": branch_id, "user": user_id},
        ):
            raise AdministrationConflict(
                "ADMIN_ROLE_UNAVAILABLE", "Branch administrator role is unavailable"
            )

    async def deactivate_branch(self, branch_id: UUID) -> None:
        await self.session.execute(
            text("UPDATE branches SET is_active=false,deleted_at=now() WHERE id=:id"),
            {"id": branch_id},
        )

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
