#!/usr/bin/env python3
"""
SWEEP do SEI — lê os processos das OBs **um a um**, com LOGIN ÚNICO (itkava) e sessão reusada.

Confirmado ao vivo (2026-06-09): o reader lê processo a processo (ex.: SEI-330003/002534/2024 → 10 docs).
O `ler()` faz login a cada chamada (~49s); aqui logamos UMA vez e iteramos `ler_processo` (~15s/processo).

Honesto e seguro:
  - Prioriza por VALOR (maior exposição primeiro); pula o que já está em cache (<24h).
  - Fora do escopo do itkava (0 docs) é registrado e seguimos — não martela.
  - Resumível (checkpoint `data/sei_cache/sei_sweep_progress.json`).
  - Respeita a pausa do SIAFE (`data/.pause_sweep_2`) e o browser_lock (nunca 2 browsers).
  - Para sozinho se o login cair (WAF) ou ao atingir --max.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.sei_sweep --max 50          # lê até 50 processos novos
    PYTHONPATH=. .venv/bin/python -m tools.sei_sweep --max 50 --ug 133100   # só processos de OBs de uma UG
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import signal
from functools import lru_cache
import sqlite3
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "compliance.db"
CACHE = REPO / "data" / "sei_cache"
PROG = CACHE / "sei_sweep_progress.json"
PAUSE = REPO / "data" / ".pause_sei_sweep"  # pausa PRÓPRIA (o browser_lock já serializa com o SIAFE)
LOG = REPO / "data" / "sei_sweep.log"


def _log(m: str):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {m}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


# ENCERRAMENTO GRACIOSO: o orquestrador (`sweep_sei.sh`) embrulha o sweep em `timeout 1500`. Sem tratar o
# SIGTERM, o `timeout` mata o processo no meio → o browser é morto à força → Node emite EPIPE (parece crash).
# Aqui o SIGTERM só LEVANTA UMA FLAG; o loop a checa entre processos e sai LIMPO (fecha o browser no finally),
# terminando o processo em curso. `timeout` (sem --kill-after) não força SIGKILL, então há tempo de fechar.
_PARAR = False


def _pedir_parada(signum, _frame):  # noqa: ANN001
    global _PARAR
    _PARAR = True


# Assinaturas de MORTE de browser/pipe (Playwright/Chromium): quando aparecem, a sessão inteira está perdida —
# não adianta seguir varrendo (toda leitura seguinte falha). Tratamos como saída limpa (cron repete), nunca crash.
_SINAIS_BROWSER_MORTO = (
    "epipe", "targetclosed", "target closed", "target page, context or browser has been closed",
    "browser has been closed", "connection closed", "browser closed", "page closed",
    "websocket", "pipe closed", "transport", "broken pipe", "playwright was closed",
)


def _browser_morto(exc: BaseException) -> bool:
    """True se a exceção indica que o BROWSER/pipe caiu (não um erro pontual de um processo). Usado para abortar
    a sessão de forma LIMPA em vez de insistir 20× num browser morto. Conservador: na dúvida, retorna False
    (segue para o próximo processo) — só corta a sessão quando a assinatura é claramente de morte de browser."""
    nome = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "targetclosed" in nome or "browser" in nome and "closed" in nome:
        return True
    return any(s in msg for s in _SINAIS_BROWSER_MORTO)


# ── O CONTEXTO DO NAVEGADOR É UM SÓ, e isso não é preferência de estilo ───────────────────────
# Medido em 2026-08-07: dos três caminhos que fazem login no SEI aqui, dois montavam o contexto com
# `user_agent` de desktop e o terceiro — a RECAPTURA — não. Resultado no log: **16 slots de
# recaptura, 16 abortos, ZERO documento recuperado**, sempre com a mesma mensagem de "login não
# completou em 20 tentativas". A mensagem levantava a hipótese de sessão anterior deixada aberta;
# ninguém a conferiu, e a diferença real era o navegador se apresentando como HeadlessChrome.
#
# Pior que o defeito era a forma dele: o passo RODAVA, escrevia no log e não entregava nada — a
# aparência de funcionamento. Três cópias de uma configuração é convite para a quarta divergir, por
# isso a montagem passa a ser uma só. Quem precisar mudar o UA muda aqui, para os três.
class FalhaDeclarada(Exception):
    """Falha JÁ diagnosticada e logada — o que falta é o código de saída dizer o mesmo.

    TIPO PRÓPRIO, e não `RuntimeError`, porque `RuntimeError` é o que um crash genérico levanta:
    a catraca `test_main_engole_excecao_de_run` simula justamente "write EPIPE — browser morreu no
    meio" com um `RuntimeError`, e usá-lo como sinal misturaria as duas coisas — um crash de
    verdade sairia com a mensagem de falha esperada, sem o aviso de "erro não previsto" que manda
    alguém olhar. Ela pegou isso na primeira tentativa desta mudança.
    """


_UA_DESKTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


async def _contexto_sei(b):
    """O contexto que o SEI aceita — mesmo UA para os três caminhos de login."""
    return await b.new_context(ignore_https_errors=True, locale="pt-BR", user_agent=_UA_DESKTOP)


def na_minha_fatia(processo: str, indice: int, total: int) -> bool:
    """Este processo pertence à fatia `indice` de `total`? Determinístico e sem coordenação.

    Duas máquinas capturando o SEI puxam a mesma fila, na mesma ordem, e começariam pelo mesmo
    processo — dobrando browser e sessão para entregar metade. O `pgrep` do `sweep_sei.sh`
    protege contra dois sweeps na MESMA máquina; entre máquinas não havia nada.

    A divisão é pelo hash do número: sem lock distribuído, sem heartbeat, sem uma máquina
    precisar saber que a outra existe. Duas máquinas offline uma para a outra não colidem.

    Configuração errada levanta em vez de cair no padrão: uma fatia inválida em silêncio faria
    a máquina varrer o vazio por dias, ou as duas varrerem tudo, que é o defeito original.
    """
    import hashlib

    if total < 1 or not (0 <= indice < total):
        raise ValueError(f"fatia inválida: {indice}/{total} (exige 0 <= índice < total, total >= 1)")
    if total == 1:
        return True
    digest = hashlib.sha256(str(processo or "").encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % total == indice


def fatia_desta_maquina() -> tuple[int, int]:
    """`JFN_SWEEP_FATIA=1/2` → `(1, 2)`. Sem a variável, máquina única `(0, 1)`."""
    bruto = (os.environ.get("JFN_SWEEP_FATIA") or "").strip()
    if not bruto:
        return 0, 1
    try:
        indice, total = (int(x) for x in bruto.split("/", 1))
    except ValueError as e:
        raise ValueError(f"JFN_SWEEP_FATIA malformada: {bruto!r} — use 'indice/total', ex. 1/2") from e
    na_minha_fatia("teste", indice, total)   # valida os limites, levantando se inválido
    return indice, total


def _carregar_prog() -> dict:
    if PROG.exists():
        try:
            return json.loads(PROG.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("checkpoint %s ilegível — sweep recomeça do zero: %s", PROG.name, exc)
    return {"feitos": {}}  # proc -> {n_docs, em}


def _salvar_prog(p: dict):
    PROG.parent.mkdir(parents=True, exist_ok=True)
    # MERGE-ON-SAVE + write ATÔMICO (fix 2026-07-10): instâncias sobrepostas (cron chains) faziam
    # load-modify-save do arquivo INTEIRO — a última a salvar apagava os feitos das outras (274
    # leituras de 07-09/10 sumiram assim), e um read no meio de um write parcial caía no
    # "ilegível → recomeça do zero". Merge: o nosso (mais novo) prevalece; o do disco completa.
    try:
        no_disco = json.loads(PROG.read_text(encoding="utf-8")).get("feitos", {})
    except Exception:
        no_disco = {}
    fe = p.setdefault("feitos", {})
    for k, v in no_disco.items():
        fe.setdefault(k, v)
    tmp = PROG.with_name(f"{PROG.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(PROG)


def _unidades_legiveis() -> set[str]:
    """Unidades SEI que o itkava JÁ leu (cache cdp_*.json com documentos>0) — escopo aprendido.
    Ex.: de 'cdp_SEI_330003_002534_2024.json' (10 docs) extrai a unidade '330003'."""
    uni: set[str] = set()
    for cf in CACHE.glob("cdp_SEI_*.json"):
        try:
            d = json.loads(cf.read_text(encoding="utf-8"))
            if len(d.get("documentos") or []) > 0:
                m = re.search(r"cdp_SEI_(\d{6})_", cf.name)
                if m:
                    uni.add(m.group(1))
        except Exception as exc:
            logger.debug("cache %s ilegível ao mapear unidades: %s", cf.name, exc)
    return uni


def _unidade(proc: str) -> str:
    m = re.match(r"SEI-\s*(\d{6})", proc or "")  # tolera 'SEI- 330003' (espaço) e 'SEI-080002'
    return m.group(1) if m else ""


def _unidades_sem_acesso(prog: dict, min_amostra: int = 6) -> set:
    """Unidades APRENDIDAS como fora do acesso do itkava: >= min_amostra processos tentados e TODOS com
    0 docs → o login não enxerga aquela unidade (INDISPONÍVEL por acesso). Pular o resto dela evita
    milhares de tentativas fúteis. Honesto: é falta de ACESSO, não 'sem processo'."""
    from collections import defaultdict
    tot: dict = defaultdict(int)
    zero: dict = defaultdict(int)
    for p, f in (prog.get("feitos") or {}).items():
        u = _unidade(p)
        if not u:
            continue
        tot[u] += 1
        if (f.get("n_docs", 0) or 0) == 0:
            zero[u] += 1
    return {u for u in tot if tot[u] >= min_amostra and zero[u] == tot[u]}


def _fila(ug: str | None, limite: int, cnpj: str | None = None) -> list[tuple]:
    """Processos SEI distintos das OBs, priorizando as UNIDADES que o itkava já leu (escopo
    aprendido), depois por valor desc. Filtra por UG e/ou CNPJ do favorecido (alvo de um relatório)."""
    con = sqlite3.connect(str(DB))
    where = "numero_sei LIKE 'SEI-%/%/20%'"
    args: list = []
    if ug:
        where += " AND ug_codigo=?"
        args.append(ug)
    if cnpj:  # processos das OBs de UM fornecedor — pré-carrega o SEI antes do /relatorio dele
        where += " AND replace(replace(replace(favorecido_cpf,'.',''),'/',''),'-','')=?"
        args.append(re.sub(r"\D", "", cnpj))
    # TODOS os processos distintos das OBs (universo ~49k) — sem teto: o sweep deve estudar TODOS os
    # processos de TODAS as OBs (pedido do dono). O `run` filtra os já feitos e pega o próximo lote;
    # o skip-após-3-tentativas trata os fora-de-escopo (acesso do itkava) sem martelar. Ordena: unidade
    # LEGÍVEL primeiro (rende docs), depois por valor — o trabalho útil sai antes; o resto marcha depois.
    # FONTE = SIAFE, não o espelho TFE. Medido em 2026-07-28: o universo do espelho tem 22.016
    # processos e o do SIAFE tem 41.740 — com o TFE INTEIRAMENTE CONTIDO no SIAFE. O sweep
    # estava cego para 19.724 processos (+90%), e o log dizia "nada novo na fila" enquanto
    # metade do acervo nunca fora oferecida a ele. É a regra da casa aplicada onde faltava:
    # OB/pagamento vem do SIAFE, nunca do espelho.
    where_siafe = where.replace("numero_sei", "processo").replace("ug_codigo", "ug_emitente")
    where_siafe = where_siafe.replace(
        "replace(replace(replace(favorecido_cpf,'.',''),'/',''),'-','')", "credor")
    rows = con.execute(
        f"SELECT processo, COUNT(*) nob, ROUND(SUM(valor),2) tot FROM ob_orcamentaria_siafe "
        f"WHERE {where_siafe} GROUP BY processo ORDER BY tot DESC",
        tuple(args),
    ).fetchall()
    sinal = _raizes_com_sinal_osint()
    credores = _credores_por_processo(con) if sinal else {}
    provados = _fila_com_lacuna_provada(con)
    folha = _processos_de_folha(con)
    con.close()
    legiveis = _unidades_legiveis()
    # ORDEM: unidade que rende documentos primeiro; depois o que o PARECER PROVA que falta (não há
    # hipótese aqui — o documento existe e nós não o temos); depois o que a inteligência marcou; e
    # só então o valor. Valor não é risco: é o tamanho do risco quando ele existe.
    def _norm_proc(x):
        return re.sub(r"\D", "", str(x))

    provados_norm = {_norm_proc(x) for x in provados}
    rows.sort(key=lambda r: (0 if _unidade(r[0]) in legiveis else 1,
                             0 if _norm_proc(r[0]) in provados_norm else 1,
                             0 if (credores.get(r[0]) or set()) & sinal else 1,
                             # FOLHA/PREVIDÊNCIA por último dentro do estrato: 82% do top-50 por
                             # valor era folha, e o browser é o recurso mais escasso da casa.
                             1 if r[0] in folha else 0,
                             -(r[2] or 0)))
    n_prov = sum(1 for r in rows if _norm_proc(r[0]) in provados_norm)
    n_pri = sum(1 for r in rows if (credores.get(r[0]) or set()) & sinal) if sinal else 0
    n_folha = sum(1 for r in rows if r[0] in folha)
    if n_prov or n_pri:
        _log(f"fila: {n_prov} com lacuna PROVADA pelo parecer e {n_pri} com sinal OSINT no credor "
             f"entram na frente (de {len(rows)}); ordem = legível > lacuna provada > sinal > "
             f"fornecedor antes de folha > valor")
    if n_folha:
        _log(f"fila: {n_folha} processos são de FOLHA/PREVIDÊNCIA (credor genérico) e foram "
             f"rebaixados dentro do próprio estrato — rebaixados, não excluídos.")
    # FATIA da máquina: com duas capturando, cada uma fica com metade determinística do
    # universo. Sem isto as duas começam pelo mesmo processo (mesma fila, mesma ordem) e
    # gastam o dobro de browser para entregar a mesma coisa. Ver `na_minha_fatia`.
    indice, total = fatia_desta_maquina()
    if total > 1:
        antes = len(rows)
        rows = [r for r in rows if na_minha_fatia(r[0], indice, total)]
        _log(f"fatia {indice}/{total}: {len(rows)} de {antes} processos são desta máquina")
    return rows


def _fila_com_lacuna_provada(con) -> set[str]:
    """Processos que o PRÓPRIO PARECER prova estarem incompletos na nossa captura.

    `sei_fila_captura` era escrita por `fila_recaptura_por_parecer` e **lida por ninguém** — só um
    relatório a consultava. Os 380 processos gravados em 2026-08-07, com a lista dos documentos que
    o parecer cita e a nossa pasta não tem, nunca voltavam para captura: a fila era um beco.

    Isto é a prioridade MAIS ALTA da fila, acima do sinal OSINT, e a razão é simples: aqui não há
    hipótese. O documento existe (o parecer o cita), nós não o temos, e a falta já rebaixou cinco
    acusações de "pagamento sem prova de entrega" para INDISPONÍVEL. Recapturar converte uma
    ressalva em resposta.
    """
    try:
        return {str(r[0]) for r in con.execute("SELECT numero_sei FROM sei_fila_captura")}
    except sqlite3.Error:
        return set()


def _raizes_com_sinal_osint() -> set[str]:
    """Raízes de CNPJ que a fila curada de agente público já marcou — a inteligência que temos.

    POR QUE A CAPTURA PRECISA DISSO. O universo do SIAFE tem 45.634 processos e a casa capturou
    2.182 (4,8%); a ~16 processos por dia, ler tudo levaria SETE ANOS. A fila já ordenava por
    VALOR, e valor não é risco: um pagamento grande e limpo entra antes de um pequeno com agente
    público no quadro societário da contratada.

    Medido em 2026-08-06: dos 44.072 processos ainda não capturados, **632** têm credor na fila
    curada de `agente_publico_reverso` (307 raízes, já sem homônimo comprovado e sem o que é
    desenho de programa). São 1,4% do universo — quarenta dias de captura em vez de sete anos.

    Degrada em silêncio de propósito: sem o arquivo, devolve vazio e a ordem volta a ser a antiga.
    Prioridade que quebra a captura seria pior que prioridade nenhuma.
    """
    alvo = Path(__file__).resolve().parent.parent / "data" / "agente_publico_fila.json"
    if not alvo.exists():
        return set()
    try:
        corpo = json.loads(alvo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {x["cnpj_basico"] for x in corpo.get("itens", [])
            if not x.get("explicacao_institucional")}


def _processos_de_folha(con) -> set[str]:
    """Processos cujo dinheiro é FOLHA/PREVIDÊNCIA, não pagamento a fornecedor.

    A fila termina em `-valor`, e a casa já escreveu que "valor não é risco". O que faltava era
    notar o que o valor bruto de fato ranqueia. Quem encabeça é `CG0004700` (**FOLHA DE
    PAGAMENTOS**), `123400`/`123499` (RIOPREV e plano previdenciário) e `CG0006026`
    (RIOPREV/INATIVOS) — credor GENÉRICO, que não tem CNPJ nem CPF.

    MEDIDO NA FILA REAL, por estrato (2026-08-11) — e a medição corrige a primeira versão desta
    nota, que citava o ranking por valor PURO (82% do top-50) e teria exagerado o efeito:

        estrato                                    processos   folha no seu top-50
        legível + lacuna provada                       2.346          0
        legível + sinal OSINT no credor                2.346         22
        legível, sem sinal (o estrato de trabalho)    77.748         30
        não legível, sem sinal                        38.423         48

    Ou seja: na cabeça de HOJE não muda nada — os estratos de lacuna provada e OSINT ocupam as
    primeiras vagas e são de fornecedor. O desperdício está no estrato onde o sweep passa a vida,
    e no estrato do próprio sinal OSINT, onde 22 das 50 primeiras vagas iam para a folha.

    O sweep lê ~16 processos por dia com browser. Mandar as primeiras vagas para a folha é gastar
    o recurso mais escasso da casa no que os detectores de licitação e contrato nem examinam.

    REBAIXAR, NÃO EXCLUIR, e dentro do mesmo estrato: folha tem irregularidade própria (a casa já
    faz perícia de benefício×vínculo) e segue alcançável. O que não pode é ela chegar na frente do
    fornecedor por um critério que não mede risco.

    A RÉGUA MORA EM `compliance_agent/credor_generico`, não aqui: o painel publica a mesma
    separação (quanto da exposição é fornecedor, quanto é folha) e duas cópias do mesmo critério
    divergem — foi o que aconteceu com o teto do art. 125, que chegou a cinco cópias com valores
    diferentes dentro de detectores de risco alto.
    """
    from compliance_agent.credor_generico import processos_de_folha
    return processos_de_folha(con)


def _credores_por_processo(con) -> dict[str, set[str]]:
    """Raiz do credor de cada processo, pelas OBs do SIAFE."""
    fora: dict[str, set[str]] = {}
    for proc, doc in con.execute(
            "SELECT processo, credor FROM ob_orcamentaria_siafe WHERE processo IS NOT NULL"):
        d = re.sub(r"\D", "", str(doc or ""))
        if len(d) == 14:
            fora.setdefault(str(proc), set()).add(d[:8])
    return fora


def _arvores_encerradas() -> set[str]:
    """Conjunto de processos com situação AUTORITATIVA de encerramento (`sei_arvore.encerrado=1`) — o gate
    FIRME de skip da fase 'update diário'. O flag `encerrado` já embute as salvaguardas (autoritativo
    arquivado/concluído + sem OB recente + sem aditivo + sem filho vigente, em sei_arvore_build); aqui
    re-checamos a recência da última OB como cinto-e-suspensório contra build defasado. Honesto: na dúvida
    (sem DB, sem tabela, sem coluna, erro) retorna VAZIO → não pula nada. Só é chamado em --diario."""
    if not DB.exists():
        return set()
    con = sqlite3.connect(str(DB))
    try:
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sei_arvore'").fetchone():
            return set()
        cols = {r[1] for r in con.execute("PRAGMA table_info(sei_arvore)")}
        if "encerrado" not in cols:
            return set()
        rows = con.execute(
            "SELECT numero_sei, COALESCE(ultima_ob,'') FROM sei_arvore WHERE encerrado=1").fetchall()
    except sqlite3.Error:
        return set()
    finally:
        con.close()
    hoje = datetime.now().date()
    out: set[str] = set()
    for numero, ult in rows:
        if not numero:
            continue
        if ult:  # defesa extra: última OB recente (≤18m) → NÃO pula, mesmo marcado encerrado
            try:
                if (hoje - datetime.fromisoformat(ult[:10]).date()).days <= 548:
                    continue
            except ValueError as exc:
                logger.debug("ultima_ob de %s não parseia (%r): %s", numero, ult, exc)
        out.add(numero)
    return out


def _iso(d: str) -> str:
    """Normaliza data p/ ISO YYYY-MM-DD. Aceita ISO (TFE) e dd/mm/yyyy (SIAFE). '' se não reconhecer."""
    d = (d or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", d):
        return d[:10]
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def _ultima_ob_por_processo() -> dict:
    """Data (ISO) da OB MAIS RECENTE de cada processo SEI, cruzando as DUAS fontes (TFE + SIAFE 1/2).
    FRESCOR POR OB (pedido do dono 2026-07-03): uma OB nova = o processo SEI andou (novo pagamento/etapa)
    → tem de ser re-lido, senão a perícia roda com pagamentos/docs INCOMPLETOS. Honesto: sem DB → {}."""
    if not DB.exists():
        return {}
    out: dict[str, str] = {}
    con = sqlite3.connect(str(DB))
    try:
        # TFE (ordens_bancarias): datas já ISO
        for proc, dt in con.execute(
            "SELECT numero_sei, MAX(COALESCE(data_pagamento, data_emissao)) FROM ordens_bancarias "
            "WHERE numero_sei LIKE 'SEI-%/%/20%' GROUP BY numero_sei"):
            if proc and dt:
                out[proc] = max(out.get(proc, ""), dt[:10])
        # SIAFE (ob_orcamentaria_siafe): data dd/mm/yyyy → reduz em Python (não ordena lexicalmente)
        for proc, dt in con.execute(
            "SELECT processo, data_emissao FROM ob_orcamentaria_siafe WHERE processo LIKE 'SEI-%/%/20%'"):
            iso = _iso(dt)
            if proc and iso:
                out[proc] = max(out.get(proc, ""), iso)
    except sqlite3.Error as exc:
        logger.warning("query de última OB por processo falhou — frescor por OB incompleto: %s", exc)
    finally:
        con.close()
    return out


def _ob_desatualizada(ult_ob_iso: str, lido_em: str) -> bool:
    """True se há OB (ISO) mais NOVA que a última leitura (checkpoint 'em') → processo andou → re-ler."""
    return bool(ult_ob_iso and lido_em and ult_ob_iso > lido_em[:10])


def _falha_recente(f: dict | None, horas: float = 4.0) -> bool:
    """COOLOFF de janela (fix constância 2026-07-03): última tentativa FALHOU (0 docs) há menos de `horas`
    → não re-tentar na MESMA janela de WAF. Sem isto, as 3 tentativas caem numa única hora ruim e o
    processo estaciona injustamente (caso 120228: 3 tentativas em 55min de 28/06 → preso 5 dias)."""
    if not f or (f.get("n_docs", 0) or 0) > 0 or not f.get("em"):
        return False
    try:
        return (datetime.now() - datetime.fromisoformat(f["em"])).total_seconds() < horas * 3600
    except (ValueError, TypeError):
        return False


def _ja_lido_ok(proc: str) -> bool:
    """True só se o processo já foi lido COM SUCESSO (documentos>0) e fresco (<7d). Um cache de 0 docs
    é leitura intermitente que FALHOU — não pular, retentar (a abertura do SEI é flaky)."""
    cf = CACHE / f"cdp_{re.sub(r'[^0-9A-Za-z]', '_', proc)}.json"
    if not cf.exists():
        return False
    try:
        c = json.loads(cf.read_text(encoding="utf-8"))
        if len(c.get("documentos") or []) > 0 and c.get("_cached_at"):
            return (datetime.now() - datetime.fromisoformat(c["_cached_at"])).total_seconds() < 7 * 86400
    except Exception as exc:
        logger.debug("cache de %s ilegível em _ja_lido_ok — vai re-ler: %s", proc, exc)
    return False


_DIAS_PARA_NOVA_CHANCE = int(os.environ.get("SEI_SWEEP_DIAS_RETENTAR", "14"))


def _tentativa_expirou(em: str | None) -> bool:
    """Faz mais de `_DIAS_PARA_NOVA_CHANCE` que a última tentativa falhou?

    Sem data registrada NÃO expira: na dúvida, mantém o comportamento antigo — a guarda existe
    para não martelar, e afrouxá-la por ausência de dado seria o oposto do que a casa faz.
    """
    if not em:
        return False
    try:
        return (datetime.now() - datetime.fromisoformat(str(em))).days >= _DIAS_PARA_NOVA_CHANCE
    except (TypeError, ValueError):
        return False


_DIAS_RECONFERIR_RESTRITO = int(os.environ.get("SEI_SWEEP_DIAS_RESTRITO", "90"))


@lru_cache(maxsize=1)
def _registro_restritos() -> dict:
    """O controle de restritos, lido UMA vez por execução do sweep.

    São 419 KB: reparsear por processo custava 4,5 ms, ~9,5 s por passada e ~95 s por ciclo do
    cron numa VM de 2 vCPU. A fila é montada inteira antes do laço de leitura, e quem escreve no
    registro é o `sei_restritos.registrar`, depois — dentro de uma execução o arquivo não muda.
    """
    try:
        return json.loads((REPO / "data" / "sei_restritos.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _restrito_confirmado(proc: str) -> bool:
    """O registro de controle diz que este processo é de ACESSO RESTRITO, e a marca ainda é recente?

    Dos 2.760 abandonados, 311 estão como RESTRITO (score>=2: duas leituras 0-doc de um processo
    que EXISTE no cadastro) e 69 como RESTRITO?. Retentá-los é gastar ~100s cada em acesso negado
    documentado — INDISPONÍVEL de verdade, não falha intermitente. O sweep rende mais nos 2.262
    que são anteriores ao registro (2026-07-14) e sobre os quais não há evidência nenhuma.

    Só o RESTRITO **confirmado** (score>=2) segura; `RESTRITO?` com uma leitura só volta à fila —
    é precisamente a segunda leitura que confirma ou desmente a marca.

    E a marca também EXPIRA, em janela mais larga: nível de acesso muda, processo é desclassificado,
    o acesso do itkava é ampliado. Trocar uma isenção permanente por outra seria repetir o defeito
    que esta mesma função foi escrita para corrigir.
    """
    try:
        e = _registro_restritos().get(re.sub(r"\D", "", proc or ""))
        if not isinstance(e, dict) or e.get("status") != "RESTRITO":
            return False
        visto = datetime.fromisoformat(str(e.get("ultima") or "").replace(" ", "T"))
        return (datetime.now() - visto).days < _DIAS_RECONFERIR_RESTRITO
    except (OSError, ValueError, TypeError, AttributeError):
        return False  # sem registro legível não se nega leitura a ninguém


def _arquivo_incompleto(proc: str) -> bool:
    """A captura arquivada deste processo está ABAIXO do mínimo que a casa exige para chamá-la
    íntegra (60% dos documentos com texto)?

    O critério é o MESMO do `manifesto_norm.captura_integra` de propósito: um processo que o
    motor recusa avaliar por captura insuficiente é, por definição, um processo a recapturar —
    não faria sentido a leitura e a avaliação usarem réguas diferentes. Medido em 2026-08-04:
    94 processos com ZERO teor, 86 abaixo do mínimo e 54 com manifesto sem docs; 234 no total,
    contra 1.941 íntegros que seguem pulados. O sweep faz ~288/dia, então o passivo cabe num dia.

    Só devolve True quando há pasta: processo nunca arquivado não é captura incompleta, é
    não-capturado, e esse caminho já é tratado pela ausência no progresso.
    """
    tag = re.sub(r"_+", "_", re.sub(r"\D", "_", re.sub(r"^SEI-?", "", proc or ""))).strip("_")
    pasta = REPO / "data" / "sei_arquivo" / tag
    mf = pasta / "manifest.json"
    if not mf.exists():
        return False
    try:
        from compliance_agent.sei import manifesto_norm
        man = json.loads(mf.read_text(encoding="utf-8"))
        man["_pasta"] = str(pasta)
        return not manifesto_norm.captura_integra(man, pasta)[0]
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        return False


def _arquivo_integro(proc: str) -> str | None:
    """Data da captura arquivada, quando ela é ÍNTEGRA pela régua da casa; `None` caso contrário.

    A METADE QUE FALTAVA. `_arquivo_incompleto` devolve à fila quem tem captura insuficiente — o
    disco mandando mais que o progresso. Faltava o sentido oposto: captura COMPLETA tira da fila,
    mesmo que o progresso diga zero. Progresso e acervo são preenchidos por caminhos diferentes (o
    sweep grava o primeiro; a colheita da VM-2, a recaptura integral e o `sei_arquivar` gravam o
    segundo), e eles divergem.

    Medido em 2026-08-11: de 2.315 pastas no acervo, **321** têm entrada no progresso dizendo ZERO
    documento e **118** dessas são íntegras — processos completos que continuavam elegíveis para
    releitura, alguns com 3 a 5 tentativas já gastas. Foi assim que o processo de R$ 88,0 mi do
    caso AGILE/SEEDUC ficou dado como "nunca lido" com 407 documentos no disco desde 09/08.

    Devolve a DATA, e não um booleano, porque quem chama precisa dela: processo que ANDOU (OB mais
    nova que a captura) volta a ser lido. Sem essa exceção, o conserto trocaria releitura inútil
    por cegueira a fato novo.
    """
    tag = re.sub(r"_+", "_", re.sub(r"\D", "_", re.sub(r"^SEI-?", "", proc or ""))).strip("_")
    pasta = REPO / "data" / "sei_arquivo" / tag
    mf = pasta / "manifest.json"
    if not mf.exists():
        return None
    try:
        from compliance_agent.sei import manifesto_norm
        man = json.loads(mf.read_text(encoding="utf-8"))
        man["_pasta"] = str(pasta)
        if not manifesto_norm.captura_integra(man, pasta)[0]:
            return None
        return str(man.get("gerado_em") or "") or None
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        return None


def _salvar_cadeia_no_cache(proc: str, cadeia: list):
    """Anexa a cadeia (relacionados lidos) ao cache cdp_*.json do processo — o Lex passa a ver a árvore."""
    cf = CACHE / f"cdp_{re.sub(r'[^0-9A-Za-z]', '_', proc)}.json"
    try:
        d = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else {"numero": proc}
        d["cadeia"] = cadeia
        d["_cached_at"] = datetime.now().isoformat()
        cf.write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    except Exception as exc:
        logger.warning("falha ao gravar cadeia no cache de %s — árvore perdida: %s", proc, exc)


async def _ficha_e_storage(proc: str):
    """Extrai a FICHA (cascata gemini-lite→stepfun:free) do conteúdo REAL e guarda SÓ a ficha no cache,
    DESCARTANDO o `texto` (menu lateral do SEI = lixo de ~12k chars). Storage: ~3-7× menor, sem perda útil.
    Retorna (n_chars_antes, n_chars_depois, modelo) ou None."""
    from tools.sei_ficha import conteudo_real, extrair_ficha, STEPFUN
    cf = CACHE / f"cdp_{re.sub(r'[^0-9A-Za-z]', '_', proc)}.json"
    if not cf.exists():
        return None
    try:
        d = json.loads(cf.read_text(encoding="utf-8"))
        antes = len(cf.read_text(encoding="utf-8"))
        cont = conteudo_real(d)
        if len(cont) < 150:
            return None
        # SÓ o nous stepfun:free (100% grátis/sem limite — diretriz do dono: gemini FORA do sweep).
        # extrair_ficha já retenta 502/503 transientes. Se falhar, retorna None → fica p/ a próxima passada
        # (sweep resumível: não marca como feito, retenta depois). Vamos aos poucos.
        f = await extrair_ficha(cont, STEPFUN, provider="nous")
        modelo = STEPFUN  # id real do catálogo (o rótulo antigo "stepfun:free" não existe mais — 404)
        if f.get("_erro"):
            return None
        d["ficha"] = f
        d["texto"] = (d.get("texto") or "")[:200]   # descarta o menu lixo; mantém só uma amostra
        # STORAGE: com a ficha (relevante) em mãos, trima o conteúdo cru — guarda só um EXCERTO de cada
        # doc (traçabilidade), não o texto inteiro. A ficha é a fonte queryável; o excerto aponta a origem.
        for c in (d.get("conteudo_documentos") or []):
            if isinstance(c, dict) and c.get("conteudo"):
                c["conteudo"] = c["conteudo"][:400]
                c["_trimado"] = True
        for rel in (d.get("cadeia") or []):
            if rel.get("texto"):
                rel["texto"] = rel["texto"][:400]
        d["_ficha_modelo"] = modelo
        cf.write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return (antes, len(cf.read_text(encoding="utf-8")), modelo)
    except Exception:  # noqa: BLE001
        return None


async def run(max_n: int, ug: str | None, tentativas_login: int = 20,
              seguir_arvore: bool = True, max_rel_arvore: int = 3, fazer_ficha: bool = True,
              cnpj: str | None = None, diario: bool = False):
    from compliance_agent.envfile import carregar_env
    carregar_env()
    from compliance_agent.recursos import browser_lock_async, aguardar_load_async
    from compliance_agent.collectors.sei_cdp import _proxy_do_env
    from tools.sei_reader import login, ler_processo, seguir_relacionados, _ler_cracked, _montar_resultado_cracked
    from playwright.async_api import async_playwright

    prog = _carregar_prog()
    # Unidades APRENDIDAS como fora do acesso do itkava (amostra suficiente, todas 0 docs) → pular o resto
    # delas (são INDISPONÍVEL por acesso, não vazias) em vez de tentar milhares fútilmente. Adaptativo.
    sem_acesso = _unidades_sem_acesso(prog)
    # FRESCOR POR OB: última OB (TFE+SIAFE) de cada processo → re-ler o que ANDOU desde a leitura.
    ob_recente = _ultima_ob_por_processo()
    _n_stale = sum(1 for p, f in prog["feitos"].items()
                   if f.get("n_docs", 0) and _ob_desatualizada(ob_recente.get(p, ""), f.get("em", "")))
    if _n_stale:
        _log(f"[frescor] {_n_stale} processos já lidos têm OB mais nova que a leitura → serão re-lidos.")
    # FASE UPDATE-DIÁRIO (regra do dono 'não pode errar'): só AQUI pulamos as árvores ENCERRADAS — gate
    # firme da sei_arvore (situação autoritativa arquivado/concluído + sem OB recente + sem aditivo + sem
    # filho vigente). NUNCA no drain inicial (diario=False), p/ não deixar processo por ler na 1ª passada.
    encerradas: set[str] = set()
    if diario:
        try:
            encerradas = _arvores_encerradas()  # gate firme + defesa extra de recência da última OB
        except Exception as e:  # noqa: BLE001 — na dúvida não pula nada (conservador)
            _log(f"[diario] não consegui carregar árvores encerradas ({type(e).__name__}) — não pulo nenhuma.")
            encerradas = set()
        if encerradas:
            _log(f"[diario] {len(encerradas)} árvores ENCERRADAS (gate firme) serão puladas nesta passada diária.")

    def _pular(p: str) -> bool:
        if _ja_lido_ok(p):
            return True
        if _unidade(p) in sem_acesso:  # unidade inteira fora do acesso do itkava (INDISPONÍVEL)
            return True
        if diario and p in encerradas:  # SÓ no update-diário: árvore encerrada (gate firme corroborado)
            return True
        f = prog["feitos"].get(p)
        if _falha_recente(f):  # cooloff: falha há <4h espera a PRÓXIMA janela de WAF (não queima tentativa)
            return True
        # FRESCOR POR OB: OB mais nova que a última leitura → processo andou → NÃO pular (re-ler p/ perícia
        # completa). Vem depois do cooloff (não martela na mesma janela) e do sem_acesso. Auto-limita: ao
        # re-ler, 'em' vira agora() > data da OB → não re-dispara.
        if f and f.get("n_docs", 0) and _ob_desatualizada(ob_recente.get(p, ""), f.get("em", "")):
            return False
        # ARQUIVO SEM TEOR MANDA MAIS QUE O PROGRESSO. Medido em 2026-08-04: **120 processos**
        # estavam marcados `n_docs>0` no progresso e não tinham UM documento com texto no acervo
        # — o sweep os pulava para sempre. E a ferramenta que os devolveria à fila
        # (`sei_reparar_truncados --sem-texto`) pula quem já tem `captura_vazia`, de modo que
        # DECLARAR a captura vazia virou isenção permanente de nova tentativa. Declarar é honesto;
        # desistir não era o combinado. Mesma doutrina do `captura_integra`: o disco decide.
        if f and f.get("n_docs", 0) > 0 and _arquivo_incompleto(p):
            return False
        # E A METADE SIMÉTRICA: captura ÍNTEGRA no acervo TIRA da fila, mesmo com o progresso
        # dizendo zero. Progresso e acervo são preenchidos por caminhos diferentes e divergem —
        # medido em 2026-08-11: 118 processos completos continuavam elegíveis para releitura,
        # alguns com 3 a 5 tentativas gastas. O disco decide nos dois sentidos.
        # A exceção fica de pé: se há OB mais nova que a captura, o processo ANDOU e volta a ser
        # lido — trocar releitura inútil por cegueira a fato novo não seria conserto.
        _integro_em = _arquivo_integro(p)
        if _integro_em and not _ob_desatualizada(ob_recente.get(p, ""), _integro_em):
            return True
        # DESISTIR NÃO PODE SER PARA SEMPRE. A regra de 3 tentativas existe para não martelar
        # processo vazio ou restrito — mas a própria docstring do `_ja_lido_ok` diz que "a
        # abertura do SEI é flaky". Medido em 2026-08-04: **2.760 processos abandonados**, e as
        # unidades deles são as MESMAS onde milhares foram lidos com sucesso (UG 080002: 826
        # abandonados contra 1.284 lidos) — não é falta de acesso, é falha intermitente. Entre os
        # abandonados estão o SEI-150001/011573/2021 (R$ 210 mi, o primeiro da fila por dinheiro)
        # e o SEI-080001/005089/2022 (I.D.E.A.S, R$ 135 mi): a fila propõe justamente o que o
        # sweep desistiu.
        # 2.131 dos 2.760 foram abandonados há MAIS DE 14 DIAS, sob episódios de WAF/sessão que
        # já passaram. A tentativa expira: depois da janela, o processo ganha nova chance. Não é
        # martelar — é reconhecer que a condição mudou.
        if f and f.get("n_docs", 0) == 0 and f.get("tentativas", 0) >= 3:
            if not _tentativa_expirou(f.get("em")):
                return True
            # expirou: volta à fila, SALVO acesso restrito confirmado e ainda recente — esse é
            # INDISPONÍVEL documentado, não falha intermitente (e a marca também expira, em 90d).
            return _restrito_confirmado(p)
        return bool(f and f.get("n_docs", 0) > 0)

    # COTA PARA A RETENTATIVA. Devolver os 1.977 abandonados à fila foi certo — mas medido nas
    # primeiras horas: **22 das 31 leituras (71%)** eram deles, e TODAS deram 0 documento, porque
    # se concentram nas unidades de alta restrição (080001/080002/040014). A retentativa se paga
    # (duas leituras classificam o processo como RESTRITO e o tiram da fila por 90 dias), mas não
    # pode consumir a capacidade de quem nunca foi tocado. Um terço do lote, no máximo; a ordem
    # por valor é preservada dentro de cada grupo.
    candidatos = [(p, nob, tot) for (p, nob, tot) in _fila(ug, max_n, cnpj) if not _pular(p)]
    def _e_retentativa(proc: str) -> bool:
        f = prog["feitos"].get(proc) or {}
        return bool(f.get("tentativas", 0) >= 3 and f.get("n_docs", 0) == 0)
    novos = [c for c in candidatos if not _e_retentativa(c[0])]
    velhos = [c for c in candidatos if _e_retentativa(c[0])]
    teto_velhos = max(1, max_n // 3)
    usar_velhos = velhos[:teto_velhos]
    # INTERCALADO, não concatenado: o lote é cortado por `timeout`, e pôr a retentativa no fim
    # faria o corte comê-la sempre — trocaria uma inanição por outra. Uma retentativa a cada três
    # posições mantém a cota e garante que ela seja de fato lida.
    fila, iv, inv = [], iter(usar_velhos), iter(novos)
    while len(fila) < max_n:
        bloco = [next(inv, None) for _ in range(2)] + [next(iv, None)]
        bloco = [x for x in bloco if x]
        if not bloco:
            break
        fila.extend(bloco)
    # A cota limita CONCORRÊNCIA, não trabalho: se não há mais nada a ler, o lote se completa com
    # retentativa em vez de devolver vagas vazias ao cron.
    if len(fila) < max_n:
        ja = set(fila)
        fila.extend(x for x in velhos if x not in ja)
    fila = fila[:max_n]
    if usar_velhos:
        _log(f"fila: {len(novos)} nunca lidos + {len(usar_velhos)} de {len(velhos)} "
             f"retentativas (cota de 1/3, intercaladas)")
    if not fila:
        _log("nada novo na fila (tudo já lido/cacheado).")
        return
    _log(f"fila: {len(fila)} processos novos (de OBs{'/UG ' + ug if ug else ''}); login único itkava…")

    await aguardar_load_async(max_por_core=1.5, espera_max=120)
    proxy = _proxy_do_env()
    n_ok = n_zero = n_doc_total = 0
    # CRASH-PROOF (regra do dono: sweep NUNCA crasha): a sessão inteira do browser fica sob try/except. Se o
    # browser/pipe MORRE (EPIPE, TargetClosed, WAF derrubando, lock estourado), vira SAÍDA LIMPA logada — o cron
    # repete no próximo slot. Nada de traceback não-tratado nem Node crashando o processo.
    try:
        async with browser_lock_async(espera_max=600), async_playwright() as pw:
            b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"],
                                         **({"proxy": proxy} if proxy else {}))
            ctx = await _contexto_sei(b)
            pg = await ctx.new_page()
            try:
                if not await login(pg, tentativas=tentativas_login):
                    _log(f"ABORTADO: login itkava não completou em {tentativas_login} tentativas. "
                         "NÃO se atribui a WAF nem a bloqueio de acesso (o acesso é liberado): "
                         "a causa já observada é sessão anterior deixada aberta por "
                         "encerramento abrupto do slot anterior.")
                    return
                _log("login OK — varrendo…")
                # NÃO COMEÇAR O QUE NÃO DÁ PARA TERMINAR. O `timeout -k 120 --foreground 1500` do
                # sweep manda TERM aos 1500s e KILL 120s depois; `_PARAR` só é lido ENTRE processos,
                # e uma leitura leva 123s na mediana mas 249s no p90 (máx. medido: 2768s). Quando o
                # TERM cai no meio de uma leitura longa, a carência estoura e vem o SIGKILL — que
                # mata o ciclo inteiro antes dos passos finais e apaga a linha de "fim" do log.
                # Medido em 2026-08-10: **725 ocorrências de rc=137** no histórico do sweep.
                # Aqui a parada é ANTES de abrir o próximo processo, e o ciclo termina inteiro.
                t_ciclo = time.time()
                orcamento_s = int(os.environ.get("SEI_ORCAMENTO_S", "1200") or 0)
                for i, (proc, nob, tot) in enumerate(fila, 1):
                    gasto = time.time() - t_ciclo
                    if orcamento_s and gasto > orcamento_s:
                        _log(f"ORÇAMENTO de {orcamento_s}s esgotado em {gasto:.0f}s após {i - 1} "
                             f"processo(s) — paro ANTES de abrir o próximo, para o ciclo chegar "
                             f"aos passos finais em vez de morrer no SIGKILL.")
                        break
                    if _PARAR:
                        _log("SIGTERM/timeout — encerrando LIMPO entre processos (browser fecha no finally, sem EPIPE)."); break
                    if PAUSE.exists():
                        _log("pausa detectada (.pause_sei_sweep) — encerrando limpo."); break
                    t0 = time.time()
                    # a busca→abrir do SEI é INTERMITENTE (cai na caixa) — retenta até abrir (docs/relacionados>0),
                    # como o ler_com_cadeia. Sem retry, leituras válidas viravam "0 docs" (era o bug do sweep).
                    try:
                        r, nd = {}, 0
                        for _try in range(3):
                            # SEMPRE fresco: _ja_lido_ok já pulou os sucessos; aqui são 0-doc/novos → não usar cache 0-doc.
                            r = await ler_processo(pg, proc, usar_cache=False)
                            nd = len(r.get("documentos") or [])
                            # sucesso = DOCUMENTOS>0. relacionados sozinho (sem docs) é a CAIXA/desktop (~40 inbox),
                            # NÃO um processo aberto — não contar como sucesso.
                            if nd > 0:
                                break
                            # árvore ABRIU e deu 0 docs = restrito/vazio HONESTO — retentar leitura completa
                            # não muda o resultado (era o custo dominante do sweep: 3×~45s p/ cada 0-doc).
                            # Só retenta quando a LEITURA falhou: árvore não abriu ou caiu na caixa (rel>15).
                            if not r.get("indisponivel") and len(r.get("relacionados") or []) <= 15:
                                break
                            await asyncio.sleep(2)
                        if nd == 0 and (r.get("indisponivel") or len(r.get("relacionados") or []) > 15):
                            # CAIXA/leitura falha (indisponivel=árvore não abriu; rel>15=inbox legado) →
                            # tenta o método CRACKED, como ler()/ler_com_cadeia. Provado ao vivo: recupera
                            # p.ex. 270042 ITERJ (normal=0/rel40 → cracked=10); fica 0 honesto em restrito.
                            # 2026-07-10: o filtro do menu (sei_cdp) zerou o rel~40 da caixa → o gatilho
                            # passa a ser o flag indisponivel do ler_processo (arvore_vista=False).
                            dump = await _ler_cracked(pg, proc)
                            if dump.get("documentos"):
                                r = await _montar_resultado_cracked(pg, proc, dump, usar_cache=False)
                                nd = len(r.get("documentos") or [])
                    except Exception as e:  # noqa: BLE001
                        _log(f"  [{i}/{len(fila)}] {proc} ERRO {type(e).__name__}: {str(e)[:60]}")
                        # se foi o BROWSER que caiu, as próximas leituras também falham → aborta a sessão limpa
                        # (o cron repete) em vez de logar 20 erros seguidos; demais erros: segue p/ o próximo.
                        if _browser_morto(e):
                            _log("  browser/pipe caiu no meio — encerrando a sessão LIMPO (cron repete). Sem crash.")
                            break
                        continue
                    # controle de RESTRITOS: registra o resultado final ao longo do sweep (0-doc+árvore-não-abriu
                    # +existe no cadastro = provável acesso restrito). Degrada em silêncio, nunca derruba o sweep.
                    try:
                        from tools import sei_restritos as _restr
                        _restr.registrar(proc, r)
                    except Exception:  # noqa: BLE001
                        pass
                    # SEI-2: segue a ÁRVORE de relacionados (o processo de pagamento tem pouco; a licitação/
                    # contrato relacionado tem a substância). Guarda 1<=N<=15 evita a CAIXA (~40 inbox).
                    rel = r.get("relacionados") or []
                    cadeia = []
                    if seguir_arvore and 1 <= len(rel) <= 15:
                        try:
                            cadeia = await seguir_relacionados(pg, r.get("url") or "", rel, max_rel=max_rel_arvore)
                        except Exception:  # noqa: BLE001
                            cadeia = []
                    nd_arv = sum(c.get("n_docs", 0) for c in cadeia)
                    if cadeia:
                        _salvar_cadeia_no_cache(proc, cadeia)  # Lex passa a enxergar a árvore
                    # FICHA + STORAGE: extrai só o relevante e descarta o `texto` (menu lixo de ~12k chars).
                    ficha_info = None
                    if fazer_ficha and (nd or nd_arv):
                        try:
                            ficha_info = await _ficha_e_storage(proc)
                        except Exception:  # noqa: BLE001
                            ficha_info = None
                    _f = prog["feitos"].get(proc, {})
                    prog["feitos"][proc] = {"n_docs": nd, "tentativas": _f.get("tentativas", 0) + 1,
                                            "rel": len(rel), "arvore_docs": nd_arv, "arvore_n": len(cadeia),
                                            "em": datetime.now().isoformat(timespec="seconds")}
                    _salvar_prog(prog)
                    if nd or nd_arv:
                        n_ok += 1; n_doc_total += nd + nd_arv
                    else:
                        n_zero += 1
                    _arv = f" +árvore {len(cadeia)} proc/{nd_arv} docs" if cadeia else ""
                    _fic = ""
                    if ficha_info:
                        a, dp, mdl = ficha_info
                        _fic = f" · ficha[{mdl}] {a}→{dp}ch ({a / max(dp, 1):.0f}× menor)"
                    _log(f"  [{i}/{len(fila)}] {proc} → {nd} docs{_arv}{_fic} (R$ {tot:,.0f}, {nob} OBs) {time.time()-t0:.0f}s")
            finally:
                try:
                    await b.close()  # fechar um browser JÁ MORTO levanta (EPIPE/TargetClosed) — nunca pode crashar
                except Exception as e:  # noqa: BLE001
                    _log(f"  (encerramento do browser ignorado: {type(e).__name__})")
    except Exception as e:  # noqa: BLE001 — CRASH-PROOF: morte de browser/pipe/lock vira saída LIMPA (cron repete)
        _log(f"sessão de browser caiu ({type(e).__name__}: {str(e)[:80]}) — encerrando LIMPO, sem crash. Cron repete.")
        return
    # "fora de escopo/vazio" era uma CAUSA AFIRMADA que ninguém mediu. Medido em 2026-08-10 sobre os
    # 3.775 processos zerados do progresso: só 930 têm motivo registrado (378 RESTRITO, 352
    # NAO_LOCALIZADO, 200 RESTRITO?); 2.794 não têm motivo nenhum, e 51 estão marcados OK no
    # `sei_restritos` e ainda assim vieram vazios. Zero sem causa é NÃO SEI, não "não havia".
    _log(f"FIM: {n_ok} com docs ({n_doc_total} docs), {n_zero} sem documento — CAUSA NÃO MEDIDA "
         f"(restrito, inexistente ou falha de leitura; ver data/sei_restritos.json). "
         f"Progresso em {PROG.name}.")


async def run_pais(max_n: int, tentativas_login: int = 20, fazer_ficha: bool = True,
                   so_alta: bool = False, cnpj: str | None = None,
                   # A FOLGA TEM DE CABER A LEITURA, não o contrário. O shell chama este caminho sob
                   # `timeout -k 120 --foreground 900`: com orçamento de 700s sobravam 200s até o
                   # TERM e 320s até o KILL, mas a leitura leva 123s na mediana e **249s no p90**
                   # (máx. medido 2768s) — o orçamento era menor que o caso ruim típico, e o ciclo
                   # morria de SIGKILL (visto em 2026-08-10 às 10:08, `sei_pais rc=137`). Com 600s
                   # a folga vai a 300s até o TERM e 420s até o KILL, acima do p90.
                   orcamento_s: int = int(os.environ.get("SEI_PAIS_ORCAMENTO_S", "600"))):
    """MODO 'SEGUIR PAIS' (recupera a substância dos dockets vazios/execução): detecta no cache os
    PROCESSOS-PAI de CONTRATAÇÃO referenciados (regex SEI + janela de palavra-chave de contratação, com
    denylist de boilerplate do menu lateral) que AINDA NÃO estão no cache, e os LÊ na mesma sessão única
    itkava — gravando docs + ficha no mesmo cache. Resumível (o que já lê fica em cache e não re-enfileira);
    bounded (o orquestrador embrulha em `timeout`); crash-proof (morte de browser = saída limpa).

    Por que funciona: o docket de pagamento aponta "processo de contratação em andamento de nº SEI-..." no
    CORPO de um despacho — é o pai que tem o contrato/parecer. Honesto: detecção é indício; refs do menu são
    descartadas; nada é inventado."""
    from compliance_agent.envfile import carregar_env
    carregar_env()
    from compliance_agent.recursos import browser_lock_async, aguardar_load_async
    from compliance_agent.collectors.sei_cdp import _proxy_do_env
    from tools.sei_reader import login, ler_processo, _ler_cracked, _montar_resultado_cracked
    from tools.sei_pais import detectar_pais, _norm
    from playwright.async_api import async_playwright

    # SEM `carregar_cache()`: ela materializa os 18 GB do acervo em RAM e é o que derrubou a VM
    # (OOM 11× em 27/07 + a queda das 22:22 + mais um às 23:04, este último causado por rodar a
    # validação com o chamador ainda antigo). `detectar_pais()` sem argumento percorre o cache em
    # streaming, com pico medido de 807 MB.
    pais = detectar_pais(incluir_relacionados=not so_alta, log=_log)
    if cnpj:  # foca nos pais citados por dockets do CNPJ alvo (pré-carrega o /relatorio dele)
        cd = re.sub(r"\D", "", cnpj)
        # origem é o docket que citou; cruza com as OBs do CNPJ
        con = sqlite3.connect(str(DB))
        seus = {r[0] for r in con.execute(
            "SELECT DISTINCT numero_sei FROM ordens_bancarias WHERE "
            "replace(replace(replace(favorecido_cpf,'.',''),'/',''),'-','')=?", (cd,)).fetchall()}
        con.close()
        pais = [p for p in pais if p["origem"] in seus] or pais  # se nada casar, não trava: usa todos
    prog = _carregar_prog()
    feitos = prog.get("pais_feitos") or {}
    # TETO DE TENTATIVAS — SEM ELE A FILA NUNCA ANDA. A regra antiga excluía apenas quem tinha
    # devolvido documento; quem devolvia ZERO voltava para sempre. Medido na VM-2 em 2026-08-07:
    # os MESMOS CINCO processos relidos a cada 30 minutos, 110-136 s cada, **34 minutos de CPU por
    # rodada**, durante dias, enquanto os outros 120 detectados nunca chegavam a ser oferecidos.
    # Zero documentos é resultado legítimo (processo restrito, árvore que não abre) e repeti-lo
    # indefinidamente é a definição de trabalho inútil. O sweep normal já tinha o skip após três
    # tentativas exatamente por isto; aqui faltava.
    _TETO_TENTATIVAS = 3
    _chega = {_norm(k) for k, v in feitos.items()
              if (v.get("n_docs", 0) or 0) > 0 or (v.get("tentativas", 1) or 1) >= _TETO_TENTATIVAS}
    fila = [p for p in pais if _norm(p["pai"]) not in _chega][:max_n]
    if not fila:
        _log("[pais] nada novo (todos os pais detectados já lidos/cacheados).")
        return
    _log(f"[pais] {len(fila)} processos-pai de contratação a ler (de {len(pais)} detectados); login único itkava…")

    await aguardar_load_async(max_por_core=1.5, espera_max=120)
    proxy = _proxy_do_env()
    n_ok = n_zero = n_doc_total = 0
    try:
        async with browser_lock_async(espera_max=600), async_playwright() as pw:
            b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"],
                                         **({"proxy": proxy} if proxy else {}))
            ctx = await _contexto_sei(b)
            pg = await ctx.new_page()
            try:
                if not await login(pg, tentativas=tentativas_login):
                    _log("[pais] ABORTADO: login itkava não completou em "
                         f"{tentativas_login} tentativas. NÃO se atribui a WAF nem a bloqueio "
                         "de acesso (o acesso é liberado): a causa já observada é sessão "
                         "anterior deixada aberta por encerramento abrupto do slot."); return
                _log("[pais] login OK — lendo os pais…")
                # ORÇAMENTO DE TEMPO — O SLOT MORRIA DE SIGKILL EM **TODAS** AS EXECUÇÕES. Medido em
                # 2026-08-06: `sei_pais rc=137` nas dez últimas rodadas, desde 05/08 pelo menos, e
                # nenhuma linha `[pais] FIM` no log. O `timeout -k 120 --foreground 900` manda
                # SIGTERM aos 900 s, mas `_PARAR` só é consultado ENTRE processos — e uma leitura de
                # pai tem mediana de 121 s, p90 de 137 s e máximo medido de **502 s**. O SIGKILL
                # sempre vencia, o browser nunca fechava, e a sessão itkava ficava pendurada: os
                # dois slots seguintes falhavam no login e o código culpava o WAF, que é justamente
                # a explicação que esta casa proíbe. Aqui o laço para SOZINHO, com margem para uma
                # leitura de p90 e para fechar o browser.
                t_inicio = time.time()
                for i, p in enumerate(fila, 1):
                    gasto = time.time() - t_inicio
                    if orcamento_s and gasto > orcamento_s:
                        _log(f"[pais] ORÇAMENTO de {orcamento_s}s esgotado em {gasto:.0f}s — parei "
                             f"em {i-1}/{len(fila)}, sessão fechada LIMPA. O cron retoma.")
                        break
                    if _PARAR:
                        _log("[pais] SIGTERM/timeout — encerrando LIMPO entre processos."); break
                    if PAUSE.exists():
                        _log("[pais] pausa detectada — encerrando limpo."); break
                    proc = p["pai"]
                    t0 = time.time()
                    try:
                        r, nd = {}, 0
                        for _try in range(3):
                            r = await ler_processo(pg, proc, usar_cache=False)
                            nd = len(r.get("documentos") or [])
                            if nd > 0:
                                break
                            if not r.get("indisponivel") and len(r.get("relacionados") or []) <= 15:
                                break              # 0-doc honesto (árvore abriu) — retry não muda
                            await asyncio.sleep(2)
                        if nd == 0:
                            # caminho normal caiu na caixa (rel=40/0 docs) → tenta o método CRACKED, como
                            # ler()/ler_com_cadeia (provado ao vivo: recupera 270042 ITERJ onde o normal
                            # dá 0; fica 0 honesto em restrito). NÃO substitui o normal — só recupera o 0.
                            dump = await _ler_cracked(pg, proc)
                            if dump.get("documentos"):
                                r = await _montar_resultado_cracked(pg, proc, dump, usar_cache=False)
                                nd = len(r.get("documentos") or [])
                    except Exception as e:  # noqa: BLE001
                        _log(f"  [pais {i}/{len(fila)}] {proc} ERRO {type(e).__name__}: {str(e)[:60]}")
                        if _browser_morto(e):
                            _log("  [pais] browser/pipe caiu — encerrando a sessão LIMPO. Sem crash."); break
                        continue
                    # controle de RESTRITOS: registra o resultado final ao longo do sweep (0-doc+árvore-não-abriu
                    # +existe no cadastro = provável acesso restrito). Degrada em silêncio, nunca derruba o sweep.
                    try:
                        from tools import sei_restritos as _restr
                        _restr.registrar(proc, r)
                    except Exception:  # noqa: BLE001
                        pass
                    ficha_info = None
                    if fazer_ficha and nd:
                        try:
                            ficha_info = await _ficha_e_storage(proc)
                        except Exception:  # noqa: BLE001
                            ficha_info = None
                    _antes = (feitos.get(proc) or {}).get("tentativas", 0) or 0
                    feitos[proc] = {"n_docs": nd, "via": p["fonte"], "conf": p["confianca"],
                                    "origem": p["origem"], "tentativas": _antes + 1,
                                    "em": datetime.now().isoformat(timespec="seconds")}
                    prog["pais_feitos"] = feitos
                    _salvar_prog(prog)
                    if nd:
                        n_ok += 1; n_doc_total += nd
                    else:
                        n_zero += 1
                    _fic = ""
                    if ficha_info:
                        a_, dp, mdl = ficha_info
                        _fic = f" · ficha[{mdl}] {a_}→{dp}ch"
                    _log(f"  [pais {i}/{len(fila)}] {proc} → {nd} docs{_fic} "
                         f"({p['confianca']}/{p['fonte']}, ←{p['origem']}) {time.time()-t0:.0f}s")
            finally:
                try:
                    await b.close()
                except Exception as e:  # noqa: BLE001
                    _log(f"  [pais] (encerramento do browser ignorado: {type(e).__name__})")
    except Exception as e:  # noqa: BLE001 — CRASH-PROOF
        _log(f"[pais] sessão de browser caiu ({type(e).__name__}: {str(e)[:80]}) — encerrando LIMPO. Cron repete.")
        return
    _log(f"[pais] FIM: {n_ok} pais com docs ({n_doc_total} docs), {n_zero} sem. Progresso em {PROG.name}.")




async def run_recaptura(max_n: int, tentativas_login: int = 20, teto: int = 120,
                        ate: int = 0) -> None:
    """RELÊ processos cujo cache prova que há documento na árvore SEM texto — login ÚNICO.

    Por que aqui e não num script à parte, e isto foi MEDIDO em 2026-08-03: uma passada
    independente pagava o login + carga de árvore a cada processo — **556 segundos para um
    processo de 5 documentos**. O custo não é do teto de documentos, é da entrada. Aqui a sessão
    é uma só para o lote inteiro, exatamente como o `run_pais` já fazia.

    O que se ganha: dos 314 processos com cache, a árvore tem 19.583 documentos e só 9.136 tinham
    texto lido — 10.447 fechados, porque o `SEI_MAX_DOCS` do leitor era 40 e 179 processos
    paravam exatamente lá.

    Ordem: do MENOR buraco para o MAIOR. Medido: o processo gigante (956 documentos) estoura o
    slot, mata o browser e não entrega nada — e enquanto ele falha, nenhum outro anda.
    """
    from compliance_agent.envfile import carregar_env
    carregar_env()
    from compliance_agent.recursos import browser_lock_async, aguardar_load_async
    from compliance_agent.collectors.sei_cdp import _proxy_do_env
    from tools.sei_reader import login, ler_processo, _ler_cracked, _montar_resultado_cracked
    from playwright.async_api import async_playwright

    os.environ["SEI_MAX_DOCS"] = str(teto)
    from tools.sweep_recaptura_integral import fila as _fila_recap
    fila = _fila_recap()
    # A FATIA VALE AQUI TAMBÉM. O sweep principal já divide o universo entre as duas máquinas
    # (`JFN_SWEEP_FATIA=1/2`), mas a recaptura não dividia nada: as duas percorriam a MESMA fila,
    # na mesma ordem, e a segunda máquina gastaria seus slots refazendo o que a primeira acabara de
    # fazer. É o defeito que já custou trabalho duplicado no grafo societário — 400 credores
    # percorridos duas vezes — e que aqui custaria mais, porque o slot da recaptura é o recurso
    # mais escasso da casa: 2 processos a cada 3 horas sobre uma fila de 1.516.
    #
    # A divisão é determinística e sem coordenação: cada máquina fica com metade dos números, e as
    # duas somadas dobram a vazão sem que uma precise saber da outra. Não fere "1 sessão SEI por
    # IP" — são IPs distintos, cada um com sua sessão.
    indice, total = fatia_desta_maquina()
    if total > 1:
        antes = len(fila)
        fila = [x for x in fila if na_minha_fatia(str(x["numero"]), indice, total)]
        _log(f"[recap] fatia {indice}/{total}: {len(fila)} de {antes} processos são desta máquina")
    if ate:
        fila = [x for x in fila if x["faltam"] <= ate]
    prog = _carregar_prog()
    feitos = prog.get("recaptura_feitos") or {}
    # DESISTIR NÃO É PARA SEMPRE — a mesma doutrina do sweep principal (tentativa expira) e do
    # caminho resiliente. `not in feitos` cru transformava UMA releitura sem ganho em exclusão
    # perpétua: com a recaptura viva, os casos "4 → 4" (doc que falhou hoje, restrição transitória)
    # sumiriam da fila para sempre. Quem GANHOU fica fora; quem não ganhou volta depois de 7 dias.
    from tools.sweep_recaptura_integral import _sem_ganho_expirou
    fila = [x for x in fila
            if x["numero"] not in feitos or _sem_ganho_expirou(feitos[x["numero"]])][:max_n]
    if not fila:
        _log("[recap] nada pendente (fila de recaptura vazia ou já percorrida).")
        return
    _log(f"[recap] {len(fila)} processos a reler com SEI_MAX_DOCS={teto}; login único itkava…")

    await aguardar_load_async(max_por_core=1.5, espera_max=120)
    proxy = _proxy_do_env()
    ganho = 0
    try:
        async with browser_lock_async(espera_max=600), async_playwright() as pw:
            b = await pw.chromium.launch(headless=True,
                                         args=["--no-sandbox", "--ignore-certificate-errors"],
                                         **({"proxy": proxy} if proxy else {}))
            ctx = await _contexto_sei(b)
            pg = await ctx.new_page()
            try:
                if not await login(pg, tentativas=tentativas_login):
                    # A MENSAGEM NÃO PODE ELEGER UMA CAUSA QUE NINGUÉM CONFERIU. Até 07/08/2026
                    # ela afirmava "sessão anterior deixada aberta" como causa OBSERVADA — e a
                    # causa real era outra, estrutural: este caminho montava o navegador sem
                    # User-Agent de desktop, ao contrário dos outros dois. Foram 47 slots
                    # abortados nas duas máquinas enquanto o log apontava para o lugar errado.
                    # Causa afirmada sem verificação faz o leitor procurar onde não está.
                    _log("[recap] ABORTADO: login itkava não completou em "
                         f"{tentativas_login} tentativas. NÃO se atribui a WAF nem a bloqueio de "
                         "acesso (o acesso é liberado). Causas JÁ VERIFICADAS neste caminho: "
                         "contexto do navegador sem User-Agent de desktop (corrigido em 07/08) e "
                         "outra sessão SEI aberta pela mesma máquina — o SEI aceita uma por IP, "
                         "então conferir se o sweep principal ou o [pais] ainda estão no slot.")
                    # O CÓDIGO DE SAÍDA PRECISA CONTAR A VERDADE. Até 07/08/2026 este `return`
                    # devolvia 0, e o sweep registrava `sei_recaptura rc=0` — 16 vezes seguidas,
                    # para 16 slots que não recuperaram um único documento. A auditoria dos 32
                    # passos agendados desta casa foi feita POR rc, e este passou por saudável.
                    # Passo que não faz o que existe para fazer não pode reportar sucesso.
                    raise FalhaDeclarada("recaptura: login itkava não completou")
                _log("[recap] login OK — relendo…")
                for i, x in enumerate(fila, 1):
                    if _PARAR or PAUSE.exists():
                        _log("[recap] encerrando LIMPO entre processos.")
                        break
                    proc, antes = x["numero"], x["lido"]
                    try:
                        r = await ler_processo(pg, proc, usar_cache=False)
                        nd = len(r.get("conteudo_documentos") or [])
                        if not nd:
                            dump = await _ler_cracked(pg, proc)
                            if dump.get("documentos"):
                                r = await _montar_resultado_cracked(pg, proc, dump,
                                                                    usar_cache=False)
                                nd = len(r.get("conteudo_documentos") or [])
                    except Exception as e:  # noqa: BLE001
                        _log(f"  [recap {i}/{len(fila)}] {proc} ERRO {type(e).__name__}: "
                             f"{str(e)[:60]}")
                        if _browser_morto(e):
                            _log("  [recap] browser caiu — encerrando a sessão LIMPO.")
                            break
                        continue
                    feitos[proc] = {"antes": antes, "depois": nd,
                                    "em": datetime.now().isoformat(timespec="seconds")}
                    prog["recaptura_feitos"] = feitos
                    _salvar_prog(prog)
                    ganho += max(0, nd - antes)
                    _log(f"  [recap {i}/{len(fila)}] {proc}: {antes} → {nd} docs com texto")
            finally:
                await ctx.close()
                await b.close()
    finally:
        _log(f"[recap] fim do slot — +{ganho} documentos com texto nesta sessão.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--ug", type=str, default=None)
    ap.add_argument("--sem-arvore", action="store_true", help="NÃO seguir os relacionados (só o processo)")
    ap.add_argument("--max-rel", type=int, default=3, help="máx. de relacionados a seguir por processo")
    ap.add_argument("--sem-ficha", action="store_true", help="NÃO extrair ficha/storage (só ler+cachear cru)")
    ap.add_argument("--cnpj", type=str, default=None, help="só os processos das OBs de um fornecedor (pré-carrega o /relatorio dele)")
    ap.add_argument("--diario", action="store_true",
                    help="FASE UPDATE-DIÁRIO: pula as árvores ENCERRADAS (gate firme da sei_arvore — situação "
                         "autoritativa + sem OB recente/aditivo/filho vigente). NUNCA usar no drain inicial.")
    ap.add_argument("--seguir-pais", action="store_true",
                    help="MODO PAI: detecta no cache os processos-pai de CONTRATAÇÃO referenciados pelos "
                         "dockets (execução/pagamento) e os lê — recupera a substância dos 'vazios'.")
    ap.add_argument("--recaptura", action="store_true",
                    help="relê processos com documento na árvore sem texto (login único)")
    ap.add_argument("--recap-teto", type=int, default=120, help="SEI_MAX_DOCS na recaptura")
    ap.add_argument("--recap-ate", type=int, default=0,
                    help="só processos com lacuna <= N (o gigante não cabe num slot)")
    ap.add_argument("--pais-so-alta", action="store_true",
                    help="(com --seguir-pais) só os pais de ALTA confiança (conteúdo+keyword), ignora leads de relacionados")
    a = ap.parse_args()
    # encerramento gracioso por timeout/SIGTERM: o loop vê a flag e sai limpo (fecha o browser) — sem EPIPE.
    try:
        signal.signal(signal.SIGTERM, _pedir_parada)
    except (ValueError, OSError) as exc:  # noqa: BLE001 — em thread non-main signal não pode ser registrado; ignora
        logger.debug("SIGTERM não registrado (thread non-main): %s", exc)
    # BACKSTOP DE PROCESSO (regra do dono: o sweep NUNCA crasha): nada escapa como traceback não-tratado.
    # KeyboardInterrupt/SystemExit (BaseException) propagam normal; qualquer Exception vira log + saída limpa.
    try:
        if a.recaptura:
            asyncio.run(run_recaptura(a.max, teto=a.recap_teto, ate=a.recap_ate))
        elif a.seguir_pais:
            asyncio.run(run_pais(a.max, fazer_ficha=not a.sem_ficha, so_alta=a.pais_so_alta, cnpj=a.cnpj))
        else:
            asyncio.run(run(a.max, a.ug, seguir_arvore=not a.sem_arvore, max_rel_arvore=a.max_rel,
                            fazer_ficha=not a.sem_ficha, cnpj=a.cnpj, diario=a.diario))
    except FalhaDeclarada as e:
        # Falha JÁ LOGADA com diagnóstico acima — o que faltava era o código de saída dizer o
        # mesmo. O sweep continua sem crashar (regra do dono: o sweep NUNCA crasha), mas o cron e
        # a auditoria por rc passam a enxergar o que o log já dizia.
        _log(f"saída com falha: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        _log(f"ABORTADO por erro não previsto ({type(e).__name__}: {str(e)[:120]}) — saída limpa, sem crash. Cron repete.")
        return 1
    return 0


if __name__ == "__main__":
    # `sys.exit(main())`, não `main()`: sem isto o valor de retorno é descartado e todo passo sai
    # com 0, que foi exatamente como 16 abortos de recaptura passaram por saudáveis na auditoria.
    sys.exit(main())
