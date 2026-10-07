from dataclasses import replace

from app.modules.cancellations.domain.models import (
    CancellationRuleError,
    RequestStatus,
    plain_text,
)


def decide_request(request, target, actor, now, note=None):
    if not isinstance(target, RequestStatus) or target == RequestStatus.PENDING:
        raise CancellationRuleError("Invalid evaluation")
    note = plain_text(note, 2000) if note is not None else None
    if request.status != RequestStatus.PENDING:
        if (request.status, request.evaluated_by_user_id, request.evaluation_note) == (
            target,
            actor,
            note,
        ):
            return request
        raise CancellationRuleError("Request already evaluated")
    return replace(
        request,
        status=target,
        evaluated_by_user_id=actor,
        evaluated_at=now,
        evaluation_note=note,
        updated_at=now,
    )
