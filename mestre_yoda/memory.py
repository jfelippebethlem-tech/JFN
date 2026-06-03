"""Memória persistente do Mestre Yoda.

Três camadas, em SQLite:

* **mensagens** — o histórico bruto da conversa, por chat;
* **resumos** — uma síntese das mensagens antigas, gerada quando o histórico
  cresce demais, para caber no contexto sem perder o fio;
* **fatos** — conhecimento duradouro sobre o usuário (nome, preferências,
  metas), que o Hermes grava e relê entre sessões.

O armazenamento (`MemoryStore`) é puro SQLite e síncrono. A gestão
(`ConversationMemory`) cuida do resumo automático e monta o contexto que o
Hermes recebe. O resumidor é injetado, então os testes rodam sem rede.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

# Assinatura do resumidor: recebe o texto a condensar, devolve o resumo.
Summarizer = Callable[[str], Awaitable[str]]


@dataclass(frozen=True)
class StoredMessage:
    id: int
    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class ConversationContext:
    """O que o Hermes precisa saber para responder."""

    summary: str | None
    facts: dict[str, str]
    messages: list[StoredMessage]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id   INTEGER NOT NULL,
    role      TEXT    NOT NULL,
    content   TEXT    NOT NULL,
    ts        REAL    NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);

CREATE TABLE IF NOT EXISTS summaries (
    chat_id   INTEGER PRIMARY KEY,
    summary   TEXT    NOT NULL,
    ts        REAL    NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS facts (
    chat_id   INTEGER NOT NULL,
    key       TEXT    NOT NULL,
    value     TEXT    NOT NULL,
    ts        REAL    NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (chat_id, key)
);
"""


class MemoryStore:
    """Persistência crua em SQLite. Seguro para uso concorrente via lock."""

    def __init__(self, db_path: str) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- mensagens -------------------------------------------------------
    def add_message(self, chat_id: int, role: str, content: str) -> int:
        if role not in ("user", "assistant"):
            raise ValueError(f"role inválido: {role!r}")
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
                (chat_id, role, content),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def recent_messages(self, chat_id: int, limit: int) -> list[StoredMessage]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, role, content FROM messages "
                "WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        rows.reverse()  # cronológico
        return [StoredMessage(r["id"], r["role"], r["content"]) for r in rows]

    def message_count(self, chat_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return int(row["n"])

    def messages_excluding_recent(
        self, chat_id: int, keep_recent: int
    ) -> list[StoredMessage]:
        """Mensagens mais antigas que as `keep_recent` últimas."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, role, content FROM messages WHERE chat_id = ? "
                "AND id NOT IN ("
                "  SELECT id FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?"
                ") ORDER BY id ASC",
                (chat_id, chat_id, keep_recent),
            ).fetchall()
        return [StoredMessage(r["id"], r["role"], r["content"]) for r in rows]

    def delete_messages_upto(self, chat_id: int, last_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM messages WHERE chat_id = ? AND id <= ?",
                (chat_id, last_id),
            )
            self._conn.commit()

    # --- resumos ---------------------------------------------------------
    def get_summary(self, chat_id: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT summary FROM summaries WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return row["summary"] if row else None

    def set_summary(self, chat_id: int, summary: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO summaries (chat_id, summary) VALUES (?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET "
                "summary = excluded.summary, ts = strftime('%s','now')",
                (chat_id, summary),
            )
            self._conn.commit()

    # --- fatos -----------------------------------------------------------
    def upsert_fact(self, chat_id: int, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO facts (chat_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id, key) DO UPDATE SET "
                "value = excluded.value, ts = strftime('%s','now')",
                (chat_id, key, value),
            )
            self._conn.commit()

    def get_facts(self, chat_id: int) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value FROM facts WHERE chat_id = ? ORDER BY key",
                (chat_id,),
            ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    # --- limpeza ---------------------------------------------------------
    def clear_chat(self, chat_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            self._conn.execute("DELETE FROM summaries WHERE chat_id = ?", (chat_id,))
            self._conn.commit()


def _render_for_summary(
    previous_summary: str | None, messages: list[StoredMessage]
) -> str:
    lines: list[str] = []
    if previous_summary:
        lines.append(f"Resumo anterior:\n{previous_summary}\n")
    lines.append("Trecho da conversa a incorporar:")
    for msg in messages:
        quem = "Usuário" if msg.role == "user" else "Yoda"
        lines.append(f"{quem}: {msg.content}")
    return "\n".join(lines)


class ConversationMemory:
    """Memória de alto nível: monta o contexto e resume quando preciso."""

    def __init__(
        self,
        store: MemoryStore,
        max_history: int,
        summarizer: Summarizer | None = None,
    ) -> None:
        self._store = store
        self._max_history = max_history
        self._summarizer = summarizer

    def set_summarizer(self, summarizer: Summarizer) -> None:
        """Define o resumidor depois da construção (evita ciclo Hermes↔memória)."""
        self._summarizer = summarizer

    def record_user(self, chat_id: int, text: str) -> None:
        self._store.add_message(chat_id, "user", text)

    def record_assistant(self, chat_id: int, text: str) -> None:
        self._store.add_message(chat_id, "assistant", text)

    def remember_fact(self, chat_id: int, key: str, value: str) -> None:
        self._store.upsert_fact(chat_id, key, value)

    def facts(self, chat_id: int) -> dict[str, str]:
        return self._store.get_facts(chat_id)

    def forget(self, chat_id: int) -> None:
        """Esquece a conversa (mensagens + resumo). Fatos persistem."""
        self._store.clear_chat(chat_id)

    def build_context(self, chat_id: int) -> ConversationContext:
        return ConversationContext(
            summary=self._store.get_summary(chat_id),
            facts=self._store.get_facts(chat_id),
            messages=self._store.recent_messages(chat_id, self._max_history),
        )

    async def maybe_summarize(self, chat_id: int) -> bool:
        """Se o histórico passou do limite, condensa o excedente num resumo.

        Mantém as `max_history` mensagens mais recentes intactas e dobra as mais
        antigas dentro do resumo, apagando-as do histórico bruto. Devolve True
        quando resumiu.
        """
        if self._summarizer is None:
            return False
        if self._store.message_count(chat_id) <= self._max_history:
            return False

        old = self._store.messages_excluding_recent(chat_id, self._max_history)
        if not old:
            return False

        previous = self._store.get_summary(chat_id)
        prompt = _render_for_summary(previous, old)
        try:
            summary = await self._summarizer(prompt)
        except Exception:  # noqa: BLE001 - resumo é best-effort; nunca derruba a conversa
            return False

        if not summary or not summary.strip():
            return False

        self._store.set_summary(chat_id, summary.strip())
        self._store.delete_messages_upto(chat_id, old[-1].id)
        return True
