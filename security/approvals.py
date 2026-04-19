from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Awaitable, Callable
from uuid import uuid4

from security.models import ActionRequest, PolicyDecision


ApprovalCallback = Callable[[], Awaitable[str]]


@dataclass(slots=True)
class PendingApproval:
    action: ActionRequest
    decision: PolicyDecision
    callback: ApprovalCallback
    approval_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def summary(self) -> str:
        return self.action.description

    def to_dict(self) -> dict:
        return {
            "approval_id": self.approval_id,
            "request_id": self.action.request_id,
            "summary": self.summary,
            "action_type": self.action.action_type.value,
            "source": self.action.source.value,
            "target": self.action.target,
            "risk": self.decision.risk.value,
            "trust_zone": self.decision.trust_zone.value,
            "reasons": list(self.decision.reasons),
            "created_at": self.created_at.isoformat(timespec="seconds") + "Z",
        }


class ApprovalManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pending: "OrderedDict[str, PendingApproval]" = OrderedDict()

    def submit(self, action: ActionRequest, decision: PolicyDecision, callback: ApprovalCallback) -> PendingApproval:
        pending = PendingApproval(action=action, decision=decision, callback=callback)
        with self._lock:
            self._pending[pending.approval_id] = pending
        return pending

    def approve(self, approval_id: str | None = None) -> PendingApproval | None:
        with self._lock:
            if not self._pending:
                return None
            if approval_id is None:
                _, pending = self._pending.popitem(last=False)
                return pending
            return self._pending.pop(approval_id, None)

    def deny(self, approval_id: str | None = None) -> PendingApproval | None:
        return self.approve(approval_id)

    def clear(self) -> int:
        with self._lock:
            count = len(self._pending)
            self._pending.clear()
            return count

    def snapshot(self) -> dict:
        with self._lock:
            items = [pending.to_dict() for pending in self._pending.values()]
        return {
            "count": len(items),
            "items": items,
            "first": items[0] if items else {},
        }
