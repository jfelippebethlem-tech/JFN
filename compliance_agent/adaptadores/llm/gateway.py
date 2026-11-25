# -*- coding: utf-8 -*-
"""gateway — a porta ÚNICA de chamada a LLM do JFN (plano mestre v2 §6 "Gateway LLM", O6.1 a–d, O6.2).

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

  (c) CACHE COMPOSTO opcional (`cache=True`; `adaptadores/llm/cache.py`): chave = sha256 de documentos (id, versão
      sha256, sha do texto, versão da extração), mensagens, prompt_version, modelo, regra, schema, contexto, classe e
      camadas candidatas; hit/miss na coluna `cache` do trace. PREFIXO FIXO: o sistema só leva texto estável (o
      marcador aleatório nunca entra nele) e as instruções do chamador vêm antes do bloco de dados;
  (d) SCHEMA ESTRITO (Pydantic `model_validate_json(strict=True)`, ou o dict/str antigo) e validação pós-parse
      das citações por verificador injetável (`adaptadores/llm/saida.py`): citação que não confere é descartada;
      nenhuma sobrou ⇒ `estado=INDETERMINADO_FALHA_CITACAO` (sem escalar para camada mais cara). `ABSTEVE(motivo)`
      é resposta válida (`estado=ABSTEVE`, `saida=Saida(ABSTEVE, motivo)`);
  MÁSCARA (§3.11): todo texto que sai (mensagens, documentos, metadados) passa por `dominio/mascara.mascarar(...,
      estrito=True)` com UM mapa local por chamada; sobrou CPF com DV válido ⇒ `MascaraFalhou` (nada sai). A resposta
      volta desmascarada. A classe `pessoal`/`restrito` continua recusada em todo provedor sem ✅ do dono;
  O6.2 PROMPT INJECTION (`adaptadores/llm/prompt_seguro.py`): `documentos` entram por datamarking (linha a linha
      com token aleatório da chamada) + regra de sistema "conteúdo marcado é dado"; `ferramentas` é recusado
      (dual-LLM); resposta que obedece instrução embutida é DESCARTADA (a camada conta como falha, motivo no trace).

  CAMADA 4 (24/11/2026, migração do co-motor — ordem 3 do mapa): `cascata_dc` = a cascata grátis da casa
      (`llm/contingencia.gerar_cascata` → `direcionamento_cerebro.gerar_sync`), com `data_policy: desconhecida` na
      política ⇒ só recebe classe `publico`. `so_camadas` restringe a chamada a um subconjunto das camadas da tarefa
      (o co-motor roda o lado Claude [2, 3] e o lado cascata [4] em paralelo); `modelo_por_camada` dá o modelo de cada
      camada (o Opus da assinatura não vira o modelo da API: lá vale `claude_api.modelo_para`); `espera` vai à trava
      do `claude` da VM. Backend que NÃO TENTOU (trava ocupada, teto diário, sem chave, sob pytest sem dublê) levanta
      `CamadaPulada`: o motivo vai ao trace e a camada é pulada SEM contar falha no circuit breaker.

  ASSINATURA PRIMEIRO E PAGA SÓ COM AUTORIZAÇÃO (24/11/2026 — dono: "priorizando SEMPRE usar a assinatura em tudo";
      "créditos de API só quando eu autorizar"; decisões em ~/vault/refatoracao/decisoes-delegadas-ia-20261124.md):
      (1) a ordem de tentativa é REFEITA no código, qualquer que seja a do YAML: a camada da assinatura primeiro, depois
      as grátis, e as PAGAS por último (`ordem_assinatura_primeiro`); provedor sem `pago: false` explícito na política
      conta como PAGO (falha fechada). (2) Camada paga só é tentada com autorização VÁLIDA do dono para aquela tarefa
      e aquele provedor (`autorizacao_paga=<id>` ou `JFN_LLM_AUTORIZACAO_PAGA`, conferida no livro
      `config/llm_autorizacoes_pagas.yaml` por `llm/autorizacao_paga`); o teto da autorização soma o gasto do trace
      daquele id (coluna `autorizacao`, com `autorizacao_quem`/`autorizacao_quando`). Sem ela: recusa "API paga não
      autorizada pelo dono", gravada no trace, e — se nada mais respondeu — `PagaNaoAutorizada` (um `SemProvedor`): o
      item fica NÃO JULGADO, pendente para a assinatura. O teto mensal NÃO autoriza gasto sozinho.

O QUE AINDA NÃO FAZ: Batch (`enviar_lote`/`colher_lote`), provedores hermes/nous/HTTP direto como camadas, preço do
OpenRouter pago, conferência de `offset` da citação. Quem embute documento DENTRO de `mensagens` (em vez de
`documentos`) fica sem datamarking — a migração dos chamadores precisa mover o documento para `documentos`.

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
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from compliance_agent.adaptadores.llm import cache as C
from compliance_agent.adaptadores.llm import prompt_seguro as PS
from compliance_agent.adaptadores.llm import saida as S
from compliance_agent.adaptadores.llm.prompt_seguro import Documento
from compliance_agent.adaptadores.llm.saida import ABSTEVE, INDETERMINADO_FALHA_CITACAO, RESPONDIDO  # noqa: F401
from compliance_agent.dominio import mascara as M
from compliance_agent.llm import arquivo_estado as arq
from compliance_agent.llm import autorizacao_paga as AP
from compliance_agent.qualidade import regua as RG

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


class MascaraFalhou(GatewayErro):
    """Depois da máscara ainda sobrou CPF com DV válido no que iria ao provedor: nada é enviado."""


class CamadaForaDaPolitica(GatewayErro):
    """`so_camadas` pediu camadas que a política da tarefa não tem: nada é tentado."""


class CamadaPulada(RuntimeError):
    """Levantada por um BACKEND que não chegou a tentar (trava ocupada, teto, sem chave, sob pytest sem dublê). O
    gateway registra o motivo e segue para a próxima camada sem contar falha no circuito (não é falha do provedor)."""


class SemProvedor(GatewayErro):
    """Todas as camadas permitidas falharam ou foram puladas; `motivos` lista cada uma."""

    def __init__(self, msg: str, motivos: list[str]):
        super().__init__(msg)
        self.motivos = motivos


class PagaNaoAutorizada(SemProvedor):
    """Nada respondeu e a(s) camada(s) paga(s) foram recusadas por falta de autorização do dono: o item fica NÃO
    JULGADO, pendente para a assinatura. É um `SemProvedor` (quem já trata a falta de provedor segue igual)."""


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
    estado: str = RESPONDIDO               # RESPONDIDO | ABSTEVE | INDETERMINADO_FALHA_CITACAO
    saida: object = None                   # dominio.estados.Saida quando ABSTEVE (com o motivo)


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


def classe_da_tarefa(tarefa: str, pol: dict | None = None, padrao: str = "interno") -> str:
    """A `classe_dado` que a política declara para a tarefa (quem migrou sem mudar a assinatura do chamador usa esta).
    Sem declaração ⇒ `padrao` (interno: nunca vai a provedor de política de dados desconhecida)."""
    pol = pol or politica()
    c = ((pol.get("tarefas") or {}).get(tarefa) or {}).get("classe_dado") or padrao
    if c not in CLASSES:
        raise ClasseDadoRecusada(f"política: classe_dado '{c}' da tarefa '{tarefa}' é inválida")
    return c


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
            ("retry", "INT"), ("motivo_escalonamento", "TEXT"), ("release_ia", "TEXT"),
            # O6.1 (c)/(d), §3.11, O6.2
            ("cache", "TEXT"), ("estado", "TEXT"), ("injecao_suspeita", "INT"), ("citacoes_descartadas", "INT"),
            ("mascarados", "INT"),
            # 24/11/2026: autorização do dono por chamada/lote para camada paga (llm/autorizacao_paga)
            ("autorizacao", "TEXT"), ("autorizacao_quem", "TEXT"), ("autorizacao_quando", "TEXT"))


def _trace_db() -> Path:
    return Path(os.environ.get("JFN_LLM_TRACE_DB") or (_REPO / "data" / "llm_trace.db"))


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(_trace_db(), timeout=5)
    migrar(con)
    return con


def migrar(con: sqlite3.Connection) -> None:
    """Migração IDEMPOTENTE: cria a tabela se faltar e acrescenta só as colunas ausentes (nenhuma linha se perde).
    Sob BEGIN IMMEDIATE: o co-motor grava o trace dos dois lados (Claude e cascata) em threads simultâneas; sem a
    trava, as duas liam o PRAGMA antes de qualquer ALTER e a segunda caía em "duplicate column name" — a linha
    daquela chamada sumia do trace (medido 24/11: 91 de 600 linhas perdidas em base nova sob carga)."""
    con.execute("BEGIN IMMEDIATE")      # check-and-alter atômico entre conexões (espera o `timeout` da conexão)
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


def gasto_autorizacao_usd(aut_id: str) -> float:
    """Gasto do trace (chamadas pagas do gateway) sob uma autorização do dono. Ilegível ⇒ OrcamentoEsgotado."""
    try:
        con = _conectar()
        try:
            r = con.execute("SELECT COALESCE(SUM(custo_usd), 0) FROM llm_trace WHERE origem='gateway' AND pago=1 "
                            "AND autorizacao=?", (aut_id,)).fetchone()
        finally:
            con.close()
        return float(r[0] or 0.0)
    except sqlite3.Error as e:
        raise OrcamentoEsgotado(f"gasto da autorização ilegível ({type(e).__name__}) — sem prova de que cabe, nada pago")


def _reservar(est: float | None, critica: bool, pol: dict, aut: dict | None = None) -> tuple[str | None, str | None]:
    """(id_da_reserva, motivo_da_recusa). Sob trava de arquivo: paralelismo não fura o teto (nem o da autorização
    `aut` do dono, quando dada: gasto do trace daquele id + reservas vivas dele + esta ≤ `teto_usd` dela)."""
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
        if aut is not None:
            try:
                ja = gasto_autorizacao_usd(aut["id"])
            except OrcamentoEsgotado as e:
                return str(e)
            ja += sum(float(v["usd"]) for v in vivas.values() if v.get("aut") == aut["id"])
            if ja + est > float(aut["teto_usd"]):
                return (f"teto da autorização '{aut['id']}' do dono: US$ {ja:.4f} + US$ {est:.4f} passam de "
                        f"US$ {float(aut['teto_usd']):.2f}")
        vivas[rid] = {"usd": est, "em": agora, "mes": mes, **({"aut": aut["id"]} if aut is not None else {})}
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


def provedor_pago(provedor: str, pol: dict) -> bool:
    """Só `pago: false` EXPLÍCITO é grátis; provedor sem a marca (ou fora da política) conta como pago."""
    return ((pol.get("provedores") or {}).get(provedor) or {}).get("pago") is not False


def ordem_assinatura_primeiro(candidatos: list[tuple[int, str]], pol: dict) -> list[tuple[int, str]]:
    """Assinatura primeiro, depois as grátis (na ordem da política), as pagas por ÚLTIMO — último recurso."""
    def peso(cp):
        c, prov = cp
        if (pol.get("camadas") or {}).get(c, {}).get("nome") == "assinatura" or prov == "assinatura_claude":
            return 0
        return 2 if provedor_pago(prov, pol) else 1
    return sorted(candidatos, key=peso)


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


def _backend_free(*, tarefa, sistema, prompt, schema, modelo_pref, max_tokens, timeout) -> Retorno | None:
    from compliance_agent.llm import free_llm
    texto = free_llm.best_free_chat(_com_schema(prompt, schema), system=sistema, smart=True, fallback="")
    return Retorno(texto=texto, modelo=None) if texto and str(texto).strip() else None


def _assinatura_nao_tentou(tarefa: str, motivo: str) -> bool:
    """O `claude_motor` devolveu None SEM chamar o CLI? (trava ocupada, teto diário/semanal, sob pytest sem dublê)."""
    if motivo.startswith(("ocupado:", "sob pytest")):
        return True
    try:
        from compliance_agent.llm import claude_motor, orcamento
        return bool(orcamento.motivo_teto(claude_motor.ler_uso(), tarefa))
    except (ImportError, OSError, ValueError, KeyError, AttributeError):
        return False


def _backend_assinatura(*, tarefa, sistema, prompt, schema, modelo_pref, max_tokens, timeout,
                        espera=None) -> Retorno | None:
    from compliance_agent.llm import claude_motor
    p = claude_motor.pensar(tarefa, prompt, schema=schema, modelo=modelo_pref or claude_motor.MODELO_VOLUME,
                            sistema=sistema, timeout=timeout, backend="cli",
                            **({"espera": espera} if espera is not None else {}))
    if p is None:
        motivo = claude_motor.ultimo_motivo or "assinatura sem resposta"
        raise (CamadaPulada if _assinatura_nao_tentou(tarefa, motivo) else RuntimeError)(motivo)
    return Retorno(texto=p.texto, modelo=p.modelo, dados=p.dados)


def _backend_cascata_dc(*, tarefa, sistema, prompt, schema, modelo_pref, max_tokens, timeout) -> Retorno | None:
    """Camada 4: a cascata grátis da casa (DC), a mesma do co-motor e da contingência. Sob pytest nunca chama."""
    from compliance_agent.llm import contingencia
    if arq.sob_pytest():
        raise CamadaPulada("cascata: sob pytest sem dublê")
    texto = contingencia.gerar_cascata(_com_schema(prompt, schema), sistema, timeout, True)
    return Retorno(texto=texto, modelo=contingencia.modelo_da_cascata()) if texto and str(texto).strip() else None


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
        raise CamadaPulada(barrado)
    if cliente is None:
        if arq.sob_pytest():
            raise CamadaPulada("API: sob pytest sem cliente dublê")
        if not claude_api.disponivel():
            raise CamadaPulada("API: sem chave (ou JFN_CLAUDE_API=0)")
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
    "cascata_dc": _backend_cascata_dc,
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
def _mascarar_entrada(sistema: str, prompt: str, docs: list, mapa: dict) -> tuple[str, str, list]:
    """Máscara com UM mapa, na ordem fixa sistema → prompt → documentos (mesma entrada ⇒ mesmo mapa). Só o conteúdo
    é mascarado: o cabeçalho que o gateway escreve (ids, sha256) não — um sha com 11 dígitos seguidos viraria
    `[CPF_n]` e a citação nunca conferiria."""
    sm, _ = M.mascarar(sistema, mapa, estrito=True)
    pm, _ = M.mascarar(prompt, mapa, estrito=True)
    dm = []
    for d in docs:
        pags = tuple(M.mascarar(p, mapa, estrito=True)[0] for p in d.paginas) if d.paginas else None
        texto = "\n".join(pags) if pags else M.mascarar(d.texto, mapa, estrito=True)[0]
        meta = {k: M.mascarar(str(v), mapa, estrito=True)[0] for k, v in (d.metadados or {}).items()}
        dm.append(replace(d, texto=texto, paginas=pags, metadados=meta))
    return sm, pm, dm


def _expostos(sistema: str, prompt: str, docs: list) -> int:
    partes = [sistema, prompt] + [d.texto for d in docs] + [str(v) for d in docs for v in d.metadados.values()]
    return sum(M.cpfs_expostos(p) for p in partes)


def chamar(tarefa: str, mensagens: list[dict], *, prompt_version: str, modelo_pref: str | None = None,
           schema=None, classe_dado: str, max_tokens: int | None = None, timeout: float = 180.0,
           backends: dict[str, Backend] | None = None, documentos: list[Documento] | None = None,
           exigir_citacao: bool = False, verificador: S.Verificador | None = None, regra: str | None = None,
           contexto=None, cache: bool = False, ferramentas=None, so_camadas=None,
           modelo_por_camada: dict | None = None, espera: float | None = None,
           autorizacao_paga: str | None = None) -> Resposta:
    """Uma chamada de LLM pela política. Ver o docstring do módulo para o contrato.

    `documentos`: o que o modelo LÊ (entra com datamarking; nunca embuta documento em `mensagens`).
    `exigir_citacao`: a saída precisa de `citacoes` conferidas (pede `schema`). `verificador(citacao, {id: Documento})
    -> (ok, motivo)` troca o verificador padrão. `regra`/`contexto`: componentes extras da chave do cache.
    `ferramentas`: sempre recusado (dual-LLM). `so_camadas`: subconjunto das camadas da tarefa (na ordem da política;
    vazio ⇒ `CamadaForaDaPolitica`). `modelo_por_camada`: {camada: modelo} (None = o padrão do backend daquela
    camada) — sobrepõe `modelo_pref` só nas camadas listadas. `espera`: trava do `claude` (só a assinatura).
    `autorizacao_paga`: id da autorização do dono no livro (`llm/autorizacao_paga`; sem ele vale
    `JFN_LLM_AUTORIZACAO_PAGA`) — sem autorização válida nenhuma camada paga é tentada."""
    if not tarefa or not isinstance(tarefa, str):
        raise GatewayErro("tarefa obrigatória")
    if not prompt_version:
        raise GatewayErro("prompt_version obrigatório (rastreabilidade: nucleo/prompt_versao)")
    if classe_dado not in CLASSES:
        raise ClasseDadoRecusada(f"classe_dado '{classe_dado}' inválida; use uma de {', '.join(CLASSES)}")
    if ferramentas:
        raise GatewayErro("dual-LLM: o gateway não entrega ferramentas a modelo — quem lê documento nunca as recebe "
                          "e os backends de hoje são só texto")
    if exigir_citacao and schema is None:
        raise GatewayErro("exigir_citacao pede schema (as citações vêm no JSON, em 'citacoes')")
    docs = list(documentos or [])
    if any(not isinstance(d, Documento) for d in docs):
        raise GatewayErro("documentos: use adaptadores.llm.prompt_seguro.Documento")
    if len({d.documento_id for d in docs}) != len(docs):
        raise GatewayErro("documentos: documento_id repetido")
    pol, tab = politica(), precos()
    pt = politica_da_tarefa(tarefa, pol)
    camadas = pt["camadas"]
    if not camadas or camadas == [0] or 0 in camadas:
        raise TarefaDeterministica(f"tarefa '{tarefa}' é camada 0 (determinística) na política — não chama LLM")
    if so_camadas is not None:
        pedidas = {int(c) for c in so_camadas}
        camadas = [c for c in camadas if c in pedidas]
        if not camadas:
            raise CamadaForaDaPolitica(f"tarefa '{tarefa}': camadas {sorted(pedidas)} fora da política "
                                       f"({pt['camadas']})")
    mpc = {int(k): v for k, v in (modelo_por_camada or {}).items()}
    sistema0, prompt0 = _achatar(mensagens)
    backends = {**BACKENDS, **(backends or {})}
    schema_b, schema_r = S.schema_para_backend(schema), S.repr_schema(schema)
    resumo_docs = PS.resumo_documentos(docs)
    input_hash = _sha([sistema0, prompt0, schema_r, modelo_pref] + ([resumo_docs] if docs else []))
    chars_in = len(sistema0) + len(prompt0) + sum(len(d.texto) for d in docs)
    tid = uuid.uuid4().hex[:16]
    base = {"origem": "gateway", "trace_id": tid, "tarefa": tarefa[:60], "prompt_version": prompt_version,
            "input_hash": input_hash, "classe_dado": classe_dado, "chars_in": chars_in}

    candidatos, recusas_classe = [], []
    for c in camadas:
        prov = ((pol.get("camadas") or {}).get(c) or {}).get("provedor")
        if not prov:
            raise GatewayErro(f"camada {c} sem provedor na política")
        m = motivo_classe(classe_dado, prov, pol)
        (recusas_classe.append(f"camada {c}: {m}") if m else candidatos.append((c, prov)))
    candidatos = ordem_assinatura_primeiro(candidatos, pol)
    if not candidatos:
        _gravar({**base, "ok": 0, "ms": 0, "erro": "recusado: classe de dado",
                 "motivo_escalonamento": " | ".join(recusas_classe)})
        raise ClasseDadoRecusada(f"tarefa '{tarefa}', classe '{classe_dado}': " + " | ".join(recusas_classe))

    # máscara (§3.11) e montagem com prefixo fixo + datamarking (O6.2)
    mapa: dict[str, str] = {}
    sist_m, prompt_m, docs_m = _mascarar_entrada(sistema0, prompt0, docs, mapa)
    if _expostos(sist_m, prompt_m, docs_m):
        _gravar({**base, "ok": 0, "ms": 0, "erro": "recusado: máscara", "mascarados": len(mapa)})
        raise MascaraFalhou(f"tarefa '{tarefa}': CPF com DV válido sobrou depois da máscara — nada foi enviado")
    token = PS.novo_token("\n".join([d.texto for d in docs_m] + [str(v) for d in docs_m
                                                                 for v in d.metadados.values()])) if docs else None
    sistema, prompt = PS.montar(sist_m, prompt_m, docs_m, token=token, abstencao=schema is not None,
                                citacao=exigir_citacao)
    n_susp, alvos = PS.alvos_de_injecao(docs, sistema0 + "\n" + prompt0) if docs else (None, set())

    def desm(t: str) -> str:
        return M.desmascarar(t, mapa)

    def processar(texto, dados):
        return S.processar(texto, dados, schema=schema, exigir_citacao=exigir_citacao, documentos=docs,
                           verificador=verificador, desmascarar=desm)

    comuns = {"injecao_suspeita": n_susp, "mascarados": len(mapa)}
    comp = ch = None
    if cache:
        comp = C.componentes(montagem=PS.VERSAO_MONTAGEM, tarefa=tarefa, sistema=sistema0, prompt=prompt0,
                             documentos=resumo_docs, prompt_version=prompt_version, modelo=modelo_pref, regra=regra,
                             schema=schema_r, contexto=contexto, classe_dado=classe_dado, candidatos=candidatos,
                             exigir_citacao=exigir_citacao)
        ch = C.chave(comp)
        ini = time.monotonic()
        hit = C.ler(ch)
        if hit is not None:
            proc = processar(hit["texto"], hit["dados"])
            if proc.estado in (RESPONDIDO, ABSTEVE):
                ms = int((time.monotonic() - ini) * 1000)
                _gravar({**base, **comuns, "provedor": hit["provedor"], "camada": hit["camada"], "ok": 1, "ms": ms,
                         "modelo": hit["modelo"], "pago": 0, "output_hash": _sha(hit["texto"]),
                         "chars_out": len(hit["texto"]), "custo_usd": 0.0, "custo_fonte": "cache", "retry": 0,
                         "release_ia": hit["release_ia"], "cache": "hit", "estado": proc.estado,
                         "citacoes_descartadas": len(proc.descartadas)})
                return Resposta(texto=desm(hit["texto"]), dados=proc.dados, tarefa=tarefa, provedor=hit["provedor"],
                                camada=hit["camada"], modelo=hit["modelo"], custo_usd=0.0, tokens_in=None,
                                tokens_out=None, tokens_cache=None, latencia_ms=ms, retry=0,
                                motivo_escalonamento=None, release_ia=hit["release_ia"], input_hash=input_hash,
                                output_hash=_sha(hit["texto"]), trace_id=tid, estado=proc.estado, saida=proc.saida,
                                extras={"custo_fonte": "cache", "memo": False, "cache": "hit",
                                        "injecao_suspeita": n_susp, "citacoes_descartadas": proc.descartadas,
                                        "regua": RG.checar(tarefa, hit["modelo"], prompt_version, hit["release_ia"])})
            logger.warning("gateway: acerto de cache reprovado na validação de hoje (%s) — trata como miss",
                           proc.erro or proc.estado)
    comuns["cache"] = "miss" if cache else None

    motivos: list[str] = list(recusas_classe)
    so_orcamento = True       # todas as camadas viáveis caíram por orçamento? (para o tipo da exceção)
    nao_autorizada = False    # alguma camada paga recusada por falta de autorização do dono?
    aut_id = autorizacao_paga or AP.id_do_ambiente()
    tentativa = 0
    for camada, prov in candidatos:
        comuns = {k: v for k, v in comuns.items() if not k.startswith("autorizacao")}   # só na linha da camada paga
        pago = provedor_pago(prov, pol)
        mp = mpc.get(camada, modelo_pref) if camada in mpc else modelo_pref
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
        rid, mt, modelo_est, est, aut = None, max_tokens, None, None, None
        if pago:
            # regra do dono (24/11/2026): crédito pago só com autorização explícita dele — antes de qualquer outra coisa
            aut, recusa_aut = AP.verificar(aut_id, tarefa=tarefa, provedor=prov)
            if recusa_aut:
                m = f"{AP.RECUSA} — {recusa_aut}; item fica NÃO JULGADO, pendente para a assinatura"
                motivos.append(f"{prov}: {m}")
                so_orcamento, nao_autorizada = False, True
                _gravar({**base, **comuns, "provedor": prov, "camada": camada, "ok": 0, "ms": 0, "pago": 1,
                         "erro": f"recusado: {AP.RECUSA}", "autorizacao": aut_id,
                         "motivo_escalonamento": m[:500]})
                continue
            comuns = {**comuns, "autorizacao": aut["id"], "autorizacao_quem": str(aut["quem"])[:120],
                      "autorizacao_quando": aut["quando"]}
        if pago and backends.get(prov) is _backend_api and arq.sob_pytest():
            # o backend real recusaria de qualquer jeito: nem reserva no teto (o arquivo de reservas é de produção)
            motivos.append(f"{prov}: não tentou — API: sob pytest sem cliente dublê")
            so_orcamento = False
            continue
        if pago:
            modelo_est, mt, est = _estimativa_api(tarefa, mp, sistema, prompt, max_tokens, tab)
            rid, recusa = _reservar(est, pt["critica"], pol, aut)
            if recusa:
                motivos.append(f"{prov}: {recusa}")
                _gravar({**base, **comuns, "provedor": prov, "camada": camada, "ok": 0, "ms": 0,
                         "erro": "recusado: orçamento", "pago": 1, "modelo": modelo_est,
                         "motivo_escalonamento": recusa[:300]})
                continue
        so_orcamento = False
        ini = time.monotonic()
        ret, erro = None, ""
        extra = {"espera": espera} if (prov == "assinatura_claude" and espera is not None) else {}
        try:
            ret = backends[prov](tarefa=tarefa, sistema=sistema, prompt=prompt, schema=schema_b,
                                 modelo_pref=mp, max_tokens=mt, timeout=timeout, **extra)
            if ret is None:
                erro = "resposta vazia"
        except CamadaPulada as e:   # o backend não tentou: motivo no trace, sem contar falha no circuito
            _liberar(rid)
            motivos.append(f"{prov}: não tentou — {str(e)[:160]}")
            _gravar({**base, **comuns, "provedor": prov, "camada": camada, "ok": 0, "ms": 0, "pago": int(pago),
                     "erro": f"pulada: {str(e)[:160]}", "motivo_escalonamento": (" | ".join(motivos))[:500]})
            continue
        except Exception as e:      # noqa: BLE001 — backend nunca derruba o gateway; o TIPO vai ao trace
            erro = f"{type(e).__name__}: {str(e)[:160]}"
        ms = int((time.monotonic() - ini) * 1000)
        proc = None
        if ret is not None and not erro:
            ob = PS.obediencia(desm(ret.texto), alvos, token) if docs else None
            if ob:
                erro = ob
            else:
                proc = processar(ret.texto, ret.dados)
                erro = proc.erro
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
        _gravar({**base, **comuns, "provedor": prov, "camada": camada, "ok": int(ok), "ms": ms,
                 "erro": erro[:200] or None, "modelo": modelo, "pago": int(pago),
                 "output_hash": _sha(ret.texto) if ret is not None else None,
                 "chars_out": len(ret.texto) if ret is not None else None,
                 "tokens_in": ret.tokens_in if ret else None, "tokens_out": ret.tokens_out if ret else None,
                 "tokens_cache": ret.tokens_cache_lido if ret else None,
                 "tokens_cache_escrito": ret.tokens_cache_escrito if ret else None,
                 "custo_usd": custo, "custo_fonte": fonte, "retry": tentativa,
                 "motivo_escalonamento": (" | ".join(motivos))[:500] or None, "release_ia": release[:120],
                 "estado": proc.estado if proc else None,
                 "citacoes_descartadas": len(proc.descartadas) if proc else None})
        _liberar(rid)
        if ok:
            registrar_sucesso(prov)
            if cache and proc.estado in (RESPONDIDO, ABSTEVE):
                C.gravar(ch, comp, tarefa=tarefa, texto=ret.texto, dados=ret.dados, estado=proc.estado,
                         provedor=prov, camada=camada, modelo=modelo, release_ia=release)
            return Resposta(texto=desm(ret.texto), dados=proc.dados, tarefa=tarefa, provedor=prov, camada=camada,
                            modelo=modelo, custo_usd=custo, tokens_in=ret.tokens_in, tokens_out=ret.tokens_out,
                            tokens_cache=ret.tokens_cache_lido, latencia_ms=ms, retry=tentativa,
                            motivo_escalonamento=" | ".join(motivos) or None, release_ia=release,
                            input_hash=input_hash, output_hash=_sha(ret.texto), trace_id=tid, estado=proc.estado,
                            saida=proc.saida,
                            extras={"custo_fonte": fonte, "memo": ret.memo, "cache": comuns["cache"],
                                    "injecao_suspeita": n_susp, "citacoes_descartadas": proc.descartadas,
                                    # O6.6: CHECAGEM da régua (§3.10) — só o rótulo exibido; não muda o roteamento
                                    "regua": RG.checar(tarefa, modelo, prompt_version, release)})
        registrar_falha(prov, pol)
        motivos.append(f"{prov}: {erro}")
        tentativa += 1

    if nao_autorizada:
        raise PagaNaoAutorizada(f"tarefa '{tarefa}': {AP.RECUSA} — nenhuma camada respondeu: " + " | ".join(motivos),
                                motivos)
    if so_orcamento:
        raise OrcamentoEsgotado(f"tarefa '{tarefa}': " + " | ".join(motivos))
    raise SemProvedor(f"tarefa '{tarefa}': nenhuma camada respondeu — " + " | ".join(motivos), motivos)
