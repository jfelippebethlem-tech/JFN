"""
LLM Router — routes tasks between Claude API and local Ollama.

Tracks monthly token usage and budget, preferring local models
for simple tasks to reduce API costs.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from compliance_agent.llm.local import (
    DEFAULT_MODEL,
    classify_text,
    extract_entities,
    summarize,
    is_available as _check_ollama,
)

MONTHLY_TOKEN_LIMIT = int(os.environ.get("MONTHLY_TOKEN_LIMIT", "500000"))

BUDGET_FILE = Path("data/llm_budget.json")

# Tasks that can be handled by local Ollama (no Claude API needed)
SIMPLE_TASKS = {"classify_contract", "summarize_doerj", "extract_entities", "categorize_alert"}


class LLMRouter:
    """
    Routes LLM tasks between local Ollama and Claude API.

    Budget tracking is persisted to data/llm_budget.json indexed by month (YYYY-MM).
    """

    def __init__(self):
        self._ollama_ok: Optional[bool] = None
        self._budget_data: Optional[dict] = None

    # ── Budget tracking ───────────────────────────────────────────────────────

    def _load_budget(self) -> dict:
        if self._budget_data is not None:
            return self._budget_data
        BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
        if BUDGET_FILE.exists():
            try:
                self._budget_data = json.loads(BUDGET_FILE.read_text(encoding="utf-8"))
                return self._budget_data
            except Exception:
                pass
        self._budget_data = {}
        return self._budget_data

    def _save_budget(self):
        if self._budget_data is None:
            return
        BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            BUDGET_FILE.write_text(
                json.dumps(self._budget_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def record_claude_usage(self, input_tokens: int, output_tokens: int):
        """Record Claude API token usage for the current month."""
        data = self._load_budget()
        month = datetime.now().strftime("%Y-%m")
        if month not in data:
            data[month] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        data[month]["input_tokens"] += input_tokens
        data[month]["output_tokens"] += output_tokens
        data[month]["total_tokens"] += input_tokens + output_tokens
        self._budget_data = data
        self._save_budget()

    def tokens_used_this_month(self) -> int:
        """Return total tokens used in the current calendar month."""
        data = self._load_budget()
        month = datetime.now().strftime("%Y-%m")
        return data.get(month, {}).get("total_tokens", 0)

    def budget_remaining_pct(self) -> float:
        """Return the fraction of monthly budget remaining (0.0–1.0)."""
        if MONTHLY_TOKEN_LIMIT <= 0:
            return 1.0
        used = self.tokens_used_this_month()
        remaining = max(0, MONTHLY_TOKEN_LIMIT - used)
        return round(remaining / MONTHLY_TOKEN_LIMIT, 4)

    # ── Routing logic ─────────────────────────────────────────────────────────

    def _ollama_available(self) -> bool:
        """Lazy-cached check for Ollama availability."""
        if self._ollama_ok is None:
            self._ollama_ok = _check_ollama()
        return self._ollama_ok

    def should_use_local(self, task: str) -> bool:
        """Return True if task should be handled by local Ollama."""
        return self._ollama_available() and task in SIMPLE_TASKS

    # ── Public task methods ───────────────────────────────────────────────────

    def classify(self, text: str, categories: list[str]) -> str:
        """
        Classify text into one of the provided categories.

        Uses Ollama if available, otherwise returns categories[0].
        """
        if self._ollama_available():
            return classify_text(text, categories)
        return categories[0] if categories else ""

    def summarize(self, text: str, max_words: int = 100) -> str:
        """
        Summarize text in at most max_words words.

        Uses Ollama if available, otherwise returns first 300 chars.
        """
        if self._ollama_available():
            return summarize(text, max_words=max_words)
        return text[:300] + ("..." if len(text) > 300 else "")

    def extract_entities(self, text: str) -> dict:
        """
        Extract named entities from text.

        Uses Ollama if available, otherwise returns empty dict.
        """
        if self._ollama_available():
            return extract_entities(text)
        return {"pessoas": [], "empresas": [], "valores": [], "cpfs": [], "cnpjs": []}

    def status(self) -> dict:
        """Return router status and budget information."""
        return {
            "ollama_disponivel": self._ollama_available(),
            "model": DEFAULT_MODEL,
            "tokens_usados_mes": self.tokens_used_this_month(),
            "limite_mensal": MONTHLY_TOKEN_LIMIT,
            "orcamento_restante_pct": self.budget_remaining_pct(),
        }
