from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Favorite:
    id: UUID
    user_id: UUID
    product_id: UUID
    created_at: datetime
