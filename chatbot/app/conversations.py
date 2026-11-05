"""Conversazioni limitate, con persistenza SQLite per il backend a singolo worker."""

from __future__ import annotations

import fcntl
import json
import os
import secrets
import sqlite3
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
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


class SQLiteConversationStore(MemoryConversationStore):
    """Riusa i limiti in memoria e salva atomicamente solo i turni completati."""

    def __init__(self, path: str | Path, clock=time.time):
        super().__init__(clock=clock)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            # ponytail: un solo worker; store e rate limiter condivisi prima di scalare.
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(descriptor)
            with self._database() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL,
                    turns INTEGER NOT NULL, history TEXT NOT NULL
                )""")
                db.execute("DELETE FROM conversations WHERE expires <= ?", (self.clock(),))
                for cid, owner, expires, turns, history in db.execute(
                    "SELECT id, owner, expires, turns, history FROM conversations"
                ):
                    messages = [
                        (HumanMessage if i % 2 == 0 else AIMessage)(content=content)
                        for i, content in enumerate(json.loads(history))
                    ]
                    self.rows[cid] = Conversation(cid, owner, expires, messages, turns)
        except BaseException:
            self.close()
            raise

    @contextmanager
    def _database(self):
        try:
            with closing(sqlite3.connect(self.path, timeout=1)) as db, db:
                db.execute("PRAGMA secure_delete = ON")
                yield db
        except sqlite3.Error:
            raise ConversationError(503, "Conversazioni temporaneamente non disponibili") from None

    def acquire(self, conversation_id: str | None, owner: str) -> Conversation:
        with self._database() as db:
            db.execute("DELETE FROM conversations WHERE expires <= ?", (self.clock(),))
        return super().acquire(conversation_id, owner)

    def commit(self, conversation: Conversation, message: str, reply: str) -> None:
        candidate = replace(conversation, history=list(conversation.history))
        super().commit(candidate, message, reply)
        with self._database() as db:
            db.execute(
                "INSERT OR REPLACE INTO conversations VALUES (?, ?, ?, ?, ?)",
                (candidate.id, candidate.owner, candidate.expires, candidate.turns,
                 json.dumps([m.content for m in candidate.history], ensure_ascii=False)),
            )
        conversation.history = candidate.history
        conversation.turns = candidate.turns

    def close(self) -> None:
        if self._lock is not None:
            os.close(self._lock)
            self._lock = None


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
