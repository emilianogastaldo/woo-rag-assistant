"""Bounded process-local storage. Replace through ConversationStore for shared deployments."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.config import settings


class ConversationError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


@dataclass
class Conversation:
    id: str
    owner: str
    expires: float
    history: list[BaseMessage] = field(default_factory=list)
    turns: int = 0
    busy: bool = False


class ConversationStore(Protocol):
    def acquire(self, conversation_id: str | None, owner: str) -> Conversation: ...
    def commit(self, conversation: Conversation, message: str, reply: str) -> None: ...
    def release(self, conversation: Conversation) -> None: ...


class MemoryConversationStore:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.rows: dict[str, Conversation] = {}

    def acquire(self, conversation_id: str | None, owner: str) -> Conversation:
        now = self.clock()
        self.rows = {key: row for key, row in self.rows.items() if row.busy or row.expires > now}
        if conversation_id is not None:
            row = self.rows.get(conversation_id)
            if row is None or row.owner != owner or row.expires <= now:
                raise ConversationError(404, "Conversazione non disponibile")
        else:
            if len(self.rows) >= settings.conversation_capacity:
                raise ConversationError(503, "Conversazioni temporaneamente esaurite")
            row = Conversation(
                secrets.token_urlsafe(32), owner, now + settings.conversation_ttl_seconds
            )
            self.rows[row.id] = row
        if row.busy:
            raise ConversationError(409, "Conversazione occupata")
        if row.turns >= settings.conversation_max_turns:
            raise ConversationError(409, "Limite conversazione raggiunto")
        row.busy = True
        return row

    def commit(self, conversation: Conversation, message: str, reply: str) -> None:
        conversation.turns += 1
        conversation.history.extend([HumanMessage(content=message), AIMessage(content=reply)])
        while (
            sum(len(m.content.encode()) for m in conversation.history) > settings.history_max_bytes
        ):
            del conversation.history[:2]

    def release(self, conversation: Conversation) -> None:
        conversation.busy = False


class MemoryRateLimiter:
    """Fixed windows; refuse new keys when full instead of evicting active limits."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.rows: dict[str, tuple[float, int]] = {}

    def check(self, key: str) -> int:
        now = self.clock()
        self.rows = {k: v for k, v in self.rows.items() if v[0] > now}
        if key not in self.rows and len(self.rows) >= settings.rate_limit_capacity:
            return max(1, int(settings.rate_limit_window_seconds))
        end, count = self.rows.get(key, (now + settings.rate_limit_window_seconds, 0))
        if count >= settings.rate_limit_requests:
            return max(1, int(end - now) + 1)
        self.rows[key] = end, count + 1
        return 0
