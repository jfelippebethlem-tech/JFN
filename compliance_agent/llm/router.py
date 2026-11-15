"""
LLM Router — routes tasks to the free remote LLM chain (free_llm) and tracks Claude API usage.

Tracks monthly token usage and budget. (O caminho de LLM local via Ollama saiu em 15/11/2026.)
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MONTHLY_TOKEN_LIMIT = int(os.environ.get("MONTHLY_TOKEN_LIMIT", "500000"))

BUDGET_FILE = Path("data/llm_budget.json")

class LLMRouter:
    """
    Routes LLM tasks to the free remote LLM chain and tracks Claude API budget.

    Budget tracking is persisted to data/llm_budget.json indexed by month (YYYY-MM).
    """

    def __init__(self):
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
            except Exception as exc:
                logger.warning("budget de tokens ilegível em %s (recomeça zerado — contagem do mês se perde): %s", BUDGET_FILE, exc)
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
        except Exception as exc:
            logger.warning("falha ao gravar budget de tokens em %s (uso do mês não persiste): %s", BUDGET_FILE, exc)

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

    # ── Public task methods ───────────────────────────────────────────────────
    # NB: classify()/summarize() abaixo (via LLM grátis) são as versões VÁLIDAS — havia
    # definições duplicadas Ollama-first acima que o Python descartava silenciosamente
    # (F811); removidas para o leitor não corrigir a errada. Comportamento idêntico.

    def extract_entities(self, text: str) -> dict:
        """
        Extract named entities from text.

        Via free LLM chain (free_llm.extrair_entidades_texto); empty dict if it fails.
        """
        from compliance_agent.llm.free_llm import extrair_entidades_texto
        return extrair_entidades_texto(text)

    def status(self) -> dict:
        """Return router status and budget information."""
        from compliance_agent.llm.free_llm import status_provedores
        return {
            "tokens_usados_mes": self.tokens_used_this_month(),
            "limite_mensal": MONTHLY_TOKEN_LIMIT,
            "orcamento_restante_pct": self.budget_remaining_pct(),
            "provedores_gratuitos": status_provedores(),
        }

    def classify(self, text: str, categories: list[str]) -> str:
        """Classify via free LLM first, fallback to first category."""
        from compliance_agent.llm.free_llm import best_free_chat
        prompt = (
            f"Classifique em UMA categoria: {' | '.join(categories)}\n"
            "Responda APENAS o nome da categoria.\n\n"
            f"Texto: {text[:400]}"
        )
        try:
            r = best_free_chat(prompt, fallback=categories[0]).strip().lower()
            for cat in categories:
                if cat.lower() in r:
                    return cat
        except Exception as exc:
            logger.debug("classificação via free LLM falhou (usando categoria padrão %s): %s", categories[0], exc)
        return categories[0]

    def summarize(self, text: str, max_words: int = 100) -> str:
        """Summarize via free LLM, fallback to truncation."""
        from compliance_agent.llm.free_llm import best_free_chat
        try:
            return best_free_chat(
                f"Resuma em até {max_words} palavras em português:\n\n{text[:1500]}",
                fallback=text[:300] + "...",
            )
        except Exception:
            return text[:300] + "..."
