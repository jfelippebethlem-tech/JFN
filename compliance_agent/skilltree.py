# -*- coding: utf-8 -*-
"""Skilltree = registro vivo de capacidades (capabilities.yaml) — JFN 2.0, Onda 1.

Fonte única consumida pelo roteador do Yoda (tool-calling). Suporta reload a quente,
validacao fail-safe, diff e sync via git — SEM restart do servico.

Invariante: se o YAML novo for invalido, mantem o estado anterior (nunca quebra o
roteador). O Yoda so chama ids presentes aqui.

Reuso (fonte unica de verdade, sem duplicar logica):
  - validate()  -> delega a tools.validate_capabilities.validar()
  - tool_specs()-> delega a tools.gen_router_tools (mesmo formato function-calling)
  - reload()    -> apos trocar o estado, regenera os derivados (jfn_tools.json) p/ o
                   gateway pegar a versao nova a quente.

Origem do spec: docs/refs/JFN-SPEC-SKILLTREE-YODA.pdf (recebido via Telegram 2026-06-08).
Adaptado a arquitetura real do JFN (o wiring no gateway Hermes vivo e a ULTIMA onda).
"""
from __future__ import annotations

import hashlib
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent
CAP_PATH = _REPO / "capabilities.yaml"
SERVER = _REPO / "server.py"


