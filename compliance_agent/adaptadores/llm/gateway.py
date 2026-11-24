# -*- coding: utf-8 -*-
"""gateway — a porta ÚNICA de chamada a LLM do JFN (plano mestre v2 §6 "Gateway LLM", O6.1 partes a e b).

O QUE FAZ HOJE (24/11/2026). `chamar()` NÃO tem backend próprio: DELEGA ao caminho que já existe e já funciona —
`llm/free_llm.best_free_chat` (camada 1), `llm/claude_motor.pensar(backend="cli")` (camada 2, assinatura) e
`llm/claude_api.pensar_api` (camada 3, API paga) — sem mudar o que eles fazem. O que o gateway ACRESCENTA:

  (a) TRACE por chamada em `data/llm_trace.db` (a mesma tabela `llm_trace` do `free_llm._trace`, ampliada por
      migração idempotente; linhas do gateway têm `origem='gateway'`): tarefa, prompt_version, input_hash,
      output_hash, modelo, provedor, camada, classe_dado, tokens in/out/cache, custo_usd, latência (`ms`), retry,
      motivo_escalonamento, release_ia. NUNCA o texto: só hashes SHA-256 e tamanhos em caracteres — prompt com CPF
      não entra no banco;
  (b) ROTEAMENTO pela política `config/llm_politica.yaml` (camadas 0..3 por tarefa, provedores permitidos por
      classe de dado, recusa explícita), TETO MENSAL da API paga (US$ 100, corte a 85%: entre 85% e 100% só tarefa
      `critica`; acima, nada pago) e CIRCUIT BREAKER por provedor (N falhas na janela ⇒ aberto por T).

O QUE REAPROVEITA (não duplica): o orçamento DIÁRIO da assinatura (`llm/orcamento`), o ritmo semanal
(`llm/ritmo_assinatura`), a contingência e o kill-switch valem DENTRO de `claude_motor.pensar` — o gateway só lê
`claude_motor.motivo_desligado()` para não gastar uma tentativa à toa e gravar o motivo. O livro-caixa da API
(`claude_api._reservar`: teto total, baldes, pausa) continua valendo dentro de `pensar_api`; o teto mensal daqui é
uma trava A MAIS (a mais apertada ganha). A estimativa conservadora de tokens é a do próprio `claude_api`.

O QUE AINDA NÃO FAZ (partes c e d do O6.1): cache composto com prefixo fixo e schema estrito + validação pós-parse
(documento existe, sha confere, página ≤ total, trecho é substring). Também não MASCARA CPF/conta antes do envio
(§3.11) — hoje a classe `pessoal`/`restrito` é recusada em todo provedor enquanto não houver ✅ do dono.

CONTRATO. Sucesso ⇒ `Resposta`. Recusa de política/classe/orçamento ⇒ exceção tipada (`TarefaDeterministica`,
`ClasseDadoRecusada`, `OrcamentoEsgotado`), nunca silêncio. Todas as camadas falharam ⇒ `SemProvedor` com os
motivos. Nenhum chamador foi migrado ainda (estrangulamento posterior).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from compliance_agent.llm import arquivo_estado as arq

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[3]
CLASSES = ("publico", "interno", "pessoal", "restrito", "segredo")
_RESERVA_VALIDADE_S = 3600     # reserva de processo que morreu no meio expira (não trava o mês para sempre)


# ── erros (todos explícitos) ─────────────────────────────────────────────────────────────────────────
class GatewayErro(RuntimeError):
    """Base: o gateway recusou ou não conseguiu responder. A mensagem diz por quê (nunca ecoa o prompt)."""


class TarefaDeterministica(GatewayErro):
    """A política marca a tarefa como camada 0: ela não chama LLM."""


class ClasseDadoRecusada(GatewayErro):
    """Nenhum provedor da tarefa pode receber esta classe de dado (ou a classe é inválida)."""


class OrcamentoEsgotado(GatewayErro):
    """Só havia caminho pago e o teto mensal (ou o corte de 85%) barrou."""


class SemProvedor(GatewayErro):
    """Todas as camadas permitidas falharam ou foram puladas; `motivos` lista cada uma."""

    def __init__(self, msg: str, motivos: list[str]):
        super().__init__(msg)
        self.motivos = motivos


# ── tipos ────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Retorno:
    """O que um backend devolve ao gateway. Campo desconhecido = None (nunca 0 inventado)."""
    texto: str
    modelo: str | None = None
    dados: object = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cache_lido: int | None = None
    tokens_cache_escrito: int | None = None
    usd_backend: float | None = None       # custo que o próprio backend calculou (livro-caixa do claude_api)
    lote: bool = False
    memo: bool = False                     # resposta da memória do backend: nenhuma chamada feita


@dataclass
class Resposta:
    texto: str
    dados: object
    tarefa: str
    provedor: str
    camada: int
    modelo: str | None
    custo_usd: float | None
    tokens_in: int | None
    tokens_out: int | None
    tokens_cache: int | None
    latencia_ms: int
    retry: int
    motivo_escalonamento: str | None
    release_ia: str
    input_hash: str
    output_hash: str
    trace_id: str
    extras: dict = field(default_factory=dict)


Backend = Callable[..., "Retorno | None"]


# ── configuração (lida a cada chamada: mudou o YAML, vale na próxima) ────────────────────────────────
def _caminho_politica() -> Path:
    return Path(os.environ.get("JFN_LLM_POLITICA") or (_REPO / "config" / "llm_politica.yaml"))


def _caminho_precos() -> Path:
    return Path(os.environ.get("JFN_LLM_PRECOS") or (_REPO / "config" / "llm_precos.yaml"))


def _yaml(p: Path) -> dict:
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(d, dict):
        raise GatewayErro(f"{p.name}: conteúdo não é um mapa")
    return d


def politica() -> dict:
    return _yaml(_caminho_politica())


def precos() -> dict:
    return _yaml(_caminho_precos())


def politica_da_tarefa(tarefa: str, pol: dict | None = None) -> dict:
    pol = pol or politica()
    t = (pol.get("tarefas") or {}).get(tarefa) or pol.get("padrao") or {"camadas": [1], "critica": False}
    return {"camadas": [int(c) for c in t.get("camadas") or []], "critica": bool(t.get("critica"))}


# ── preço ────────────────────────────────────────────────────────────────────────────────────────────
def _linha_preco(modelo: str | None, tokens_prompt: int, tab: dict) -> dict | None:
    if not modelo:
        return None
    m = (tab.get("modelos") or {}).get(str(modelo).split("@")[0])
    if not m:
        return None
    if m.get("longo") and tokens_prompt > int(m.get("longo_acima_de_tokens") or 10**12):
        return m["longo"]
    return m


def custo_usd(modelo: str | None, tokens_in: int | None, tokens_out: int | None, cache_lido: int | None = 0,
              cache_escrito: int | None = 0, *, lote: bool = False, tab: dict | None = None) -> float | None:
    """US$ de uma resposta pela tabela oficial. Modelo sem preço, ou contagem de entrada/saída desconhecida ⇒ None."""
    if tokens_in is None or tokens_out is None:
        return None
    tab = tab if tab is not None else precos()
    lido, escrito = int(cache_lido or 0), int(cache_escrito or 0)
    p = _linha_preco(modelo, tokens_in + lido + escrito, tab)
    if p is None:
        return None
    try:
        usd = (tokens_in * p["entrada"] + tokens_out * p["saida"] + lido * p["cache_leitura"]
               + escrito * p["cache_escrita_5m"]) / 1e6
    except (KeyError, TypeError):
        return None
    return round(usd * (float(tab.get("desconto_lote", 0.5)) if lote else 1.0), 8)


def estimar_usd(modelo: str | None, tokens_entrada: int, max_tokens: int, tab: dict | None = None) -> float | None:
    """Pior caso ANTES da chamada: entrada inteira como escrita de cache (5 min) + saída no `max_tokens` inteiro."""
    tab = tab if tab is not None else precos()
    p = _linha_preco(modelo, tokens_entrada, tab)
    if p is None:
        return None
    try:
        return round((tokens_entrada * p["cache_escrita_5m"] + max_tokens * p["saida"]) / 1e6, 8)
    except (KeyError, TypeError):
        return None


# ── trace ────────────────────────────────────────────────────────────────────────────────────────────
_COLUNAS = (("modelo", "TEXT"), ("tokens_in", "INT"), ("tokens_out", "INT"), ("usd", "REAL"), ("tarefa", "TEXT"),
            ("chars_in", "INT"), ("chars_out", "INT"),
            # O6.1 (a) — colunas do gateway (as de cima são do free_llm._trace; repetidas para base nova)
            ("origem", "TEXT"), ("trace_id", "TEXT"), ("prompt_version", "TEXT"), ("input_hash", "TEXT"),
            ("output_hash", "TEXT"), ("camada", "INT"), ("classe_dado", "TEXT"), ("tokens_cache", "INT"),
            ("tokens_cache_escrito", "INT"), ("custo_usd", "REAL"), ("custo_fonte", "TEXT"), ("pago", "INT"),
            ("retry", "INT"), ("motivo_escalonamento", "TEXT"), ("release_ia", "TEXT"))


def _trace_db() -> Path:
    return Path(os.environ.get("JFN_LLM_TRACE_DB") or (_REPO / "data" / "llm_trace.db"))


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(_trace_db(), timeout=5)
    migrar(con)
    return con


def migrar(con: sqlite3.Connection) -> None:
    """Migração IDEMPOTENTE: cria a tabela se faltar e acrescenta só as colunas ausentes (nenhuma linha se perde)."""
    con.execute("CREATE TABLE IF NOT EXISTS llm_trace("
                "ts TEXT DEFAULT (datetime('now')), provedor TEXT, ok INT, ms INT, erro TEXT)")
    tem = {r[1] for r in con.execute("PRAGMA table_info(llm_trace)")}
    for c, t in _COLUNAS:
        if c not in tem:
            con.execute(f"ALTER TABLE llm_trace ADD COLUMN {c} {t}")
    con.execute("CREATE INDEX IF NOT EXISTS ix_llm_trace_origem_ts ON llm_trace(origem, ts)")
    con.commit()


def _gravar(linha: dict) -> None:
    """Uma linha por tentativa. Falha de disco não derruba a chamada (só avisa)."""
    try:
        con = _conectar()
        try:
            cols = list(linha)
            con.execute(f"INSERT INTO llm_trace({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                        [linha[c] for c in cols])
            con.commit()
        finally:
            con.close()
    except (sqlite3.Error, OSError) as e:
        logger.warning("gateway: trace não gravado (%s)", type(e).__name__)


def _sha(obj) -> str:
    bruto = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


# ── orçamento mensal da API paga ─────────────────────────────────────────────────────────────────────
def _mes() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def gasto_mes_usd(mes: str | None = None) -> float:
    """Soma de custo_usd das chamadas PAGAS do gateway no mês (UTC). Custo desconhecido não entra como 0: a
    chamada paga sem custo estimável é recusada antes (ver `_reservar`)."""
    mes = mes or _mes()
    try:
        con = _conectar()
        try:
            r = con.execute("SELECT COALESCE(SUM(custo_usd), 0) FROM llm_trace WHERE origem='gateway' AND pago=1 "
                            "AND strftime('%Y-%m', ts)=?", (mes,)).fetchone()
        finally:
            con.close()
        return float(r[0] or 0.0)
    except sqlite3.Error as e:
        # sem leitura do gasto não há como provar que cabe: quem chama trata como teto atingido
        raise OrcamentoEsgotado(f"gasto do mês ilegível ({type(e).__name__}) — sem prova de que cabe, nada pago")


def _arq_reservas() -> Path:
    return arq.dados() / "llm_gateway_reservas.json"


def _vivas(d: dict, agora: float, mes: str) -> dict:
    return {k: v for k, v in (d.get("reservas") or {}).items()
            if v.get("mes") == mes and agora - float(v.get("em", 0)) < _RESERVA_VALIDADE_S}


def estado_orcamento(pol: dict | None = None) -> dict:
    pol = pol or politica()
    o = pol.get("orcamento_mensal") or {}
    teto, corte = float(o.get("teto_usd", 100.0)), float(o.get("corte_fracao", 0.85))
    mes = _mes()
    reservado = sum(float(v["usd"]) for v in _vivas(arq.ler_json(_arq_reservas()), time.time(), mes).values())
    gasto = gasto_mes_usd(mes)
    return {"mes": mes, "teto_usd": teto, "corte_usd": round(teto * corte, 6), "gasto_usd": round(gasto, 6),
            "reservado_usd": round(reservado, 6), "fracao": round((gasto + reservado) / teto, 6) if teto else None}


def motivo_orcamento(gasto_mais_reservado: float, est: float, teto: float, corte: float, critica: bool) -> str | None:
    """None = cabe. Abaixo do corte passa; entre corte e teto só a crítica; acima do teto nada."""
    total = gasto_mais_reservado + est
    if total > teto:
        return f"teto mensal da API paga: US$ {gasto_mais_reservado:.2f} + US$ {est:.4f} passam de US$ {teto:.2f}"
    if total > teto * corte and not critica:
        return (f"corte de {corte:.0%} do teto mensal (US$ {teto * corte:.2f}): US$ {gasto_mais_reservado:.2f} + "
                f"US$ {est:.4f} — só tarefa crítica passa")
    return None


def _reservar(est: float | None, critica: bool, pol: dict) -> tuple[str | None, str | None]:
    """(id_da_reserva, motivo_da_recusa). Sob trava de arquivo: paralelismo não fura o teto."""
    if est is None:
        return None, "custo da chamada paga não estimável (modelo sem preço em config/llm_precos.yaml)"
    o = pol.get("orcamento_mensal") or {}
    teto, corte = float(o.get("teto_usd", 100.0)), float(o.get("corte_fracao", 0.85))
    rid = uuid.uuid4().hex[:12]

    def f(d):
        agora, mes = time.time(), _mes()
        vivas = _vivas(d, agora, mes)
        d["reservas"] = vivas
        try:
            gasto = gasto_mes_usd(mes)
        except OrcamentoEsgotado as e:
            return str(e)
        m = motivo_orcamento(gasto + sum(float(v["usd"]) for v in vivas.values()), est, teto, corte, critica)
        if m:
            return m
        vivas[rid] = {"usd": est, "em": agora, "mes": mes}
        return None
    motivo = arq.mutar_json(_arq_reservas(), f, espera=None)
    return (None, motivo) if motivo else (rid, None)


def _liberar(rid: str | None) -> None:
    if rid:
        arq.mutar_json(_arq_reservas(), lambda d: (d.get("reservas") or {}).pop(rid, None), espera=None)


# ── circuit breaker por provedor ─────────────────────────────────────────────────────────────────────
def _arq_circuito() -> Path:
    return arq.dados() / "llm_gateway_circuito.json"


def circuito_aberto(provedor: str, pol: dict, agora: float | None = None) -> str | None:
    agora = time.time() if agora is None else agora
    c = (arq.ler_json(_arq_circuito()).get(provedor) or {})
    ate = float(c.get("aberto_ate") or 0)
    return f"circuito aberto até {datetime.fromtimestamp(ate).isoformat(timespec='seconds')}" if ate > agora else None


def registrar_falha(provedor: str, pol: dict, agora: float | None = None) -> None:
    agora = time.time() if agora is None else agora
    cfg = pol.get("circuito") or {}
    n, janela, aberto = int(cfg.get("falhas", 5)), float(cfg.get("janela_s", 300)), float(cfg.get("aberto_s", 600))

    def f(d):
        c = d.setdefault(provedor, {"falhas": [], "aberto_ate": 0})
        c["falhas"] = [t for t in c.get("falhas", []) if agora - float(t) < janela] + [agora]
        if len(c["falhas"]) >= n:
            c["aberto_ate"] = agora + aberto
            c["falhas"] = []
    arq.mutar_json(_arq_circuito(), f, espera=10.0)


def registrar_sucesso(provedor: str) -> None:
    def f(d):
        if provedor in d:
            d[provedor] = {"falhas": [], "aberto_ate": 0}
    arq.mutar_json(_arq_circuito(), f, espera=10.0)


# ── classe de dado ───────────────────────────────────────────────────────────────────────────────────
def motivo_classe(classe_dado: str, provedor: str, pol: dict) -> str | None:
    """None = o provedor pode receber esta classe. Regras em `classes_dado` da política."""
    exige = ((pol.get("classes_dado") or {}).get(classe_dado) or {}).get("exige")
    p = (pol.get("provedores") or {}).get(provedor)
    if p is None:
        return f"provedor {provedor} fora da política"
    if exige in (None, "nunca"):
        return f"classe '{classe_dado}' nunca vai a provedor de LLM"
    if exige == "nada":
        return None
    if exige == "data_policy_conhecida":
        return None if p.get("data_policy") == "conhecida" else \
            f"{provedor}: data_policy '{p.get('data_policy')}' — classe '{classe_dado}' exige política de dados conhecida"
    if exige == "aprovada_dono":
        return None if (p.get("data_policy") == "conhecida" and p.get("aprovada_dono") is True) else \
            f"{provedor}: sem ✅ do dono para classe '{classe_dado}' (§3.11)"
    return f"exigência desconhecida '{exige}' para classe '{classe_dado}'"


# ── mensagens ────────────────────────────────────────────────────────────────────────────────────────
def _achatar(mensagens: list[dict]) -> tuple[str, str]:
    """(sistema, prompt) no formato que os backends de hoje aceitam (um prompt só). `system` vira o sistema; uma
    única mensagem `user` passa intacta; conversa com mais turnos é rotulada por papel."""
    if not isinstance(mensagens, list) or not mensagens:
        raise GatewayErro("mensagens vazias")
    sist = [str(m.get("content") or "") for m in mensagens if m.get("role") == "system"]
    resto = [m for m in mensagens if m.get("role") != "system"]
    if not resto or resto[-1].get("role") != "user":
        raise GatewayErro("a última mensagem precisa ser do papel 'user'")
    if len(resto) == 1:
        prompt = str(resto[0].get("content") or "")
    else:
        prompt = "\n\n".join(f"[{m.get('role')}]\n{m.get('content') or ''}" for m in resto)
    return "\n\n".join(s for s in sist if s), prompt


# ── backends (delegam ao caminho existente; sem mudar comportamento) ─────────────────────────────────
def _com_schema(prompt: str, schema) -> str:
    from compliance_agent.llm.json_resposta import instrucao_schema
    return prompt + (instrucao_schema(schema) if schema is not None else "")


def _parse(texto: str, schema):
    """(dados, motivo). Sem schema ⇒ (None, None)."""
    if schema is None:
        return None, None
    from compliance_agent.llm.json_resposta import chaves_faltando, parse_json_llm
    dados = parse_json_llm(texto)
    falta = chaves_faltando(dados, schema)
    if falta != []:
        return None, "resposta sem o JSON pedido" + (f" (faltam {', '.join(falta[:5])})" if falta else "")
    return dados, None


def _backend_free(*, tarefa, sistema, prompt, schema, modelo_pref, max_tokens, timeout) -> Retorno | None:
    from compliance_agent.llm import free_llm
    texto = free_llm.best_free_chat(_com_schema(prompt, schema), system=sistema, smart=True, fallback="")
    return Retorno(texto=texto, modelo=None) if texto and str(texto).strip() else None


def _backend_assinatura(*, tarefa, sistema, prompt, schema, modelo_pref, max_tokens, timeout) -> Retorno | None:
    from compliance_agent.llm import claude_motor
    p = claude_motor.pensar(tarefa, prompt, schema=schema, modelo=modelo_pref or claude_motor.MODELO_VOLUME,
                            sistema=sistema, timeout=timeout, backend="cli")
    if p is None:
        raise RuntimeError(claude_motor.ultimo_motivo or "assinatura sem resposta")
    return Retorno(texto=p.texto, modelo=p.modelo, dados=p.dados)


class _Captura:
    """Cliente Anthropic que só OBSERVA: repassa tudo ao cliente real e guarda as respostas de `create`, para o
    gateway ler o `usage` (tokens in/out/cache) sem mudar uma linha de `claude_api`."""

    class _Mensagens:
        def __init__(self, real, dono):
            self._real, self._dono = real, dono

        def create(self, **kw):
            r = self._real.create(**kw)
            self._dono.respostas.append(r)
            return r

        def __getattr__(self, nome):
            return getattr(self._real, nome)

    class _Beta:
        def __init__(self, real, dono):
            self._real = real
            self.messages = _Captura._Mensagens(real.messages, dono)

        def __getattr__(self, nome):
            return getattr(self._real, nome)

    def __init__(self, real):
        self.respostas: list = []
        self.messages = _Captura._Mensagens(real.messages, self)
        self.beta = _Captura._Beta(real.beta, self)


def _uso(usage, k: str) -> int | None:
    v = usage.get(k) if isinstance(usage, dict) else getattr(usage, k, None)
    return None if v is None else int(v)


def _backend_api(*, tarefa, sistema, prompt, schema, modelo_pref, max_tokens, timeout, cliente=None) -> Retorno | None:
    from compliance_agent.llm import claude_api, claude_motor
    barrado = claude_motor._motivo_kill_switch()
    if barrado:
        raise RuntimeError(barrado)
    if cliente is None:
        if arq.sob_pytest():
            raise RuntimeError("API: sob pytest sem cliente dublê")
        if not claude_api.disponivel():
            raise RuntimeError("API: sem chave (ou JFN_CLAUDE_API=0)")
        cliente = claude_api._cliente(timeout)
    cap = _Captura(cliente)
    res = claude_api.pensar_api(tarefa, _com_schema(prompt, schema), sistema=sistema or claude_motor.SISTEMA_PADRAO,
                                modelo=modelo_pref, max_tokens=max_tokens, timeout=timeout, cliente=cap)
    if res is None:
        raise RuntimeError(claude_api.ultimo_motivo or "API sem resposta")
    texto, quem, usd = res
    if not cap.respostas:      # memória do claude_api: nenhuma chamada, nada cobrado
        return Retorno(texto=texto, modelo=quem, tokens_in=0, tokens_out=0, tokens_cache_lido=0,
                       tokens_cache_escrito=0, usd_backend=0.0, memo=True)
    u = getattr(cap.respostas[-1], "usage", None)
    return Retorno(texto=texto, modelo=quem, tokens_in=_uso(u, "input_tokens"), tokens_out=_uso(u, "output_tokens"),
                   tokens_cache_lido=_uso(u, "cache_read_input_tokens"),
                   tokens_cache_escrito=_uso(u, "cache_creation_input_tokens"), usd_backend=usd)


BACKENDS: dict[str, Backend] = {
    "free_llm": _backend_free,
    "assinatura_claude": _backend_assinatura,
    "api_anthropic": _backend_api,
}


def _pre_assinatura(tarefa: str) -> str | None:
    """Motivo para nem tentar a assinatura (kill-switch, contingência/ritmo, canário) — lido do motor, não refeito."""
    try:
        from compliance_agent.llm import claude_motor
        return claude_motor.motivo_desligado(tarefa=tarefa)
    except (ImportError, OSError) as e:
        return f"motor indisponível ({type(e).__name__})"


def _estimativa_api(tarefa: str, modelo_pref: str | None, sistema: str, prompt: str, max_tokens: int | None,
                    tab: dict) -> tuple[str, int, float | None]:
    """(modelo que o claude_api vai usar, max_tokens, US$ do pior caso). Mesmas regras do claude_api."""
    from compliance_agent.llm import claude_api
    modelo = claude_api._sem_opus(modelo_pref or claude_api.modelo_para(tarefa))
    mt = max_tokens or claude_api.MAX_TOKENS_TAREFA.get(tarefa, 4000)
    ent = claude_api._tokens_aprox(sistema) + claude_api._tokens_aprox(prompt)
    return modelo, mt, estimar_usd(modelo, ent, mt, tab)


# ── a porta ──────────────────────────────────────────────────────────────────────────────────────────
def chamar(tarefa: str, mensagens: list[dict], *, prompt_version: str, modelo_pref: str | None = None,
           schema=None, classe_dado: str, max_tokens: int | None = None, timeout: float = 180.0,
           backends: dict[str, Backend] | None = None) -> Resposta:
    """Uma chamada de LLM pela política. Ver o docstring do módulo para o contrato."""
    if not tarefa or not isinstance(tarefa, str):
        raise GatewayErro("tarefa obrigatória")
    if not prompt_version:
        raise GatewayErro("prompt_version obrigatório (rastreabilidade: nucleo/prompt_versao)")
    if classe_dado not in CLASSES:
        raise ClasseDadoRecusada(f"classe_dado '{classe_dado}' inválida; use uma de {', '.join(CLASSES)}")
    pol, tab = politica(), precos()
    pt = politica_da_tarefa(tarefa, pol)
    camadas = pt["camadas"]
    if not camadas or camadas == [0] or 0 in camadas:
        raise TarefaDeterministica(f"tarefa '{tarefa}' é camada 0 (determinística) na política — não chama LLM")
    sistema, prompt = _achatar(mensagens)
    backends = {**BACKENDS, **(backends or {})}
    input_hash = _sha([sistema, prompt, schema, modelo_pref])
    chars_in = len(sistema) + len(prompt)
    tid = uuid.uuid4().hex[:16]

    candidatos, recusas_classe = [], []
    for c in camadas:
        prov = ((pol.get("camadas") or {}).get(c) or {}).get("provedor")
        if not prov:
            raise GatewayErro(f"camada {c} sem provedor na política")
        m = motivo_classe(classe_dado, prov, pol)
        (recusas_classe.append(f"camada {c}: {m}") if m else candidatos.append((c, prov)))
    if not candidatos:
        _gravar({"origem": "gateway", "trace_id": tid, "tarefa": tarefa[:60], "ok": 0, "ms": 0,
                 "erro": "recusado: classe de dado", "prompt_version": prompt_version, "input_hash": input_hash,
                 "classe_dado": classe_dado, "chars_in": chars_in, "motivo_escalonamento": " | ".join(recusas_classe)})
        raise ClasseDadoRecusada(f"tarefa '{tarefa}', classe '{classe_dado}': " + " | ".join(recusas_classe))

    motivos: list[str] = list(recusas_classe)
    so_orcamento = True       # todas as camadas viáveis caíram por orçamento? (para o tipo da exceção)
    tentativa = 0
    for camada, prov in candidatos:
        pago = bool(((pol.get("provedores") or {}).get(prov) or {}).get("pago"))
        aberto = circuito_aberto(prov, pol)
        if aberto:
            motivos.append(f"{prov}: {aberto}")
            so_orcamento = False
            continue
        if prov == "assinatura_claude" and backends.get(prov) is BACKENDS[prov]:
            pre = _pre_assinatura(tarefa)
            if pre:
                motivos.append(f"{prov}: {pre}")
                so_orcamento = False
                continue
        rid, mt, modelo_est, est = None, max_tokens, None, None
        if pago:
            modelo_est, mt, est = _estimativa_api(tarefa, modelo_pref, sistema, prompt, max_tokens, tab)
            rid, recusa = _reservar(est, pt["critica"], pol)
            if recusa:
                motivos.append(f"{prov}: {recusa}")
                _gravar({"origem": "gateway", "trace_id": tid, "tarefa": tarefa[:60], "provedor": prov,
                         "camada": camada, "ok": 0, "ms": 0, "erro": "recusado: orçamento", "pago": 1,
                         "prompt_version": prompt_version, "input_hash": input_hash, "classe_dado": classe_dado,
                         "chars_in": chars_in, "modelo": modelo_est, "motivo_escalonamento": recusa[:300]})
                continue
        so_orcamento = False
        ini = time.monotonic()
        ret, erro = None, ""
        try:
            ret = backends[prov](tarefa=tarefa, sistema=sistema, prompt=prompt, schema=schema,
                                 modelo_pref=modelo_pref, max_tokens=mt, timeout=timeout)
            if ret is None:
                erro = "resposta vazia"
        except Exception as e:      # noqa: BLE001 — backend nunca derruba o gateway; o TIPO vai ao trace
            erro = f"{type(e).__name__}: {str(e)[:160]}"
        ms = int((time.monotonic() - ini) * 1000)
        dados = None
        if ret is not None and not erro:
            dados = ret.dados
            if schema is not None and dados is None:
                dados, m = _parse(ret.texto, schema)
                if m:
                    erro = m
        modelo = (ret.modelo if ret else None) or (modelo_est if pago else None)
        custo, fonte = None, None
        if ret is not None:
            custo = custo_usd(modelo, ret.tokens_in, ret.tokens_out, ret.tokens_cache_lido, ret.tokens_cache_escrito,
                              lote=ret.lote, tab=tab)
            fonte = "tabela" if custo is not None else None
            if custo is None and ret.usd_backend is not None:
                custo, fonte = round(float(ret.usd_backend), 8), "backend"
            if ret.memo:
                fonte = "memo"
        elif pago:
            # falhou sem resposta: o backend pode ter cobrado a entrada; o gasto real fica no livro-caixa do
            # claude_api. Aqui fica a ESTIMATIVA como custo — conservador (nunca subconta o teto mensal).
            custo, fonte = est, "estimativa_falha"
        release = f"{prompt_version}+{modelo or prov}"
        ok = ret is not None and not erro
        _gravar({"origem": "gateway", "trace_id": tid, "tarefa": tarefa[:60], "provedor": prov, "camada": camada,
                 "ok": int(ok), "ms": ms, "erro": erro[:200] or None, "modelo": modelo, "pago": int(pago),
                 "prompt_version": prompt_version, "input_hash": input_hash,
                 "output_hash": _sha(ret.texto) if ret is not None else None, "classe_dado": classe_dado,
                 "chars_in": chars_in, "chars_out": len(ret.texto) if ret is not None else None,
                 "tokens_in": ret.tokens_in if ret else None, "tokens_out": ret.tokens_out if ret else None,
                 "tokens_cache": ret.tokens_cache_lido if ret else None,
                 "tokens_cache_escrito": ret.tokens_cache_escrito if ret else None,
                 "custo_usd": custo, "custo_fonte": fonte, "retry": tentativa,
                 "motivo_escalonamento": (" | ".join(motivos))[:500] or None, "release_ia": release[:120]})
        _liberar(rid)
        if ok:
            registrar_sucesso(prov)
            return Resposta(texto=ret.texto, dados=dados, tarefa=tarefa, provedor=prov, camada=camada, modelo=modelo,
                            custo_usd=custo, tokens_in=ret.tokens_in, tokens_out=ret.tokens_out,
                            tokens_cache=ret.tokens_cache_lido, latencia_ms=ms, retry=tentativa,
                            motivo_escalonamento=" | ".join(motivos) or None, release_ia=release,
                            input_hash=input_hash, output_hash=_sha(ret.texto), trace_id=tid,
                            extras={"custo_fonte": fonte, "memo": ret.memo})
        registrar_falha(prov, pol)
        motivos.append(f"{prov}: {erro}")
        tentativa += 1

    if so_orcamento:
        raise OrcamentoEsgotado(f"tarefa '{tarefa}': " + " | ".join(motivos))
    raise SemProvedor(f"tarefa '{tarefa}': nenhuma camada respondeu — " + " | ".join(motivos), motivos)
