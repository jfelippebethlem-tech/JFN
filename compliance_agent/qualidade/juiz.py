# -*- coding: utf-8 -*-
"""juiz — o juiz subjetivo das regras de qualidade (família SUB), pelo Claude da ASSINATURA.

O que faz: amostra o que o painel, os casos do vault e o Yoda AFIRMAM ao dono, escolhendo por valor e risco, e
dá nota de 0 a 4 em cada critério da rubrica (`config/qualidade_regras.yaml` → `rubricas`): proporção, moldura,
hipótese inocente, padrão de auditoria, jornalista hostil, presunção de inocência, utilidade, clareza,
acabamento. Nota ≤ 1 é violação da regra SUB correspondente (o sensor `juiz_qualidade` abre o item).

REGRAS DESTE MÓDULO (ordem do dono, 13/11/2026: "fable tem que usar assinatura só"):
  · toda chamada ao Claude sai por `claude_motor.pensar(..., backend="cli")` — Claude Code CLI, sem chave no
    ambiente, sem `--bare`. NUNCA o backend automático do motor (cairia na API paga) — há catraca (`test_regra_juiz.py`);
  · se a assinatura não comporta o volume, a amostra ENCOLHE (pelo valor e pelo risco); nunca se troca de backend;
  · co-motor: nas afirmações que já são públicas no painel, a cascata gratuita julga a MESMA entrada em paralelo
    (`comotor.juizo`) e os dois vereditos vão lado a lado para o banco de cruzamento. O veredito da cascata nunca
    abre nem fecha violação sozinho (COR-14): sem o Claude, a avaliação fica `PENDENTE`;
  · material do vault (casos internos) vai SÓ ao Claude da assinatura — não sai para provedor gratuito;
  · CPF é mascarado antes de qualquer envio; nada do que o juiz lê é gravado no registro de uso do motor.

Amostragem: cada candidata tem risco = peso do grau × materialidade do valor. Afirmação já julgada nos últimos
7 dias com o MESMO texto não é rejulgada (o orçamento vai para o que mudou ou nunca foi visto).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Callable

from compliance_agent.qualidade import regras, sensores, verificadores as v

logger = logging.getLogger(__name__)

TAREFA = "juiz_qualidade"
BACKEND = "cli"                     # assinatura. Não mude: a catraca barra.
AMOSTRA_PADRAO = 6
REJULGAR_DIAS = 7
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
def _mascarar(texto: str) -> str:
    texto = re.sub(r"(?<![\d.])\d{3}\.(\d{3})\.(\d{3})-\d{2}(?!\d)", r"***.\1.\2-**", texto or "")
    return re.sub(r"(?i)(\bcpf\b[^\d\n]{0,20})\d{3}(\d{3})(\d{3})\d{2}(?!\d)", r"\1***\2\3**", texto)


def _de_manchetes(ctx: sensores.Ctx) -> list[Afirmacao]:
    out = []
    for m in ctx.manchetes():
        try:
            p = ctx.payload(m["rota"])
        except RuntimeError:
            continue
        nums = sensores._numeros(m, p)
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
    pasta = ctx.vault / "casos"
    out = []
    for arq in sorted(pasta.glob("*.md")) if pasta.is_dir() else []:
        texto = arq.read_text(encoding="utf-8", errors="replace")
        fm = sensores._frontmatter(texto)
        grau = sensores.grau_do_caso(fm)
        if not fm or not sensores._RE_GRAU_ALTO.match(grau) or not sensores.caso_aberto(fm):
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
        textos += [("hermes", t) for t in sensores._textos_yoda(ctx, 40)]
    except _FALHAS:
        pass
    out = []
    for origem, t in textos:
        if "R$" not in t and not re.search(r"🔴|🟡", t):
            continue                                            # só resposta que AFIRMA número ou grau
        vals = [float(x.replace(".", "").replace(",", ".")) for x in re.findall(r"R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2})", t)]
        rotulo, cab = (("resposta do /cc (Claude Code) ao dono", "Resposta enviada ao dono no Telegram (modo /cc):\n")
                       if origem == "cc" else ("resposta do Yoda ao dono", "Resposta enviada pelo assistente no Telegram:\n"))
        a = Afirmacao("", "yoda", rotulo, cab + t[:3500], "🔴" if "🔴" in t else "", max(vals, default=0.0), publica=False)
        a.id = f"yoda:{a.impressao}"
        out.append(a)
    return out[:8]


# Produtos da casa (`reports/`, raiz — `reports/arquivo/` é o acervo podado): relatório de fornecedor e de órgão
# (`inteligencia_*`), parecer Lex (`parecer_lex_*`) e dossiê (`dossie_*`, hoje só PDF — entra se houver .md/.html).
PRODUTO_N = 6
PRODUTO_DIAS = 30
_RE_PRODUTO = re.compile(r"^((?:inteligencia|parecer_lex|dossie)_.+?)_(\d{4}-\d{2}-\d{2})\.(md|html)$")
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
        vals = [float(x.replace(".", "").replace(",", ".")) for x in re.findall(r"R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2})", trecho)]
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
        a.texto = _mascarar(a.texto)
    return out


def amostrar(cands: list[Afirmacao], historico: dict, n: int, agora: datetime) -> list[Afirmacao]:
    """Por risco, pulando o que já foi julgado com o mesmo texto há menos de 7 dias; a amostra é repartida entre
    os grupos presentes (cockpit, análise de gestão, vault, Yoda) — senão os itens de maior valor de UMA superfície
    comeriam o juízo sobre as outras."""
    limite = (agora - timedelta(days=REJULGAR_DIAS)).isoformat()
    novos = [a for a in cands if not (historico.get(a.id, {}).get("impressao") == a.impressao
                                      and historico.get(a.id, {}).get("em", "") >= limite
                                      and historico.get(a.id, {}).get("estado") == "JULGADA")]
    # correção à espera de confirmação primeiro: afirmação com nota ≤ 1 vigente cujo texto MUDOU (19/11/2026: as
    # notas 1 corrigidas ficavam atrás de dezenas de casos novos de maior valor e a violação não saía)
    def _corrigida(a: Afirmacao) -> bool:
        h = historico.get(a.id) or {}
        return h.get("estado") == "JULGADA" and any(isinstance(x, (int, float)) and x <= 1 for x in (h.get("notas") or {}).values())
    novos.sort(key=lambda a: (not _corrigida(a), -a.risco))
    corrigidas = [a for a in novos if _corrigida(a)][:n]
    escolhidas, por_grupo = list(corrigidas), {}
    for a in corrigidas:
        por_grupo[a.grupo] = por_grupo.get(a.grupo, 0) + 1
    grupos = {a.grupo for a in novos}
    teto = max(1, math.ceil(n / max(1, len(grupos))))
    for a in novos:
        if len(escolhidas) >= n:
            break
        if a in escolhidas or por_grupo.get(a.grupo, 0) >= teto:
            continue
        # vaga reservada: o 2º item de um grupo não toma a vaga de grupo ainda sem nenhum (20/11/2026: com 5 grupos
        # e n=6, 2+2+2 dos grupos de maior valor enchia a amostra e Yoda/produto nunca eram julgados)
        if por_grupo.get(a.grupo) and n - len(escolhidas) <= len(grupos - set(por_grupo)):
            continue
        escolhidas.append(a)
        por_grupo[a.grupo] = por_grupo.get(a.grupo, 0) + 1
    for a in novos:                                              # sobra orçamento? completa sem o teto por sistema
        if len(escolhidas) >= n:
            break
        if a not in escolhidas:
            escolhidas.append(a)
    return escolhidas


# ───────────────────────────── o pedido ao juiz ─────────────────────────────
def criterios_de(sistema: str) -> list[str]:
    """Os critérios da rubrica cuja regra SUB se aplica ao sistema (acabamento de entregável não se cobra de um
    card; o juiz não dá nota no que não vale ali)."""
    por_id = regras.por_id()
    return [c for c, r in regras.rubricas().items() if sistema in por_id[r["regra"]].aplica]


def montar_prompt(a: Afirmacao, pre: list[str]) -> str:
    d = regras.bruto()
    crit = criterios_de(a.sistema)
    linhas = ["RUBRICA — dê nota de 0 a 4 em cada critério (use null só se o critério realmente não se aplica):"]
    for nota, desc in d["escala"].items():
        linhas.append(f"  {nota} = {desc}")
    for nome, r in d["rubricas"].items():
        if nome not in crit:
            continue
        linhas.append(f"\n[{nome}] {r['pergunta']}\n  exemplo RUIM: {r['ancora_ruim'].strip()}\n  exemplo BOM: {r['ancora_boa'].strip()}")
    linhas.append("\nESCALAR AO DONO (humano) quando: " + " | ".join(d["escalar_humano"]))
    linhas.append("\nPRÉ-SINAIS do verificador automático (determinístico; pode haver falso positivo — julgue você):\n"
                  + ("\n".join(f"  - {p}" for p in pre[:12]) if pre else "  (nenhum)"))
    linhas.append("\nCOMO LER A ENTRADA: ela foi extraída por código da tela ou do arquivo e pode chegar como campos "
                  "estruturados (JSON). NÃO julgue o formato da extração, nomes de campo nem termos internos desta ficha "
                  "(\"card\", \"cockpit\", \"chip\", códigos de regra): julgue o CONTEÚDO que o dono lê — rótulo, número, "
                  "ressalvas e o que falta. Se a entrada não traz proveniência, isso é fato a pesar (a tela não a mostra).")
    linhas.append(f"\nAFIRMAÇÃO A JULGAR (origem: {a.sistema}; grau exibido: {a.grau or 'não informado'}):\n«««\n{a.texto}\n»»»")
    linhas.append("\nPara cada nota ≤ 2, diga em uma frase o que está errado e o que tornaria a afirmação aceitável. "
                  "`veredito`: aprovada (todas ≥ 3) · ressalva (alguma = 2, nenhuma ≤ 1) · reprovada (alguma ≤ 1).")
    # o formato vai NO PROMPT (e não pelo `schema` do motor): a cascata recebe o mesmo texto e precisa dele também
    linhas.append("\nResponda SOMENTE com um objeto JSON válido, sem texto fora dele, neste formato:\n"
                  + json.dumps(esquema(a.sistema), ensure_ascii=False))
    return "\n".join(linhas)


def esquema(sistema: str | None = None) -> dict:
    crit = criterios_de(sistema) if sistema else list(regras.rubricas())
    return {"notas": {c: "0-4 ou null" for c in crit}, "motivos": {c: "frase curta (obrigatória se nota ≤ 2)" for c in crit},
            "veredito": "aprovada|ressalva|reprovada", "o_que_falta": "documento ou ajuste que resolve",
            "escalar": "true|false", "motivo_escalar": "se escalar"}


def normalizar(txt: str):
    """Para o cruzamento com a cascata: aprovada 0 · ressalva 1 · reprovada 2."""
    d = _json(txt) or {}
    ver = str(d.get("veredito") or "").strip().lower()
    return (ver or None), {"aprovada": 0, "ressalva": 1, "reprovada": 2}.get(ver), None


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


# ───────────────────────────── a rodada ─────────────────────────────
def rodar(ctx: sensores.Ctx | None = None, n: int = AMOSTRA_PADRAO, *, pensar: Callable | None = None,
          cascata: Callable | None = None) -> dict:
    """Uma rodada: amostra, julga, grava `data/qualidade_juiz.json` (a última) e `qualidade_juiz_historico.json`
    (por afirmação). Rodada em que o Claude não respondeu NENHUMA não atualiza o carimbo `em` — o sensor de
    silêncio (CST-15) tem de continuar vendo a última rodada que de fato julgou."""
    ctx = ctx or sensores.Ctx()
    with sensores.trava(ctx.dados, "juiz"):
        return _rodar(ctx, n, pensar, cascata)


def _rodar(ctx: sensores.Ctx, n: int, pensar: Callable | None, cascata: Callable | None) -> dict:
    arq, arq_h = ctx.dados / "qualidade_juiz.json", ctx.dados / "qualidade_juiz_historico.json"
    historico = json.loads(arq_h.read_text(encoding="utf-8")) if arq_h.exists() else {}
    anterior = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    cands = candidatas(ctx)
    escolhidas = amostrar(cands, historico, n, ctx.agora)
    feitas = []
    for a in escolhidas:
        av = julgar(a, pensar=pensar, cascata=cascata, agora=ctx.agora)
        feitas.append(av)
        ant = historico.get(a.id, {})
        if av.estado == "JULGADA":
            piorou = {c: (ant.get("notas", {}).get(c), nota) for c, nota in av.notas.items()
                      if isinstance(ant.get("notas", {}).get(c), (int, float)) and nota < ant["notas"][c]}
            historico[a.id] = asdict(av) | {"piorou": piorou, "reprovada_seguidas":
                                            (ant.get("reprovada_seguidas", 0) + 1) if av.veredito == "reprovada" else 0}
            if historico[a.id]["reprovada_seguidas"] >= 2:
                av.escalar, av.motivo_escalar = True, av.motivo_escalar or "reprovada em duas rodadas seguidas"
                historico[a.id]["escalar"], historico[a.id]["motivo_escalar"] = True, av.motivo_escalar
        elif "sem Claude" in av.juiz:
            break                                                # sem assinatura agora: parar (não insistir, não trocar de backend)
    julgadas = [asdict(x) for x in feitas if x.estado == "JULGADA"]
    # a fotografia traz TODAS as afirmações com juízo vigente (não só as desta rodada): o sensor lê daqui.
    # Superfície que SAIU (card retirado, achado que a régua não gera mais, caso apagado) não tem juízo vigente —
    # 19/11/2026: cards retirados por FP medida seguiam como SUB bloqueante para sempre. Só se poda o grupo cuja
    # fonte foi lida nesta rodada (fonte que falhou não apaga nota de ninguém); Yoda não se poda (resposta entregue
    # é fato consumado).
    vivos, lidos = {c.id for c in cands}, {_grupo_poda(c.id) for c in cands}
    for hid in [h for h in historico if _grupo_poda(h) in lidos and h not in vivos]:
        historico[hid]["estado"] = "SUPERFICIE_RETIRADA"
    vigentes = [h for h in historico.values() if h.get("estado") == "JULGADA"]
    todas_notas = [n_ for h in vigentes for n_ in h.get("notas", {}).values()]
    por_crit = {c: _media([h["notas"][c] for h in vigentes if c in h.get("notas", {})]) for c in regras.rubricas()}
    resumo = {
        "em": ctx.agora.isoformat(timespec="seconds") if julgadas else anterior.get("em", ctx.agora.isoformat(timespec="seconds")),
        "ultima_tentativa": ctx.agora.isoformat(timespec="seconds"),
        "motivo": "" if julgadas else (feitas[-1].juiz if feitas else "nada novo a julgar"),
        "candidatas": len(cands), "amostra": len(escolhidas), "julgadas_nesta_rodada": len(julgadas),
        "pendentes_nesta_rodada": [x.id for x in feitas if x.estado != "JULGADA"],
        "vigentes": len(vigentes), "media": _media(todas_notas), "por_criterio": por_crit,
        "reprovadas": sorted(h["id"] for h in vigentes if h.get("veredito") == "reprovada"),
        "a_escalar": sorted(h["id"] for h in vigentes if h.get("escalar")),
        "avaliacoes": sorted(vigentes, key=lambda h: (min(h.get("notas", {}).values() or [9]), h["id"])),
    }
    if not julgadas and not feitas and anterior:
        resumo["em"] = ctx.agora.isoformat(timespec="seconds")   # nada novo a julgar É rodada concluída
    ctx.dados.mkdir(parents=True, exist_ok=True)
    for caminho, obj in ((arq_h, historico), (arq, resumo)):
        tmp = caminho.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(caminho)
    return resumo


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
