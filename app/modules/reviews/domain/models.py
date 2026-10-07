from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


def review_values(rating: int, comment: str | None) -> tuple[int, str | None]:
    if type(rating) is not int or not 1 <= rating <= 5:
        raise ValueError("Rating must be an integer from 1 to 5")
    if comment is not None:
        if not isinstance(comment, str):
            raise ValueError("Comment must be plain text")
        comment = comment.strip() or None
        if comment and (
            len(comment) > 1000
            or "<" in comment
            or ">" in comment
            or any(ord(c) < 32 and c not in "\n\t" for c in comment)
        ):
            raise ValueError("Comment must be plain text up to 1000 characters")
    return rating, comment


def completed_order(mode: str, status: str) -> bool:
    return {"LOCAL": "SERVED", "PICKUP": "PICKED_UP", "DELIVERY": "DELIVERED"}.get(
        mode
    ) == status


@dataclass(frozen=True)
class OrderReview:
    id: UUID
    order_id: UUID
    customer_id: UUID
    branch_id: UUID
    rating: int
    comment: str | None
    created_at: datetime
    updated_at: datetime
