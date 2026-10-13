"""Audit trail: who changed what, and when."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .models import AuditLog, User


def record(db: Session, user: User | None, action: str, entity: str, entity_id="", detail: dict | None = None) -> None:
    """Add an audit entry to the current transaction (committed with the change itself)."""
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else "system",
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            detail=json.dumps(detail or {}, default=str, ensure_ascii=False),
        )
    )