@dataclass
class SkillTree:
    """Registro vivo das capacidades. Thread-safe; troca de estado e atomica sob lock."""

    path: Path = CAP_PATH
    capacidades: dict = field(default_factory=dict)  # id -> cap
    meta: dict = field(default_factory=dict)
    sha: str = ""
    carregado_em: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ---------- parsing / validacao ----------
    def _parse(self, raw: str) -> dict:
        """Parseia e valida a estrutura minima. Levanta ValueError se invalido."""
        doc = yaml.safe_load(raw)
        if not isinstance(doc, dict) or "capacidades" not in doc:
            raise ValueError("capabilities.yaml sem chave 'capacidades'")
        caps: dict = {}
        for c in doc["capacidades"]:
            if not isinstance(c, dict) or "id" not in c:
                raise ValueError(f"capacidade sem 'id': {c!r}")
            cid = c["id"]
            if cid in caps:
                raise ValueError(f"id duplicado: {cid}")
            caps[cid] = c
        return {"meta": doc.get("meta", {}), "capacidades": caps}

    # ---------- mutacoes (fail-safe) ----------
    def reload(self) -> dict:
        """Recarrega do disco. Valida ANTES de trocar; em erro, mantem o estado atual
        e propaga a excecao (o chamador reporta e a skilltree antiga segue valendo)."""
        raw = self.path.read_text(encoding="utf-8")
        novo = self._parse(raw)  # valida ANTES de trocar (fail-safe)
        sha = hashlib.sha256(raw.encode()).hexdigest()[:12]
        with self._lock:
            antes = set(self.capacidades)
            self.meta = novo["meta"]
            self.capacidades = novo["capacidades"]
            self.sha = sha
            self.carregado_em = time.time()
            depois = set(self.capacidades)
        # reload e PURO (so troca o estado em memoria) — fail-safe, sem efeito colateral
        # em disco. O hot-swap das tools no gateway e feito por quem chama, via
        # tool_specs() -> bot_data["yoda_tools"] (wiring no Yoda vivo = ultima onda).
        # A regeneracao dos derivados em disco (data/jfn_tools.json) e papel do
        # pre-commit / tools.gen_router_tools, nao do reload.
        return {
            "sha": sha,
            "total": len(depois),
            "add": sorted(depois - antes),
            "rm": sorted(antes - depois),
        }

    def sync(self) -> dict:
        """git pull --ff-only no projeto todo, depois reload."""
        pull = subprocess.run(
            ["git", "-C", str(_REPO), "pull", "--ff-only"],
            capture_output=True, text=True, timeout=60,
        )
        if pull.returncode != 0:
            raise RuntimeError(pull.stderr.strip() or "git pull falhou")
        commit = subprocess.run(
            ["git", "-C", str(_REPO), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        res = self.reload()
        res["commit"] = commit
        return res

    # ---------- validacao de contrato (reusa o validador unico) ----------
    def validate(self) -> list[str]:
        """Schema minimo + toda rota PRONTO existe no server.py.
        Delega ao validador unico (tools.validate_capabilities) p/ nao divergir."""
        try:
            from tools.validate_capabilities import validar

            return validar()
        except Exception as e:  # noqa: BLE001 — fallback local minimo se o import falhar
            problemas: list[str] = []
            server_src = SERVER.read_text(encoding="utf-8") if SERVER.exists() else ""
            for cid, c in self.capacidades.items():
                for campo in ("agente", "tipo", "status", "descricao"):
                    if campo not in c:
                        problemas.append(f"{cid}: falta '{campo}'")
                if c.get("status") == "PRONTO" and c.get("tipo") == "http":
                    base = (c.get("rota", "")).split("{")[0].rstrip("/")
                    if base and base not in server_src:
                        problemas.append(f"{cid}: rota {c.get('rota')} ausente no server.py")
            problemas.append(f"(validador unico indisponivel: {e})")
            return problemas

    # ---------- saidas ----------
    def tool_specs(self) -> list[dict]:
        """Tool-specs (function-calling) que o gateway do Yoda carrega p/ tool-calling.
        Reusa tools.gen_router_tools._tool_spec p/ manter o MESMO formato dos derivados.
        Ignora capacidades ainda nao implementadas (status ONDA N)."""
        try:
            from tools.gen_router_tools import _tool_spec

            return [
                _tool_spec(c)
                for c in self.capacidades.values()
                if not str(c.get("status", "")).startswith("ONDA")
            ]
        except Exception:  # noqa: BLE001 — formato minimo de fallback
            specs = []
            for cid, c in self.capacidades.items():
                if str(c.get("status", "")).startswith("ONDA"):
                    continue
                specs.append({
                    "name": cid,
                    "description": f"{c.get('descricao', '')}. Quando usar: {c.get('quando_usar', '')}",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            k: {"type": "string", "description": str(v)}
                            for k, v in (c.get("args") or {}).items()
                        },
                    },
                })
            return specs

    def render(self, filtro: str = "") -> str:
        """Markdown da skilltree, agrupada por dominio (para /skills e /lista)."""
        por_dom: dict[str, list] = {}
        for cid, c in sorted(self.capacidades.items()):
            blob = f"{cid} {c.get('descricao', '')} {c.get('dominio', '')}".lower()
            if filtro and filtro.lower() not in blob:
                continue
            por_dom.setdefault(c.get("dominio", "outros"), []).append((cid, c))
        if not por_dom:
            return f"Nenhuma skill casa com '{filtro}'."
        linhas = [
            f"🌳 *Skilltree* — v{self.meta.get('versao', '?')} · "
            f"`{self.sha}` · {len(self.capacidades)} skills"
        ]
        for dom in sorted(por_dom):
            linhas.append(f"\n*{dom.upper()}*")
            for cid, c in por_dom[dom]:
                st = c.get("status", "")
                tag = "✅" if st == "PRONTO" else f"🔸{st}"
                linhas.append(f"{tag} `{cid}` — {c.get('descricao', '')}")
        return "\n".join(linhas)

    _DOM_EMOJI = {"auditoria": "🏢", "inteligencia": "🔎", "juridico": "⚖️",
                  "mercado": "📈", "sistema": "⚙️", "outros": "▪️"}
    _DOM_TITULO = {"auditoria": "AUDITORIA & RELATÓRIOS", "inteligencia": "INTELIGÊNCIA / OSINT",
                   "juridico": "JURÍDICO (Lex) / SEI", "mercado": "MERCADO (Massare)", "sistema": "SISTEMA"}

    def render_menu(self, so_prontas: bool = True) -> str:
        """Menu COMPLETO p/ o /lista — gerado do capabilities.yaml (fonte única), agrupado por domínio,
        com descrição + quando usar. Substitui o texto fixo: /lista passa a refletir TODAS as capacidades."""
        por_dom: dict[str, list] = {}
        for cid, c in sorted(self.capacidades.items(), key=lambda kv: kv[0]):
            if so_prontas and c.get("status") != "PRONTO":
                continue
            por_dom.setdefault(c.get("dominio", "outros"), []).append((cid, c))
        linhas = [
            "🧭 *ECOSSISTEMA JFN* — eu, o *Yoda*, sou o maestro e aciono os agentes (JFN · Lex · Massare).",
            "Peça em linguagem natural ou pelo comando. Detalhe de uma função: `/skill <id>`.",
            f"_v{self.meta.get('versao', '?')} · {sum(len(v) for v in por_dom.values())} capacidades ativas_",
        ]
        ordem = ["auditoria", "inteligencia", "juridico", "mercado", "sistema"]
        for dom in ordem + [d for d in sorted(por_dom) if d not in ordem]:
            caps = por_dom.get(dom)
            if not caps:
                continue
            linhas.append("━━━━━━━━━━━━━━━━━━━━")
            linhas.append(f"{self._DOM_EMOJI.get(dom, '▪️')} *{self._DOM_TITULO.get(dom, dom.upper())}*")
            for cid, c in caps:
                alvo = c.get("rota") or c.get("comando") or ""
                qu = c.get("quando_usar", "")
                qu = f" — _{qu}_" if qu else ""
                linhas.append(f"▪️ *{cid}* (`{alvo}`): {c.get('descricao', '')}{qu}")
        return "\n".join(linhas)

    def detalhe(self, cid: str) -> str:
        """Markdown de uma capacidade (para /skill <id>)."""
        c = self.capacidades.get(cid)
        if not c:
            return f"Skill `{cid}` nao existe. Use /skills para listar."
        args = c.get("args") or {}
        args_txt = "\n".join(f" • `{k}`: {v}" for k, v in args.items()) or " (nenhum)"
        alvo = c.get("rota") or c.get("comando") or "?"
        return (
            f"🌳 *{cid}* ({c.get('status', '')})\n"
            f"dominio: {c.get('dominio', '?')} · agente: {c.get('agente', '?')}\n"
            f"{c.get('descricao', '')}\n\n"
            f"*Quando usar:* {c.get('quando_usar', '—')}\n"
            f"*Acesso:* `{c.get('tipo', '?')} {alvo}`\n"
            f"*Args:*\n{args_txt}\n"
            f"*Retorno:* {c.get('retorno', '—')}"
        )


# singleton vivo do processo (carrega na importacao; fail-safe se o YAML sumir)
SKILLTREE = SkillTree()
try:
    SKILLTREE.reload()
except Exception:  # noqa: BLE001 — import nunca quebra; estado vazio ate o 1o reload OK
    pass
