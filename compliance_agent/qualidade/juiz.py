# -*- coding: utf-8 -*-
"""juiz — o juiz subjetivo das regras de qualidade (família SUB), pelo Claude da ASSINATURA.

O que faz: julga TUDO o que o painel, os casos do vault, o Yoda e os produtos da casa AFIRMAM ao dono e
dá nota de 0 a 4 em cada critério da rubrica (`config/qualidade_regras.yaml` → `rubricas`): proporção, moldura,
hipótese inocente, padrão de auditoria, jornalista hostil, presunção de inocência, utilidade, clareza,
acabamento. Nota ≤ 1 é violação da regra SUB correspondente (o sensor `juiz_qualidade` abre o item).

REGRAS DESTE MÓDULO (ordem do dono, 13/11/2026: "fable tem que usar assinatura só"):
  · toda chamada ao Claude sai por `claude_motor.pensar(..., backend="cli")` — Claude Code CLI, sem chave no
    ambiente, sem `--bare`. NUNCA o backend automático do motor (cairia na API paga) — há catraca (`test_regra_juiz.py`);
  · se a assinatura não comporta o volume, a fila anda mais devagar (correção e risco primeiro); nunca se troca de backend;
  · co-motor: nas afirmações que já são públicas no painel, a cascata gratuita julga a MESMA entrada em paralelo
    (`comotor.juizo`) e os dois vereditos vão lado a lado para o banco de cruzamento. O veredito da cascata nunca
    abre nem fecha violação sozinho (COR-14): sem o Claude, a avaliação fica `PENDENTE`;
  · material do vault (casos internos) vai SÓ ao Claude da assinatura — não sai para provedor gratuito;
  · CPF é mascarado antes de qualquer envio; nada do que o juiz lê é gravado no registro de uso do motor.

Cobertura TOTAL (20/11/2026, dono: "como que o juiz não julga tudo? precisa julgar, não apenas um baixo limite"):
  · FILA COMPLETA: pendente = candidata sem veredito vigente para a impressão (sha1 do texto) ATUAL. Ordem:
    (a) reprovada cuja impressão mudou (correção à espera de confirmação), (b) nunca julgada — primeiro a de maior
    risco de CADA grupo (nenhum grupo fica sem vaga se o orçamento cortar), depois o resto por risco, (c) julgada
    cujo texto mudou, por risco, (d) revalidação periódica (veredito com mais de REVALIDAR_DIAS, texto igual);
  · CACHE POR CONTEÚDO: veredito vigente enquanto a impressão não muda — o que não mudou não volta ao modelo;
  · LOTES: K afirmações (padrão LOTE_PADRAO) numa só chamada, mesma rubrica, JSON por item com o `id` ecoado; item
    ausente, trocado ou com nota inválida volta à fila — nunca se inventa nota. Lote é homogêneo em rubrica e em
    `publica` (material interno nunca divide chamada com o que vai à cascata);
  · ORÇAMENTO POR TEMPO: `rodar(..., n=None, minutos=M)` processa lotes até a fila zerar, o tempo acabar ou o teto
    do motor/contingência parar a assinatura — o progresso é gravado a cada lote (corte no meio retoma de onde parou);
  · COBERTURA MEDIDA: `data/qualidade_juiz_fila.json` (candidatas, julgadas vigentes, cobertura %, pendentes e há
    quanto tempo) — o painel de conformidade e o sensor CST-15 leem dali.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Callable

from compliance_agent.qualidade import regras, sensores, verificadores as v
from compliance_agent.qualidade.arquivos import gravar_json

logger = logging.getLogger(__name__)

TAREFA = "juiz_qualidade"
BACKEND = "cli"                     # assinatura. Não mude: a catraca barra.
AMOSTRA_PADRAO = 6                  # `-n` sem `--ate-esvaziar`: nº de AFIRMAÇÕES (compatível com o cron antigo)
LOTE_PADRAO = 4                     # afirmações por chamada (`--lote` ou JFN_JUIZ_LOTE)
REVALIDAR_DIAS = 30                 # veredito de texto igual mais velho que isto vai ao FIM da fila (0 desliga)
TIMEOUT_ITEM_S = 300.0              # prazo de uma chamada de 1 item; cada item a mais no lote soma TIMEOUT_EXTRA_S
TIMEOUT_EXTRA_S = 150.0
MIN_SEGUNDOS_LOTE = 180.0           # com menos que isto no orçamento de tempo, não se começa lote novo
_FALHAS = (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error)
_PESO_GRAU = {"🔴": 3.0, "alto": 3.0, "alta": 3.0, "critico": 3.0, "crítico": 3.0, "🟡": 2.0, "medio": 2.0,
              "médio": 2.0, "media": 2.0, "manchete": 2.5}

SISTEMA = (
    "Você é revisor de qualidade de um sistema de auditoria usado por um deputado estadual para fiscalizar o "
    "Poder Executivo. Seu papel é o de um auditor sênior de tribunal de contas, cético e justo: você não confirma "
    "nem refuta o fato (não tem a fonte primária aqui) — você julga se a AFIRMAÇÃO, do jeito que foi escrita, se "
    "sustenta com o que ela mesma apresenta. Desconfie de moldura que afirma mais que o dado, de número sem "
    "natureza, época ou esfera, de explicação inocente só nomeada, e de linguagem que trata indício como culpa. "
    "Seja exigente: este é um projeto de governo e não pode haver margem para erro. Responda em português do Brasil."
)


@dataclass
class Afirmacao:
    id: str
    sistema: str                    # painel · vault · yoda
    rotulo: str
    texto: str
    grau: str = ""
    valor: float = 0.0
    publica: bool = False           # True = já é exibida no painel (pode ser cruzada com a cascata)
    pessoa_fisica: bool = False

    @property
    def risco(self) -> float:
        return _PESO_GRAU.get(self.grau.strip().lower(), 1.0) * (1.0 + math.log10(max(self.valor, 1.0)))

    @property
    def grupo(self) -> str:
        if self.id.startswith("produto:"):                       # relatório e parecer Lex: um grupo só na amostra
            return "produto"
        return ":".join(self.id.split(":")[:2]) if self.id.startswith("painel:gestao:") else self.sistema

    @property
    def impressao(self) -> str:
        return hashlib.sha1(self.texto.encode("utf-8", "replace")).hexdigest()[:16]


@dataclass
class Avaliacao:
    id: str
    sistema: str
    rotulo: str
    impressao: str
    em: str
    estado: str                     # JULGADA (Claude respondeu) · PENDENTE (só a cascata, ou ninguém)
    juiz: str = ""
    notas: dict = field(default_factory=dict)
    motivos: dict = field(default_factory=dict)
    veredito: str = ""
    o_que_falta: str = ""
    escalar: bool = False
    motivo_escalar: str = ""
    pre_sinais: list = field(default_factory=list)
    cascata: dict = field(default_factory=dict)


# ───────────────────────────── de onde vêm as afirmações ─────────────────────────────
_RE_REAIS = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2})")


def _valores_reais(texto: str) -> list[float]:
    """Os valores "R$ 1.234,56" de um texto (o maior pesa no risco da afirmação)."""
    return [float(x.replace(".", "").replace(",", ".")) for x in _RE_REAIS.findall(texto)]


def _de_manchetes(ctx: sensores.Ctx) -> list[Afirmacao]:
    out = []
    for m in ctx.manchetes():
        try:
            p = ctx.payload(m["rota"])
        except RuntimeError:
            continue
        nums = sensores.numeros(m, p)
        if not nums:
            continue
        extras = {k: p.get(k) for k in ("explicacao", "ressalva", "escala", "gerado_em") if isinstance(p, dict) and p.get(k)}
        texto = (f"Card do painel: {m.get('superficie', m['id'])}\nO que o card afirma: {m.get('afirma', '')}\n"
                 f"Números exibidos: {json.dumps(nums, ensure_ascii=False)}\n"
                 f"Proveniência exibida: {json.dumps(p.get('proveniencia'), ensure_ascii=False) if isinstance(p, dict) else None}\n"
                 f"Textos de apoio da rota: {json.dumps(extras, ensure_ascii=False)[:1500]}")
        out.append(Afirmacao(f"painel:{m['id']}", "painel", m.get("superficie", m["id"])[:90], texto, "manchete",
                             float(nums.get("valor") or 0), publica=True))
    return out


def _de_couto(ctx: sensores.Ctx) -> list[Afirmacao]:
    arq = ctx.dados / "governo_couto_suspeitas.json"
    if not arq.exists():
        return []
    out = []
    for a in json.loads(arq.read_text(encoding="utf-8")).get("achados", []):
        if not str(a.get("grau", "")).startswith(("🔴", "🟡")):
            continue
        campos = {k: a.get(k) for k in ("regra_ou_hipotese", "grau", "orgao", "valor_ob", "fonte", "explicacao_inocente",
                                         "proximo_passo", "prova_primaria", "verificacao", "revisao_cetica")}
        texto = "Achado exibido na aba de análise de gestão do painel:\n" + json.dumps(campos, ensure_ascii=False, default=str)[:3500]
        out.append(Afirmacao(f"painel:gestao:{a.get('id')}", "painel", str(a.get("regra_ou_hipotese", a.get("id")))[:90], texto,
                             str(a.get("grau", ""))[:1], float(a.get("valor_ob") or 0), publica=True))
    return out


def _de_vault(ctx: sensores.Ctx) -> list[Afirmacao]:
    out = []
    for arq, texto, fm in sensores.casos_do_vault(ctx):
        if not sensores.caso_alto_aberto(fm):
            continue
        valor = fm.get("valor") or fm.get("valor_total") or 0
        valor = float(valor) if isinstance(valor, (int, float)) else 0.0
        out.append(Afirmacao(f"vault:{arq.stem}", "vault", str(fm.get("titulo") or arq.stem)[:90],
                             "Caso aberto no acervo interno, grau alto. Frontmatter e início do corpo:\n" + texto[:4500],
                             "alto", valor, publica=False, pessoa_fisica=bool(re.search(r"\*\*\*\.\d{3}\.\d{3}-\*\*", texto))))
    return out


# Modo /cc do Yoda (desde 15/11/2026): o plugin `~/.hermes/plugins/jfn-claude` roda o Claude Code com cwd ~/JFN e
# manda o `result` DIRETO pelo Bot API — a resposta não entra no state.db do Hermes. Ela fica no transcript da
# sessão; o log do plugin guarda só o sha256 do que foi enviado (`sha_enviado`/`sha_resultado`).
PASTA_CC = (Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
            / re.sub(r"[^A-Za-z0-9]", "-", str(Path.home() / "JFN")))
_MARCADOR_CC = "[[PRECISA_OK]]"                                  # o executor tira antes de enviar (executor.MARCADOR)
_RE_SESSAO = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _respostas_cc(ctx: sensores.Ctx, limite: int = 40, sessoes: int = 5) -> list[str]:
    """Respostas finais do /cc ENTREGUES ao dono, da mais nova para a mais velha. Só entra texto do assistant cujo
    sha256 bate com o log do plugin (prova de entrega; passo intermediário não entra). Só `origem=modo_direto`
    (Telegram) — WhatsApp/secretário nunca (regra do dono: nada do WhatsApp fora da VM)."""
    log = ctx.hermes / "logs" / "jfn-claude.jsonl"
    if not log.exists():
        return []
    entregues, ordem = set(), []                                 # ordem: sessões da mais recente à mais antiga
    for linha in reversed(log.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            ev = json.loads(linha)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("origem") != "modo_direto" or not ev.get("ok"):
            continue
        sid = str(ev.get("sessao_id") or "")
        if not _RE_SESSAO.match(sid):
            continue
        entregues |= {h for h in (ev.get("sha_enviado"), ev.get("sha_resultado")) if h}
        if sid not in ordem:
            ordem.append(sid)
    out, vistos = [], set()
    for sid in ordem[:sessoes]:
        arq = PASTA_CC / f"{sid}.jsonl"
        if not arq.exists():
            continue
        textos = []
        for linha in arq.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(linha)
            except ValueError:
                continue
            msg = ev.get("message") if isinstance(ev, dict) and ev.get("type") == "assistant" else None
            for b in (msg.get("content") if isinstance(msg, dict) else None) or []:
                if isinstance(b, dict) and b.get("type") == "text":
                    t = str(b.get("text") or "").replace(_MARCADOR_CC, "").strip()
                    h = hashlib.sha256(t.encode("utf-8")).hexdigest()
                    if h in entregues and h not in vistos:
                        vistos.add(h)
                        textos.append(t)
        out += reversed(textos)
    return out[:limite]


def _de_yoda(ctx: sensores.Ctx) -> list[Afirmacao]:
    try:
        textos = [("cc", t) for t in _respostas_cc(ctx)]
    except _FALHAS:
        textos = []
    try:
        textos += [("hermes", t) for t in sensores.textos_yoda(ctx, 40)]
    except _FALHAS:
        pass
    out = []
    for origem, t in textos:
        if "R$" not in t and not re.search(r"🔴|🟡", t):
            continue                                            # só resposta que AFIRMA número ou grau
        vals = _valores_reais(t)
        rotulo, cab = (("resposta do /cc (Claude Code) ao dono", "Resposta enviada ao dono no Telegram (modo /cc):\n")
                       if origem == "cc" else ("resposta do Yoda ao dono", "Resposta enviada pelo assistente no Telegram:\n"))
        a = Afirmacao("", "yoda", rotulo, cab + t[:3500], "🔴" if "🔴" in t else "", max(vals, default=0.0), publica=False)
        a.id = f"yoda:{a.impressao}"
        out.append(a)
    return out[:8]


# Produtos da casa (`reports/`, raiz — `reports/arquivo/` é o acervo podado): relatório de fornecedor e de órgão
# (`inteligencia_*`), parecer Lex (`parecer_lex_*`) e dossiê (`dossie_*`, hoje só PDF — entra se houver .md/.html).
PRODUTO_N = 12    # 21/11/2026: 6 → 12 com as famílias novas (eram ~10 produtos nos últimos 30 dias)
PRODUTO_DIAS = 30
# 21/11/2026: + peças da Comissão de Orçamento (comissao_P*), relatório de contrato, trajetória das finanças e perícia
# Enge Prat — estavam em reports/ e o juiz nunca as julgava (só inteligencia/parecer_lex/dossie).
_RE_PRODUTO = re.compile(r"^((?:inteligencia|parecer_lex|dossie|comissao_P\d+|contrato|trajetoria|engeprat)_.+?)"
                         r"_(\d{4}-\d{2}-\d{2})\.(md|html)$")
_RE_PESSOAL = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)|\*{3}\.\d{3}\.\d{3}-\*{2}|(?i:\bcpf\b)[^\d\n]{0,20}\d{11}(?!\d)")


def _de_produtos(ctx: sensores.Ctx) -> list[Afirmacao]:
    """Os PRODUTO_N entregáveis mais recentes (por mtime, até PRODUTO_DIAS), uma versão por produto. Vai o começo
    do texto (capa + sumário + primeiras seções). Com dado pessoal (CPF), `publica=False`: só o Claude da assinatura."""
    pasta = ctx.repo / "reports"
    if not pasta.is_dir():
        return []
    limite = (ctx.agora - timedelta(days=PRODUTO_DIAS)).timestamp()
    mais_novo: dict[str, Path] = {}
    for arq in pasta.iterdir():
        m = _RE_PRODUTO.match(arq.name)
        if not m or not arq.is_file() or arq.stat().st_mtime < limite:
            continue
        base = m.group(1).rstrip("_")                            # "…cartografia__2026-11-15" (órgão) tem "_" duplo
        if base not in mais_novo or arq.stat().st_mtime > mais_novo[base].stat().st_mtime:
            mais_novo[base] = arq
    out = []
    for base, arq in sorted(mais_novo.items(), key=lambda kv: kv[1].stat().st_mtime, reverse=True)[:PRODUTO_N]:
        bruto = arq.read_text(encoding="utf-8", errors="replace")
        if arq.suffix == ".html":
            bruto = re.sub(r"\s+\n", "\n", re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)\b.*?</\1>", "", bruto)))
        trecho = bruto[:4500]
        vals = _valores_reais(trecho)
        pessoal = bool(_RE_PESSOAL.search(bruto))
        grau = "🔴" if "🔴" in trecho else ("🟡" if "🟡" in trecho else "")
        sistema = "lex" if base.startswith("parecer_lex") else "relatorios"
        out.append(Afirmacao(f"produto:{base}", sistema, base[:90],
                             f"Entregável da casa enviado ao dono ({arq.name}). Início do documento:\n" + trecho,
                             grau, max(vals, default=0.0), publica=not pessoal, pessoa_fisica=pessoal))
    return out


FONTES: tuple[Callable, ...] = (_de_manchetes, _de_couto, _de_vault, _de_yoda, _de_produtos)


def candidatas(ctx: sensores.Ctx) -> list[Afirmacao]:
    out = []
    for fonte in FONTES:
        try:
            out += fonte(ctx)
        except _FALHAS as e:
            logger.warning("juiz: fonte %s não leu (%s)", fonte.__name__, type(e).__name__)
    for a in out:
        a.texto = v.mascarar_cpfs(a.texto)
    return out


def _int_env(nome: str, padrao: int) -> int:
    try:
        return int(os.environ.get(nome, "") or padrao)
    except ValueError:
        return padrao


def lote_padrao() -> int:
    return max(1, _int_env("JFN_JUIZ_LOTE", LOTE_PADRAO))


def revalidar_dias() -> int:
    return max(0, _int_env("JFN_JUIZ_REVALIDAR_DIAS", REVALIDAR_DIAS))


def _reprovada(h: dict) -> bool:
    return h.get("estado") == "JULGADA" and any(isinstance(x, (int, float)) and not isinstance(x, bool) and x <= 1
                                                for x in (h.get("notas") or {}).values())


def situacao(a: Afirmacao, historico: dict, agora: datetime) -> str:
    """vigente · corrigida (reprovada e o texto mudou) · nova (nunca julgada) · mudada · revalidar (texto igual,
    veredito velho). Só `vigente` e `revalidar` contam como cobertas: o veredito vale enquanto a impressão não muda."""
    h = historico.get(a.id) or {}
    if h.get("estado") != "JULGADA":
        return "nova"
    if h.get("impressao") != a.impressao:
        return "corrigida" if _reprovada(h) else "mudada"
    dias = revalidar_dias()
    if dias and str(h.get("em", "")) < (agora - timedelta(days=dias)).isoformat():
        return "revalidar"
    return "vigente"


_ORDEM_SITUACAO = ("corrigida", "nova", "mudada", "revalidar")


def fila(cands: list[Afirmacao], historico: dict, agora: datetime, *, revalidacao: bool = True) -> list[Afirmacao]:
    """A fila COMPLETA do juiz, na ordem em que deve ser julgada (ver o cabeçalho). Na faixa das nunca julgadas, a
    de maior risco de cada grupo vem antes (vaga reservada: 20/11/2026, com 5 grupos os de maior valor enchiam a
    amostra e Yoda/produto nunca eram julgados); depois, puro risco."""
    por_sit: dict[str, list[Afirmacao]] = {k: [] for k in _ORDEM_SITUACAO}
    vistos = set()
    for a in cands:
        if a.id in vistos:
            continue
        vistos.add(a.id)
        sit = situacao(a, historico, agora)
        if sit in por_sit:
            por_sit[sit].append(a)
    # FOCO (22/11/2026): em cada situação, metade com afirmação sobre o período Couto (aba de gestão), cada metade
    # na ordem de risco (compliance_agent/foco). A vaga reservada de cada grupo vem antes e não entra na cota.
    from compliance_agent.foco import intercalar

    def _couto(a: Afirmacao) -> bool:
        return a.id.startswith("painel:gestao:")
    for lista in por_sit.values():
        lista.sort(key=lambda a: (-a.risco, a.id))
    novas, cabecas, grupos = por_sit["nova"], [], set()
    for a in novas:
        if a.grupo not in grupos:
            grupos.add(a.grupo)
            cabecas.append(a)
    por_sit["nova"] = cabecas + intercalar([a for a in novas if a not in cabecas], _couto)
    por_sit["revalidar"].sort(key=lambda a: str((historico.get(a.id) or {}).get("em", "")))
    for k in ("corrigida", "mudada", "revalidar"):
        por_sit[k] = intercalar(por_sit[k], _couto)
    return [a for k in _ORDEM_SITUACAO if revalidacao or k != "revalidar" for a in por_sit[k]]


def amostrar(cands: list[Afirmacao], historico: dict, n: int, agora: datetime) -> list[Afirmacao]:
    """Compatível com o `-n` antigo: as `n` primeiras da fila completa."""
    return fila(cands, historico, agora)[:max(0, n)]


def chave_lote(a: Afirmacao) -> tuple:
    """Só divide chamada quem tem a MESMA rubrica e o mesmo canal (público pode ir à cascata; interno, nunca)."""
    return (tuple(criterios_de(a.sistema)), bool(a.publica))


def lotes(itens: list[Afirmacao], k: int) -> list[list[Afirmacao]]:
    """Agrupa respeitando a ordem da fila: a cabeça abre o lote e ele se completa com as próximas de mesma chave."""
    k = max(1, k)
    restantes, out = list(itens), []
    while restantes:
        cab = restantes.pop(0)
        ch, lote = chave_lote(cab), [cab]
        for a in list(restantes):
            if len(lote) >= k:
                break
            if chave_lote(a) == ch:
                lote.append(a)
                restantes.remove(a)
        out.append(lote)
    return out


def cobertura(cands: list[Afirmacao], historico: dict, agora: datetime, anterior: dict | None = None,
              k: int | None = None) -> dict:
    """A medida da cobertura (sem chamar modelo). `anterior` = a fila gravada antes: guarda DESDE QUANDO cada
    pendente está pendente com o texto atual (a idade da mais antiga é o que o sensor CST-15 cobra)."""
    desde_ant = (anterior or {}).get("pendentes_desde") or {}
    unicas = list({a.id: a for a in cands}.values())
    sit = {a.id: situacao(a, historico, agora) for a in unicas}
    pend = [a for a in unicas if sit[a.id] not in ("vigente", "revalidar")]
    desde = {}
    for a in pend:
        ant = desde_ant.get(a.id) or {}
        desde[a.id] = {"desde": ant["desde"] if ant.get("impressao") == a.impressao and ant.get("desde")
                       else agora.isoformat(timespec="seconds"), "impressao": a.impressao, "situacao": sit[a.id]}
    mais_antiga = min((d["desde"] for d in desde.values()), default=None)
    ordem = fila(unicas, historico, agora)
    julgadas = len(unicas) - len(pend)
    plano = lotes([a for a in ordem if sit[a.id] != "revalidar"], k or lote_padrao())
    return {
        "em": agora.isoformat(timespec="seconds"),
        "candidatas": len(unicas), "julgadas_vigentes": julgadas,
        "cobertura_pct": round(100.0 * julgadas / len(unicas), 1) if unicas else 100.0,
        "pendentes": len(pend),
        "mais_antiga_pendente_em": mais_antiga,
        "mais_antiga_pendente_dias": round((agora - datetime.fromisoformat(mais_antiga)).total_seconds() / 86400, 2)
        if mais_antiga else 0.0,
        "a_revalidar": sum(s == "revalidar" for s in sit.values()),
        "por_situacao": {k_: sum(s == k_ for s in sit.values()) for k_ in ("vigente",) + _ORDEM_SITUACAO},
        "por_grupo": {g: {"candidatas": sum(a.grupo == g for a in unicas), "pendentes": sum(a.grupo == g for a in pend)}
                      for g in sorted({a.grupo for a in unicas})},
        "lote": k or lote_padrao(), "chamadas_para_zerar": len(plano),
        "proximas": [{"id": a.id, "situacao": sit[a.id], "risco": round(a.risco, 2)} for a in ordem[:40]],
        "pendentes_desde": desde,
    }


# ───────────────────────────── o pedido ao juiz ─────────────────────────────
def criterios_de(sistema: str) -> list[str]:
    """Os critérios da rubrica cuja regra SUB se aplica ao sistema (acabamento de entregável não se cobra de um
    card; o juiz não dá nota no que não vale ali)."""
    por_id = regras.por_id()
    return [c for c, r in regras.rubricas().items() if sistema in por_id[r["regra"]].aplica]


_COMO_LER = ("\nCOMO LER A ENTRADA: ela foi extraída por código da tela ou do arquivo e pode chegar como campos "
             "estruturados (JSON). NÃO julgue o formato da extração, nomes de campo nem termos internos desta ficha "
             "(\"card\", \"cockpit\", \"chip\", códigos de regra): julgue o CONTEÚDO que o dono lê — rótulo, número, "
             "ressalvas e o que falta. Se a entrada não traz proveniência, isso é fato a pesar (a tela não a mostra).")
_INSTRUCAO_NOTAS = ("\nPara cada nota ≤ 2, diga em uma frase o que está errado e o que tornaria a afirmação aceitável. "
                    "`veredito`: aprovada (todas ≥ 3) · ressalva (alguma = 2, nenhuma ≤ 1) · reprovada (alguma ≤ 1).")


def _linhas_rubrica(crit: list[str]) -> list[str]:
    d = regras.bruto()
    linhas = ["RUBRICA — dê nota de 0 a 4 em cada critério (use null só se o critério realmente não se aplica):"]
    for nota, desc in d["escala"].items():
        linhas.append(f"  {nota} = {desc}")
    for nome, r in d["rubricas"].items():
        if nome not in crit:
            continue
        linhas.append(f"\n[{nome}] {r['pergunta']}\n  exemplo RUIM: {r['ancora_ruim'].strip()}\n  exemplo BOM: {r['ancora_boa'].strip()}")
    linhas.append("\nESCALAR AO DONO (humano) quando: " + " | ".join(d["escalar_humano"]))
    return linhas


def _linhas_pre(pre: list[str]) -> str:
    return "\n".join(f"  - {p}" for p in pre[:12]) if pre else "  (nenhum)"


def montar_prompt(a: Afirmacao, pre: list[str]) -> str:
    linhas = _linhas_rubrica(criterios_de(a.sistema))
    linhas.append("\nPRÉ-SINAIS do verificador automático (determinístico; pode haver falso positivo — julgue você):\n"
                  + _linhas_pre(pre))
    linhas.append(_COMO_LER)
    linhas.append(f"\nAFIRMAÇÃO A JULGAR (origem: {a.sistema}; grau exibido: {a.grau or 'não informado'}):\n«««\n{a.texto}\n»»»")
    linhas.append(_INSTRUCAO_NOTAS)
    # o formato vai NO PROMPT (e não pelo `schema` do motor): a cascata recebe o mesmo texto e precisa dele também
    linhas.append("\nResponda SOMENTE com um objeto JSON válido, sem texto fora dele, neste formato:\n"
                  + json.dumps(esquema(a.sistema), ensure_ascii=False))
    return "\n".join(linhas)


def rotulos_lote(n: int) -> list[str]:
    return [f"A{i}" for i in range(1, n + 1)]


def montar_prompt_lote(lote: list[Afirmacao], pres: list[list[str]]) -> str:
    """Um pedido para K afirmações de MESMA rubrica. Cada item é julgado sozinho; a resposta traz o `id` de volta
    (item trocado ou faltando não vira nota de ninguém)."""
    sistema = lote[0].sistema
    rots = rotulos_lote(len(lote))
    linhas = _linhas_rubrica(criterios_de(sistema))
    linhas.append(_COMO_LER)
    linhas.append(f"\nVOCÊ VAI JULGAR {len(lote)} AFIRMAÇÕES INDEPENDENTES. Julgue cada uma SÓ pelo que ela mesma "
                  "apresenta: não use uma para completar ou desculpar outra e não as compare entre si. A régua é a "
                  "mesma de quando se julga uma afirmação sozinha — o lote não afrouxa nem endurece a nota.")
    for rot, a, pre in zip(rots, lote, pres):
        linhas.append(f"\n════ ITEM {rot} — id: {a.id} (origem: {a.sistema}; grau exibido: {a.grau or 'não informado'}) ════"
                      "\nPRÉ-SINAIS do verificador automático (determinístico; pode haver falso positivo — julgue você):\n"
                      f"{_linhas_pre(pre)}\nAFIRMAÇÃO:\n«««\n{a.texto}\n»»»")
    linhas.append(_INSTRUCAO_NOTAS)
    um = {"id": "o id do item, copiado exatamente"} | esquema(sistema)
    linhas.append(f"\nResponda SOMENTE com um objeto JSON válido, sem texto fora dele, com UMA entrada por item "
                  f"({', '.join(rots)}) dentro de \"itens\", neste formato:\n"
                  + json.dumps({"itens": {r: um for r in rots}}, ensure_ascii=False))
    return "\n".join(linhas)


def itens_do_lote(d: dict | None, lote: list[Afirmacao]) -> list[dict | None]:
    """A resposta de cada item, na ordem do lote; None = ausente, malformado ou com `id` que não é o do item."""
    bruto = d.get("itens") if isinstance(d, dict) else None
    if isinstance(bruto, list):
        bruto = {str(x.get("item") or x.get("rotulo") or ""): x for x in bruto if isinstance(x, dict)}
    if not isinstance(bruto, dict):
        return [None] * len(lote)
    out = []
    for rot, a in zip(rotulos_lote(len(lote)), lote):
        sub = bruto.get(rot)
        out.append(sub if isinstance(sub, dict) and str(sub.get("id") or "").strip() == a.id else None)
    return out


def timeout_lote(n: int) -> float:
    return TIMEOUT_ITEM_S + TIMEOUT_EXTRA_S * max(0, n - 1)


def esquema(sistema: str | None = None) -> dict:
    crit = criterios_de(sistema) if sistema else list(regras.rubricas())
    return {"notas": {c: "0-4 ou null" for c in crit}, "motivos": {c: "frase curta (obrigatória se nota ≤ 2)" for c in crit},
            "veredito": "aprovada|ressalva|reprovada", "o_que_falta": "documento ou ajuste que resolve",
            "escalar": "true|false", "motivo_escalar": "se escalar"}


VEREDITOS = ("aprovada", "ressalva", "reprovada")      # o nível do cruzamento com a cascata é a posição (0 · 1 · 2)


def normalizar(txt: str):
    """Para o cruzamento com a cascata: aprovada 0 · ressalva 1 · reprovada 2."""
    d = _json(txt) or {}
    ver = str(d.get("veredito") or "").strip().lower()
    return (ver or None), (VEREDITOS.index(ver) if ver in VEREDITOS else None), None


def normalizar_lote(txt: str):
    """Cruzamento de um LOTE com a cascata: o pior veredito entre os itens (das notas, por código)."""
    d = _json(txt) or {}
    bruto = d.get("itens")
    subs = list(bruto.values()) if isinstance(bruto, dict) else (bruto if isinstance(bruto, list) else [])
    niveis = []
    for sub in subs:
        if isinstance(sub, dict):
            notas, _ = _limpar_notas(sub)
            ver = veredito_de(notas)
            if ver:
                niveis.append(VEREDITOS.index(ver))
    if not niveis:
        return None, None, None
    pior = max(niveis)
    return VEREDITOS[pior], pior, None


def _json(txt: str):
    from compliance_agent.llm.json_resposta import parse_json_llm
    d = parse_json_llm(txt or "")
    return d if isinstance(d, dict) else None


def _limpar_notas(d: dict, sistema: str | None = None) -> tuple[dict, dict]:
    crit = criterios_de(sistema) if sistema else list(regras.rubricas())
    notas, motivos = {}, {}
    for c in crit:
        n = (d.get("notas") or {}).get(c)
        if isinstance(n, (int, float)) and not isinstance(n, bool) and 0 <= n <= 4:
            notas[c] = n
            m = str((d.get("motivos") or {}).get(c) or "").strip()
            if m:
                motivos[c] = m[:400]
    return notas, motivos


def veredito_de(notas: dict) -> str:
    """O veredito sai das NOTAS, por código — não da palavra que o modelo escreveu."""
    if not notas:
        return ""
    menor = min(notas.values())
    return "reprovada" if menor <= 1 else ("ressalva" if menor == 2 else "aprovada")


def deve_escalar(a: Afirmacao, notas: dict, pediu: bool) -> tuple[bool, str]:
    """As condições de `escalar_humano` que o código consegue conferir sozinho (as demais vêm do próprio juiz)."""
    if notas and min(notas.values()) == 0:
        return True, "nota 0 em algum critério"
    if a.pessoa_fisica:
        return True, "pessoa física referida"
    if a.valor >= 10_000_000 and any(notas.get(c, 4) <= 2 for c in ("moldura", "inocente", "auditor")) and a.grau in ("🔴", "alto", "manchete"):
        return True, "afirmação de R$ 10 milhões ou mais com ressalva em moldura, hipótese inocente ou padrão de auditoria"
    return (True, "o juiz pediu") if pediu else (False, "")


def cruzar_com_cascata() -> bool:
    """Liga/desliga o braço da cascata (`JFN_JUIZ_CRUZAR=0` desliga). A cascata é a mesma dos produtos da casa;
    são no máximo 12 chamadas curtas por dia. Desligada, o juiz segue só com o Claude da assinatura."""
    return os.environ.get("JFN_JUIZ_CRUZAR", "1").strip().lower() not in ("0", "false", "off", "no")


def julgar(a: Afirmacao, *, pensar: Callable | None = None, cascata: Callable | None = None,
           agora: datetime | None = None) -> Avaliacao:
    """Julga UMA afirmação. `pensar`/`cascata` são injetáveis para teste (nenhum teste chama o Claude de verdade)."""
    from compliance_agent.llm import claude_motor, comotor
    agora = agora or datetime.now()
    pre = v.texto_entregue(a.texto) + v.ausencia_sem_controle(a.texto)
    prompt = montar_prompt(a, pre)
    pensar_cli = partial(pensar or claude_motor.pensar, backend=BACKEND)
    av = Avaliacao(a.id, a.sistema, a.rotulo, a.impressao, agora.isoformat(timespec="seconds"), "PENDENTE", pre_sinais=pre[:12])
    texto_claude = None
    if a.publica and cruzar_com_cascata():
        gerar = comotor.juizo(TAREFA, modelo=claude_motor.MODELO_JUIZO, normalizar=normalizar, pensar=pensar_cli,
                              cascata=cascata, timeout_claude=300.0, conferencia=False)
        try:
            texto = gerar(prompt, sistema=SISTEMA, timeout=90.0, json_saida=True, item=a.id)
        except _FALHAS as e:
            av.juiz = f"indisponível ({type(e).__name__})"
            return av
        ult = comotor.ultima_chamada()
        if str(ult.get("exibido") or "").startswith("claude:"):
            texto_claude, av.juiz = texto, ult["exibido"]
            av.cascata = {"modelo": ult.get("outro"), "divergencia": ult.get("divergencia"), "grave": ult.get("grave")}
        else:                                                    # só a cascata respondeu: preliminar, nunca veredito
            d = _json(texto) or {}
            notas, _ = _limpar_notas(d, a.sistema)
            av.juiz = f"sem Claude ({claude_motor.ultimo_motivo[:60]})"
            av.cascata = {"modelo": ult.get("exibido"), "notas_preliminares": notas}
            return av
    else:
        r = pensar_cli(TAREFA, prompt, modelo=claude_motor.MODELO_JUIZO, sistema=SISTEMA, timeout=300.0)
        if r is None:
            av.juiz = f"sem Claude ({claude_motor.ultimo_motivo[:60]})"
            return av
        texto_claude, av.juiz = r.texto, f"claude:{r.modelo}"
    d = _json(texto_claude)
    if not d:
        av.juiz += " — resposta sem o JSON pedido"
        return av
    return _aplicar(av, a, d)


def _aplicar(av: Avaliacao, a: Afirmacao, d: dict) -> Avaliacao:
    """Notas → veredito e escalada, por código. Sem nota válida, a avaliação fica PENDENTE (nada se inventa)."""
    av.notas, av.motivos = _limpar_notas(d, a.sistema)
    if not av.notas:
        av.juiz += " — resposta sem notas"
        return av
    av.estado = "JULGADA"
    av.veredito = veredito_de(av.notas)
    av.o_que_falta = str(d.get("o_que_falta") or "")[:400]
    av.escalar, av.motivo_escalar = deve_escalar(a, av.notas, bool(d.get("escalar") in (True, "true", "True")))
    if av.cascata.get("grave"):
        av.escalar, av.motivo_escalar = True, (av.motivo_escalar or "Claude e cascata divergem em dois níveis")
    return av


def julgar_lote(lote: list[Afirmacao], *, pensar: Callable | None = None, cascata: Callable | None = None,
                agora: datetime | None = None) -> list[Avaliacao]:
    """Julga um LOTE numa chamada só (mesma rubrica, mesmo canal). Lote de 1 é `julgar`. Item que não volta com o
    seu `id` e notas válidas fica PENDENTE (volta à fila); os outros do lote seguem julgados."""
    if len(lote) == 1:
        return [julgar(lote[0], pensar=pensar, cascata=cascata, agora=agora)]
    from compliance_agent.llm import claude_motor, comotor
    if len({chave_lote(a) for a in lote}) != 1:
        raise ValueError("lote misturando rubricas ou canais (público × interno)")
    agora = agora or datetime.now()
    pres = [v.texto_entregue(a.texto) + v.ausencia_sem_controle(a.texto) for a in lote]
    prompt = montar_prompt_lote(lote, pres)
    prazo = timeout_lote(len(lote))
    pensar_cli = partial(pensar or claude_motor.pensar, backend=BACKEND)
    em = agora.isoformat(timespec="seconds")
    avs = [Avaliacao(a.id, a.sistema, a.rotulo, a.impressao, em, "PENDENTE", pre_sinais=p[:12]) for a, p in zip(lote, pres)]
    info_cascata: dict = {}
    if all(a.publica for a in lote) and cruzar_com_cascata():
        gerar = comotor.juizo(TAREFA, modelo=claude_motor.MODELO_JUIZO, normalizar=normalizar_lote, pensar=pensar_cli,
                              cascata=cascata, timeout_claude=prazo, conferencia=False)
        item = "lote:" + hashlib.sha1("|".join(f"{a.id}@{a.impressao}" for a in lote).encode()).hexdigest()[:16]
        try:
            texto = gerar(prompt, sistema=SISTEMA, timeout=120.0, json_saida=True, item=item)
        except _FALHAS as e:
            for av in avs:
                av.juiz = f"indisponível ({type(e).__name__})"
            return avs
        ult = comotor.ultima_chamada()
        if not str(ult.get("exibido") or "").startswith("claude:"):  # só a cascata respondeu: preliminar, nunca veredito
            for av, a, sub in zip(avs, lote, itens_do_lote(_json(texto), lote)):
                notas, _ = _limpar_notas(sub or {}, a.sistema)
                av.juiz = f"sem Claude ({claude_motor.ultimo_motivo[:60]})"
                av.cascata = {"modelo": ult.get("exibido"), "notas_preliminares": notas, "lote": len(lote)}
            return avs
        texto_claude, quem = texto, ult["exibido"]
        # a divergência medida é a do LOTE (pior veredito × pior veredito): não escala item por item
        info_cascata = {"modelo": ult.get("outro"), "divergencia_lote": ult.get("divergencia"), "grave_lote": ult.get("grave")}
    else:
        r = pensar_cli(TAREFA, prompt, modelo=claude_motor.MODELO_JUIZO, sistema=SISTEMA, timeout=prazo)
        if r is None:
            for av in avs:
                av.juiz = f"sem Claude ({claude_motor.ultimo_motivo[:60]})"
            return avs
        texto_claude, quem = r.texto, f"claude:{r.modelo}"
    d = _json(texto_claude)
    for av, a, sub in zip(avs, lote, itens_do_lote(d, lote)):
        av.juiz, av.cascata = f"{quem} (lote de {len(lote)})", dict(info_cascata)
        if not d:
            av.juiz += " — resposta sem o JSON pedido"
        elif sub is None:
            av.juiz += " — item ausente ou com id trocado na resposta"
        else:
            _aplicar(av, a, sub)
    return avs


# ───────────────────────────── a rodada ─────────────────────────────
def rodar(ctx: sensores.Ctx | None = None, n: int | None = AMOSTRA_PADRAO, *, pensar: Callable | None = None,
          cascata: Callable | None = None, lote: int | None = None, minutos: float | None = None,
          relogio: Callable[[], float] = time.monotonic) -> dict:
    """Uma rodada: monta a fila completa, julga em lotes e grava, A CADA LOTE, `data/qualidade_juiz.json` (fotografia),
    `qualidade_juiz_historico.json` (por afirmação) e `qualidade_juiz_fila.json` (cobertura e pendentes).

    `n` = máximo de afirmações (None = a fila inteira, `--ate-esvaziar`); `minutos` = orçamento de tempo (não se
    começa lote com menos de MIN_SEGUNDOS_LOTE no relógio); `lote` = afirmações por chamada. Para limpo quando o
    Claude da assinatura não responde (teto do motor, contingência, limite de uso): nunca troca de backend.
    Rodada em que o Claude não respondeu NENHUMA não atualiza o carimbo `em` — o sensor de silêncio (CST-15) tem de
    continuar vendo a última rodada que de fato julgou."""
    ctx = ctx or sensores.Ctx()
    with sensores.trava(ctx.dados, "juiz"):
        return _rodar(ctx, n, pensar, cascata, lote or lote_padrao(), minutos, relogio)


def _ler(arq: Path) -> dict:
    return json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}


def _podar(historico: dict, cands: list[Afirmacao]) -> None:
    """Superfície que SAIU (card retirado, achado que a régua não gera mais, caso apagado) perde o juízo vigente —
    19/11/2026: cards retirados por FP medida seguiam como SUB bloqueante para sempre. Só se poda o grupo cuja fonte
    foi lida nesta rodada (fonte que falhou não apaga nota de ninguém); Yoda não se poda (resposta entregue é fato
    consumado)."""
    vivos, lidos = {c.id for c in cands}, {_grupo_poda(c.id) for c in cands}
    for hid in [h for h in historico if _grupo_poda(h) in lidos and h not in vivos]:
        historico[hid]["estado"] = "SUPERFICIE_RETIRADA"


def medir_fila(ctx: sensores.Ctx | None = None, k: int | None = None) -> dict:
    """Só MEDE (sem modelo): recalcula a fila e a cobertura e grava `qualidade_juiz_fila.json`. É o derivado leve
    da propagação (`juiz_fila`): o painel e o sensor veem o que ficou pendente quando o vault ou o painel mudam; o
    julgamento continua nas janelas noturnas. Com a rodada do juiz em curso, não grava (ela grava a cada lote)."""
    ctx = ctx or sensores.Ctx()
    try:
        with sensores.trava(ctx.dados, "juiz", esperar=False):
            arq_f = ctx.dados / "qualidade_juiz_fila.json"
            historico = _ler(ctx.dados / "qualidade_juiz_historico.json")
            cands = candidatas(ctx)
            cob = cobertura(cands, historico, ctx.agora, _ler(arq_f), k) | {"origem": "medicao"}
            gravar_json(arq_f, cob)
            return {"ok": True, "gravado": True} | {x: y for x, y in cob.items() if x not in ("pendentes_desde", "proximas")}
    except BlockingIOError:
        return {"ok": True, "gravado": False, "motivo": "rodada do juiz em curso (ela grava a cobertura a cada lote)"}


_CAMPOS_COBERTURA = ("candidatas", "julgadas_vigentes", "cobertura_pct", "pendentes", "mais_antiga_pendente_em",
                     "mais_antiga_pendente_dias", "a_revalidar", "por_situacao", "por_grupo", "chamadas_para_zerar")


def _rodar(ctx: sensores.Ctx, n: int | None, pensar: Callable | None, cascata: Callable | None, k: int,
           minutos: float | None, relogio: Callable[[], float]) -> dict:
    arq, arq_h, arq_f = (ctx.dados / "qualidade_juiz.json", ctx.dados / "qualidade_juiz_historico.json",
                         ctx.dados / "qualidade_juiz_fila.json")
    historico, anterior, fila_ant = _ler(arq_h), _ler(arq), _ler(arq_f)
    cands = candidatas(ctx)
    _podar(historico, cands)
    ordem = fila(cands, historico, ctx.agora)
    plano = lotes(ordem if n is None else ordem[:max(0, n)], k)
    fim = relogio() + 60.0 * minutos if minutos else None
    feitas: list[Avaliacao] = []
    estado = {"chamadas": 0, "parada": ""}

    def gravar() -> dict:
        julgadas = [x for x in feitas if x.estado == "JULGADA"]
        vigentes = [h for h in historico.values() if h.get("estado") == "JULGADA"]
        todas_notas = [n_ for h in vigentes for n_ in h.get("notas", {}).values()]
        por_crit = {c: _media([h["notas"][c] for h in vigentes if c in h.get("notas", {})]) for c in regras.rubricas()}
        cob = cobertura(cands, historico, ctx.agora, fila_ant, k) | {"origem": "rodada"}
        agora_iso = ctx.agora.isoformat(timespec="seconds")
        resumo = {
            "em": agora_iso if julgadas else anterior.get("em", agora_iso),
            "ultima_tentativa": agora_iso,
            "motivo": "" if julgadas else (feitas[-1].juiz if feitas else "nada novo a julgar"),
            "parada": estado["parada"],
            "amostra": sum(len(x) for x in plano), "lote": k, "lotes_planejados": len(plano), "chamadas": estado["chamadas"],
            "julgadas_nesta_rodada": len(julgadas),
            "pendentes_nesta_rodada": [x.id for x in feitas if x.estado != "JULGADA"],
            "vigentes": len(vigentes), "media": _media(todas_notas), "por_criterio": por_crit,
            "reprovadas": sorted(h["id"] for h in vigentes if h.get("veredito") == "reprovada"),
            "a_escalar": sorted(h["id"] for h in vigentes if h.get("escalar")),
            "avaliacoes": sorted(vigentes, key=lambda h: (min(h.get("notas", {}).values() or [9]), h["id"])),
        } | {c: cob[c] for c in _CAMPOS_COBERTURA}
        if not julgadas and not plano and anterior:
            resumo["em"] = agora_iso                             # nada novo a julgar É rodada concluída
        for caminho, obj in ((arq_h, historico), (arq_f, cob), (arq, resumo)):
            gravar_json(caminho, obj)
        return resumo

    for lt in plano:
        if fim is not None and fim - relogio() < MIN_SEGUNDOS_LOTE:
            estado["parada"] = f"orçamento de tempo ({minutos:g} min) esgotado"
            break
        avs = julgar_lote(lt, pensar=pensar, cascata=cascata, agora=ctx.agora)
        estado["chamadas"] += 1
        feitas.extend(avs)
        for a, av in zip(lt, avs):
            if av.estado != "JULGADA":
                continue
            ant = historico.get(a.id, {})
            piorou = {c: (ant.get("notas", {}).get(c), nota) for c, nota in av.notas.items()
                      if isinstance(ant.get("notas", {}).get(c), (int, float)) and nota < ant["notas"][c]}
            historico[a.id] = asdict(av) | {"piorou": piorou, "reprovada_seguidas":
                                            (ant.get("reprovada_seguidas", 0) + 1) if av.veredito == "reprovada" else 0}
            if historico[a.id]["reprovada_seguidas"] >= 2:
                av.escalar, av.motivo_escalar = True, av.motivo_escalar or "reprovada em duas rodadas seguidas"
                historico[a.id]["escalar"], historico[a.id]["motivo_escalar"] = True, av.motivo_escalar
        sem_claude = next((av.juiz for av in avs if "sem Claude" in av.juiz), "")
        if sem_claude:
            estado["parada"] = sem_claude                        # sem assinatura agora: parar (não insistir, não trocar de backend)
        gravar()                                                 # progresso a cada lote: corte no meio retoma daqui
        if sem_claude:
            break
    return gravar()


def _grupo_poda(aid: str) -> str | None:
    """Grupo de fonte de uma afirmação, para a poda de superfície retirada (None = nunca se poda)."""
    if aid.startswith("painel:gestao:"):
        return "couto"
    if aid.startswith("painel:"):
        return "manchetes"
    if aid.startswith("vault:"):
        return "vault"
    return None


def _media(vals: list) -> float | None:
    return round(sum(vals) / len(vals), 2) if vals else None
