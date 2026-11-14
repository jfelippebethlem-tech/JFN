# -*- coding: utf-8 -*-
"""Vínculo OB ↔ contrato tirado dos AUTOS do processo de pagamento (pedido do dono, 13/11/2026).

Por que existe: a perícia contábil (`pericia_contabil`) deixava 18.397 contratos do Estado INDETERMINADOS por
"ob_do_credor_fora_do_processo" — no RJ o pagamento corre muitas vezes num processo SEI PRÓPRIO (processo de
pagamento), diferente do processo do contrato, e a OB do SIAFE não traz o número do contrato do TCE-RJ.
Atribuir a OB ao contrato por credor seria palpite. Aqui o vínculo vem do que os autos DIZEM.

Unidade do vínculo: (processo de pagamento P, credor C) → contrato do TCE-RJ. Cada OB Contabilizada de C em P
vira uma linha de `vinculo_ob_contrato`.

REGRA (determinística, primeiro): o texto dos documentos DECLARADOS no manifesto do acervo
(`data/sei_arquivo/<P>/`) cita o número SEI do processo de UM contrato do credor C (e só de um). A citação é o
trecho literal em volta do número, conferido por código (`verificacao.citacao_existe`) e reanalisado para
provar que o número está no trecho. Nunca vira VERIFICADO:
  · processo que cita processos de DOIS ou mais contratos do credor (vai ao modelo, ver abaixo);
  · processo do contrato com mais de um registro no TCE-RJ para o mesmo credor (vínculo ambíguo);
  · Termo de Ajuste de Contas / reconhecimento de dívida / indenização (natureza 339093): indenização não é
    pagamento do contrato — PENDENTE;
  · OB emitida mais de 30 dias antes do início do contrato citado: o processo paga outra coisa também — o
    par inteiro fica PENDENTE.
MODELO (só o que a regra não resolve, com citação dupla):
  · Haiku pela Batch API (balde `extracao_sei`), parte fixa em cache, JSON curto; duas leituras com a lista de
    candidatos em ordem diferente. VERIFICADO só se as DUAS leituras escolhem o mesmo processo, cada uma com
    citação literal achada no texto e o número do processo escolhido DENTRO da citação. Divergência,
    "mais de um contrato" ou citação que não confere = PENDENTE. PENDENTE nunca muda classe na perícia.
O que não está no acervo vira FILA DE CAPTURA (lista priorizada por valor pago) — nada é capturado daqui.

CLI:
  python -m compliance_agent.vinculo_ob_contrato regra [--gravar]
  python -m compliance_agent.vinculo_ob_contrato modelo --limite N [--controle K] [--gravar]
  python -m compliance_agent.vinculo_ob_contrato fila [--top N]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from compliance_agent import pericia_contabil as P
from compliance_agent.llm import verificacao as V

logger = logging.getLogger(__name__)

ARQUIVO = Path(os.environ.get("JFN_SEI_ARQUIVO", str(Path(P._DB).parent / "sei_arquivo")))
SAIDA_FILA = Path(P._DB).parent / "sei_fila_vinculo_ob.json"

REGRA, HAIKU, SONNET = "regra", "haiku", "sonnet"
TAREFA = "extracao_sei"
FOLGA_INICIO_DIAS = 30
JANELA_TRECHO = 160

DDL = """CREATE TABLE IF NOT EXISTS vinculo_ob_contrato (
    ob TEXT NOT NULL, ug TEXT NOT NULL, exercicio INTEGER NOT NULL,
    contrato_tcerj_id TEXT, processo_contrato TEXT, processo_pagamento TEXT, credor TEXT,
    fonte_doc TEXT, trecho TEXT, metodo TEXT, estado TEXT, motivo TEXT, data TEXT,
    PRIMARY KEY (ob, ug, exercicio))"""

# número SEI do processo: OOOOOO/NNNNNN/AAAA (ano de 2 ou 4 dígitos; separadores e sufixo de letra tolerados).
# Lookbehind de dígito: CNPJ (14 dígitos) e chaves longas não viram processo.
RE_PROC = re.compile(r"(?<!\d)(\d{6})[\s/.\-]*(\d{6})[A-Za-z]?[\s/.\-]*(\d{4}|\d{2})(?!\d)")
RE_TAC = re.compile(r"TERMO\s+DE\s+AJUSTE\s+DE\s+CONTAS|RECONHECIMENTO\s+DE\s+D[ÍI]VIDA|\b339093\b|"
                    r"INDENIZA[ÇC][ÃA]O\s+A\s+FORNECEDOR", re.I)


def _chave(m: re.Match) -> str:
    ano = m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)
    return m.group(1) + m.group(2) + ano


def _valida(m: re.Match) -> bool:
    """Sem separador, só a forma canônica de 16 dígitos (ano com 4): CNPJ colado (6+6+2) não é processo."""
    return not (m.group(0).isdigit() and len(m.group(3)) == 2)


def _achados(texto: str):
    return (m for m in RE_PROC.finditer(texto or "") if _valida(m))


def chaves_citadas(texto: str) -> set[str]:
    return {_chave(m) for m in _achados(texto)}


def formatar(chave: str) -> str:
    return f"{chave[:6]}/{chave[6:12]}/{chave[12:]}"


def pasta(chave: str) -> Path:
    return ARQUIVO / f"{chave[:6]}_{chave[6:12]}_{chave[12:]}"


def ler_docs(pst: Path) -> list[tuple[str, str]]:
    """[(fonte_doc, texto)] só dos documentos DECLARADOS no manifesto (pasta pode ter órfãos alheios)."""
    from compliance_agent.sei import acervo_texto as A
    try:
        man = json.loads((pst / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for d in man.get("docs") or []:
        if not isinstance(d, dict) or not d.get("texto"):
            continue
        t = A.ler(pst, d)
        if t.strip():
            out.append((f"{d.get('texto')} — {str(d.get('titulo') or '')[:120]}", t))
    return out


def trecho(texto: str, m: re.Match, janela: int = JANELA_TRECHO) -> str:
    return " ".join(texto[max(0, m.start() - janela):m.end() + janela].split())


# ── índice dos contratos e pares candidatos ──────────────────────────────────────────────────────────
def indice_contratos(con) -> tuple[dict, dict]:
    """({cnpj: {chave_processo: [ids]}}, {id: (inicio_ref, fim)}) — sem registro cancelado."""
    por_cred: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    info = {}
    for cid, proc, sn, dc, st, cnpj, vi, vf in con.execute(
            "SELECT id, processo, sei_norm, data_contratacao, status, cnpj, vig_inicio, vig_fim FROM contratos_tcerj"):
        k, c = P.chave_sei(sn or proc), P._digitos(cnpj)
        if not (k and c) or (st or "").strip() == "Cancelado":
            continue
        por_cred[c][k].append(cid)
        info[cid] = (min([d for d in (P.parse_data(vi), P.parse_data(dc)) if d], default=None), P.parse_data(vf))
    return por_cred, info


def pares_candidatos(con, por_cred: dict) -> dict[tuple, list]:
    """{(processo_pagamento, credor): [(ob, ug, exercicio, data, valor)]} — OB Contabilizada de credor com
    contrato, em processo que NÃO é o de nenhum contrato dele (essas a perícia já casa)."""
    pares: dict[tuple, list] = defaultdict(list)
    vistos = set()
    for num, ex, ug, dt, proc, cred, val in con.execute(
            "SELECT numero_ob, exercicio, ug_emitente, data_emissao, processo, credor, valor "
            "FROM ob_orcamentaria_siafe WHERE status='Contabilizado'"):
        c = P._digitos(cred)
        if c not in por_cred or not str(num or "").strip():
            continue
        k = P.chave_sei(proc)
        if not k or k in por_cred[c] or (num, ex, str(ug)) in vistos:
            continue
        vistos.add((num, ex, str(ug)))
        pares[(k, c)].append((str(num), str(ug), int(ex), P.parse_data(dt), float(val or 0)))
    return pares


# ── regra ────────────────────────────────────────────────────────────────────────────────────────────
def citacoes(docs: list[tuple[str, str]]) -> tuple[dict, tuple | None]:
    """Uma passada pelos autos: ({chave citada: (fonte, trecho, texto do doc)} na 1ª ocorrência, TAC ou None)."""
    todas: dict[str, tuple] = {}
    tac = None
    for fonte, texto in docs:
        if tac is None and (mt := RE_TAC.search(texto)):
            tac = (fonte, trecho(texto, mt))
        for m in _achados(texto):
            k = _chave(m)
            if k not in todas:
                todas[k] = (fonte, trecho(texto, m), texto)
    return todas, tac


def decidir_regra(docs: list[tuple[str, str]], proc_pag: str, contratos_do_credor: dict, *, lidas=None) -> dict:
    """Lê os autos de UM par. {'situacao': resolvido|varios|sem_citacao|ambiguo|tac|sem_texto, ...}.
    `lidas` = `citacoes(docs)` já calculado (o mesmo processo de pagamento serve a vários credores)."""
    if not docs:
        return {"situacao": "sem_texto"}
    todas, tac = lidas if lidas is not None else citacoes(docs)
    achados = {k: v for k, v in todas.items() if k != proc_pag and k in contratos_do_credor}
    if not achados:
        return {"situacao": "sem_citacao", "tac": tac}
    if len(achados) > 1:
        return {"situacao": "varios", "citadas": sorted(achados), "tac": tac}
    k, (fonte, tr, texto) = next(iter(achados.items()))
    # conferência por código: o trecho está no documento e o número está no trecho
    if not (V.citacao_existe(tr, texto) and k in chaves_citadas(tr)):
        return {"situacao": "sem_citacao", "tac": tac}
    ids = contratos_do_credor[k]
    base = {"chave": k, "fonte_doc": fonte, "trecho": tr, "tac": tac}
    if len(ids) != 1:
        return {**base, "situacao": "ambiguo", "ids": list(ids)}
    return {**base, "situacao": "resolvido", "id": ids[0]}


def linhas_do_par(proc_pag: str, credor: str, obs: list, cid: str | None, chave_ctr: str | None, info: dict,
                  fonte: str, tr: str, metodo: str, estado: str, motivo: str = "") -> list[tuple]:
    """Uma linha por OB. VERIFICADO só sobrevive se nenhuma OB do par antecede o contrato (folga de 30 dias)."""
    hoje = datetime.now().isoformat(timespec="seconds")
    if estado == V.VERIFICADO and cid:
        ini = info.get(cid, (None, None))[0]
        if ini is None:
            estado, motivo = V.PENDENTE, "contrato sem data de início registrada"
        elif any(o[3] and o[3] < ini - timedelta(days=FOLGA_INICIO_DIAS) for o in obs):
            estado, motivo = V.PENDENTE, ("OB do processo de pagamento anterior ao início do contrato citado — "
                                          "o processo paga outra coisa também")
    return [(o[0], o[1], o[2], cid, formatar(chave_ctr) if chave_ctr else None, formatar(proc_pag), credor,
             fonte, P.mascarar_textos({"objeto": tr})["objeto"][:600], metodo, estado, motivo, hoje)
            for o in obs]


def rodar_regra(con, *, por_cred=None, info=None, pares=None) -> tuple[list[tuple], dict, dict]:
    """(linhas, pares_para_o_modelo {par: citadas}, estatística)."""
    if por_cred is None:
        por_cred, info = indice_contratos(con)
    pares = pares if pares is not None else pares_candidatos(con, por_cred)
    linhas, ao_modelo = [], {}
    est = defaultdict(lambda: [0, 0.0])
    por_proc: dict[str, list] = defaultdict(list)
    for (pp, c) in pares:
        por_proc[pp].append(c)
    lidos = 0
    for pp, creds in por_proc.items():
        pst = pasta(pp)
        if not (pst / "manifest.json").exists():
            continue
        lidos += 1
        if lidos % 500 == 0:
            logger.info("regra: %d processos de pagamento lidos", lidos)
        docs = ler_docs(pst)
        lidas = citacoes(docs)
        for c in creds:
            obs = pares[(pp, c)]
            _um_par(pp, c, obs, decidir_regra(docs, pp, por_cred[c], lidas=lidas), info, linhas, ao_modelo, est)
    return linhas, ao_modelo, {k: (n, round(v, 2)) for k, (n, v) in est.items()}


def _um_par(pp, c, obs, d, info, linhas, ao_modelo, est) -> None:
    s = d["situacao"]
    valor = sum(o[4] for o in obs)
    if s == "resolvido" and d.get("tac"):
        s = "tac"
    est[s][0] += 1
    est[s][1] += valor
    if s == "resolvido":
        linhas += linhas_do_par(pp, c, obs, d["id"], d["chave"], info, d["fonte_doc"], d["trecho"], REGRA,
                                V.VERIFICADO)
    elif s == "ambiguo":
        linhas += linhas_do_par(pp, c, obs, None, d["chave"], info, d["fonte_doc"], d["trecho"], REGRA,
                                V.PENDENTE, f"processo do contrato com {len(d['ids'])} registros no TCE-RJ "
                                            "para o mesmo credor")
    elif s == "tac":
        fonte, tr = d["tac"]
        linhas += linhas_do_par(pp, c, obs, d.get("id"), d.get("chave"), info, fonte, tr, REGRA, V.PENDENTE,
                                "termo de ajuste de contas/indenização — não é pagamento do contrato")
    elif s == "varios":
        ao_modelo[(pp, c)] = d["citadas"]


# ── modelo (Haiku, Batch API, dupla leitura) ─────────────────────────────────────────────────────────
SISTEMA = (
    "Você lê autos de um PROCESSO DE PAGAMENTO do Governo do Estado do Rio de Janeiro (SEI) e diz qual CONTRATO "
    "esse processo paga, entre os processos de contrato candidatos listados. Regras:\n"
    "1. Responda só com o JSON pedido.\n"
    "2. 'processo_contrato' = o número de UM candidato no formato OOOOOO/NNNNNN/AAAA, ou \"\" (vazio) se o "
    "texto não permite afirmar qual contrato é pago.\n"
    "3. Se o processo paga MAIS DE UM dos candidatos, 'mais_de_um' = true e 'processo_contrato' = \"\".\n"
    "4. 'citacao' = trecho COPIADO LITERALMENTE do texto (até 300 caracteres), que contenha o número do processo "
    "escolhido e mostre que o pagamento se refere a ele. Nunca parafraseie, nunca corrija grafia.\n"
    "5. Um processo apenas mencionado como histórico, licitação de origem de outro contrato ou referência não "
    "é o contrato pago. Na dúvida, \"\".")
FORMATO = {"type": "object", "additionalProperties": False,
           "properties": {"processo_contrato": {"type": "string"}, "mais_de_um": {"type": "boolean"},
                          "citacao": {"type": "string"}},
           "required": ["processo_contrato", "mais_de_um", "citacao"]}
_RE_RELEVANTE = re.compile(r"contrat|processo|SEI|referente|objeto|vig[êe]ncia|compet[êe]ncia|pagamento", re.I)
_RE_LIGA_PAGAMENTO = re.compile(r"contrat|referente|pagamento|pagar|nota\s+fiscal|\bNF\b|empenho|liquida|atest|"
                                r"medi[çc][ãa]o|compet[êe]ncia|fatura", re.I)
TETO_EXCERTO = 9000
# piloto de 14/11/2026: com 400, 79 de 400 leituras cortadas — o raciocínio adaptativo do Haiku consome o max_tokens
MAX_TOKENS = 2500


def excerto(docs: list[tuple[str, str]], teto: int = TETO_EXCERTO, candidatos=()) -> str:
    """Recorte LITERAL dos autos (linhas inteiras, para a citação continuar conferível). Primeiro, a vizinhança
    (± 3 linhas) de cada linha que cita um processo candidato — piloto de 14/11/2026: com só as primeiras linhas
    "relevantes", a citação do contrato ficava fora dos 9.000 caracteres e o modelo se abstinha; depois, as
    demais linhas relevantes (± 1 linha), até o teto."""
    alvo = set(candidatos)
    partes, total, vistas = [], 0, set()

    def juntar(fonte, ls, idx):
        nonlocal total
        bloco = [ls[i] for i in sorted(idx) if ls[i].strip() and (fonte, i) not in vistas]
        vistas.update((fonte, i) for i in idx)
        if not bloco or total >= teto:
            return
        b = f"### {fonte}\n" + "\n".join(bloco)
        b = b[:max(0, teto - total - 2)]           # 2 = o separador entre blocos
        partes.append(b)
        total += len(b) + 2

    linhas = [(f, t.splitlines()) for f, t in docs]
    if alvo:
        for fonte, ls in linhas:
            idx = {j for i, l in enumerate(ls) if chaves_citadas(l) & alvo
                   for j in range(i - 3, i + 4) if 0 <= j < len(ls)}
            juntar(fonte, ls, idx)
    for fonte, ls in linhas:
        idx = {j for i, l in enumerate(ls) if _RE_RELEVANTE.search(l) or RE_PROC.search(l)
               for j in (i - 1, i, i + 1) if 0 <= j < len(ls)}
        juntar(fonte, ls, idx)
    return "\n\n".join(partes)


def prompt(proc_pag: str, candidatos: list[str], exc: str, inverter: bool) -> str:
    cand = list(reversed(candidatos)) if inverter else list(candidatos)
    return (f"Processo de pagamento: {formatar(proc_pag)}\nCandidatos (processos de contrato do credor):\n"
            + "\n".join(f"- {formatar(k)}" for k in cand) + f"\n\nTEXTO DOS AUTOS:\n{exc}")


def conferir_leitura(resp: str | None, candidatos: list[str], fonte_total: str) -> tuple[str | None, str, str]:
    """(chave, citação, motivo). chave None = leitura que não sustenta vínculo."""
    if not resp:
        return None, "", "leitura vazia/cortada/recusada"
    try:
        j = json.loads(resp)
    except ValueError:
        return None, "", "resposta sem JSON"
    if j.get("mais_de_um"):
        return None, j.get("citacao") or "", "o processo paga mais de um contrato"
    pc = j.get("processo_contrato")
    cit = j.get("citacao") or ""
    k = next(iter(chaves_citadas(pc or "")), None)
    if not k or k not in candidatos:
        return None, cit, "modelo não escolheu candidato"
    if not V.citacao_existe(cit, fonte_total):
        return None, cit, "citação não encontrada literalmente nos autos"
    if k not in chaves_citadas(cit):
        return None, cit, "o número do processo escolhido não está no trecho citado"
    if not _RE_LIGA_PAGAMENTO.search(cit):
        # piloto de 14/11/2026: "PROCESSO Nº SEI-…/2025." sozinho, entre dois contratos citados, não prova qual é pago
        return None, cit, "a citação não liga o pagamento ao processo escolhido"
    return k, cit, ""


def id_par(pp: str, credor: str) -> str:
    """custom_id ESTÁVEL do lote (processo + credor), nunca a posição: resultado colhido depois — ou relido de um
    lote já pago — não pode cair no par errado (14/11/2026: reler o piloto por posição trocou os pares)."""
    return f"{pp}_{re.sub(r'[^0-9A-Za-z]', '', credor)}"[:60]


def montar_itens(pares: dict, candidatos_de: dict | None = None) -> tuple[list, dict]:
    itens, contexto = [], {}
    for (pp, c), cand in pares.items():
        docs = ler_docs(pasta(pp))
        exc = excerto(docs, candidatos=cand)
        pid = id_par(pp, c)
        contexto[pid] = ((pp, c), cand, "\n".join(t for _, t in docs))
        itens.append((pid + "a", prompt(pp, cand, exc, False)))
        itens.append((pid + "b", prompt(pp, cand, exc, True)))
    return itens, contexto


def decidir_modelo(saida: dict, contexto: dict) -> dict:
    """{par: (chave|None, citação, estado, motivo)} a partir das duas leituras."""
    out = {}
    for pid, (par, cand, total) in contexto.items():
        ka, ca, ma = conferir_leitura(saida.get(pid + "a"), cand, total)
        kb, cb, mb = conferir_leitura(saida.get(pid + "b"), cand, total)
        est = V.estado_dupla_leitura(ka, kb)
        if est == V.VERIFICADO:
            out[par] = (ka, ca, V.VERIFICADO, "")
        else:
            motivo = ("as duas leituras divergem" if ka and kb else (ma or mb or "sem vínculo afirmável"))
            out[par] = (ka or kb, ca or cb, V.PENDENTE if (ka or kb) else V.INDISPONIVEL, motivo)
    return out


def rodar_modelo(pares: dict, *, modelo: str | None = None, espera_max: int = 3600) -> tuple[dict, dict]:
    from compliance_agent.llm import claude_api as C
    itens, contexto = montar_itens(pares)
    lote = C.enviar_lote(TAREFA, itens, sistema=SISTEMA, modelo=modelo, max_tokens=MAX_TOKENS, effort="low",
                         formato=FORMATO, n_decisoes=len(pares))
    if not lote:
        raise RuntimeError(C.ultimo_motivo or "lote não enviado")
    logger.info("lote %s enviado (%d leituras)", lote, len(itens))
    t0 = time.time()
    while True:
        saida = C.colher_lote(lote)
        if saida is not None:
            break
        if time.time() - t0 > espera_max:
            raise TimeoutError(f"lote {lote} não terminou em {espera_max} s — colher depois")
        time.sleep(30)
    return decidir_modelo(saida, contexto), {"lote": lote, "leituras": len(itens)}


# ── gravação ─────────────────────────────────────────────────────────────────────────────────────────
def gravar(db: str | Path, linhas: list[tuple], *, preservar_regra: bool = True) -> int:
    """INSERT OR REPLACE, numa transação curta. Linha do modelo nunca sobrescreve linha da regra."""
    con = sqlite3.connect(str(db), timeout=120)
    try:
        con.execute(DDL)
        n = 0
        with con:
            for ln in linhas:
                if preservar_regra and ln[9] != REGRA and con.execute(
                        "SELECT 1 FROM vinculo_ob_contrato WHERE ob=? AND ug=? AND exercicio=? AND metodo=?",
                        (ln[0], ln[1], ln[2], REGRA)).fetchone():
                    continue
                con.execute("INSERT OR REPLACE INTO vinculo_ob_contrato VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", ln)
                n += 1
        return n
    finally:
        con.close()


def vinculos_verificados(con) -> dict[tuple, str]:
    """{(ob, exercicio, ug): contrato_tcerj_id} — só VERIFICADO. Sem a tabela: {} (a perícia segue como antes)."""
    if not P._tem(con, "vinculo_ob_contrato"):
        return {}
    return {(ob, int(ex), str(ug)): cid for ob, ex, ug, cid in con.execute(
        "SELECT ob, exercicio, ug, contrato_tcerj_id FROM vinculo_ob_contrato "
        "WHERE estado='VERIFICADO' AND contrato_tcerj_id IS NOT NULL")}


# ── fila de captura (só a LISTA; quem captura é a VM-2) ──────────────────────────────────────────────
# Raízes de CNPJ que nunca são o contratado (União/Fazenda, tributo/repasse) — a mesma lista de
# `tools.sei_fila_por_dinheiro._RAIZES_NAO_CONTRATADO`, repetida aqui para o pacote não importar `tools`.
RAIZES_NAO_CONTRATADO = {"00394460", "42498600", "42498733"}
CARENCIA_FIM_DIAS = 60


def fila_captura(pares: dict, contratos_indet: dict[str, list], top: int | None = None) -> list[dict]:
    """Processos de pagamento NÃO arquivados que podem tirar contrato de INDETERMINADO, em ordem de valor.

    `contratos_indet` = {credor: [(início, fim, valor do contrato)]} dos contratos INDETERMINADOS por OB fora do
    processo. Conta só a OB Contabilizada do credor emitida dentro da vigência de algum desses contratos (fim +
    60 dias; fim desconhecido = aberto), e o ESCORE de cada par é o menor entre esse valor pago e a soma dos valores
    dos contratos cuja vigência a OB toca — sem o teto, o banco que recebe a folha (bilhões em OB) e a União
    (tributo) ocupavam o topo da fila sem ter contrato desse tamanho para resolver (medido em 14/11/2026)."""
    from compliance_agent.sei import acervo_texto as A
    agg: dict[str, dict] = {}
    for (pp, c), obs in pares.items():
        if c not in contratos_indet or c[:8] in RAIZES_NAO_CONTRATADO:
            continue
        janelas = contratos_indet[c]
        tocados, val = set(), []
        for o in obs:
            if not o[3]:
                continue
            hit = [k for k, (ini, fim, _v) in enumerate(janelas) if ini and o[3] >= ini
                   and (fim is None or o[3] <= fim + timedelta(days=CARENCIA_FIM_DIAS))]
            if hit:
                tocados.update(hit)
                val.append(o)
        if not val:
            continue
        pago = sum(o[4] for o in val)
        teto = sum(float(janelas[k][2] or 0) for k in tocados)
        e = agg.setdefault(pp, {"score": 0.0, "valor": 0.0, "n_ob": 0, "credores": set()})
        e["score"] += min(pago, teto)
        e["valor"] += pago
        e["n_ob"] += len(val)
        e["credores"].add(c)
    out = []
    for pp, e in sorted(agg.items(), key=lambda x: -x[1]["score"]):
        if e["score"] <= 0:
            continue
        pst = pasta(pp)
        if (pst / "manifest.json").exists() and A.docs_com_conteudo(pst) > 0:
            continue
        out.append({"sei": f"SEI-{formatar(pp)}", "score": round(e["score"], 2), "valor_ob": round(e["valor"], 2),
                    "n_ob": e["n_ob"], "cnpj": sorted(e["credores"])[0], "n_credores": len(e["credores"]),
                    "tipo": "VINCULO_OB", "flags": ["FILA_VINCULO_OB_CONTRATO"],
                    "motivo": "processo de pagamento de credor com contrato INDETERMINADO na perícia contábil"})
        if top and len(out) >= top:
            break
    return out


MOTIVOS_FORA = ("ob_do_credor_fora_do_processo", "a_menor_com_ob_fora_do_processo")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("acao", choices=("regra", "modelo", "fila"))
    ap.add_argument("--db", default=P._DB)
    ap.add_argument("--gravar", action="store_true")
    ap.add_argument("--limite", type=int, default=0, help="modelo: nº máximo de pares (por valor pago)")
    ap.add_argument("--controle", type=int, default=0,
                    help="modelo: pares JÁ resolvidos pela regra relidos como controle positivo")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--cache", help="regra grava aqui o que vai ao modelo; modelo lê daqui (evita reler o acervo)")
    a = ap.parse_args(argv)
    con = P._con_ro(a.db)
    por_cred, info = indice_contratos(con)
    pares = pares_candidatos(con, por_cred)
    if a.acao == "fila":
        con.close()
        res = P.avaliar_estado(a.db)
        valor_de = {r["id"]: r["valor_atualizado"] for r in res if r["motivo"] in MOTIVOS_FORA}
        indet: dict[str, list] = {}
        for c, procs in por_cred.items():
            js = [(*info[i], valor_de[i]) for ids in procs.values() for i in ids if i in valor_de]
            if js:
                indet[c] = js
        fila = fila_captura(pares, indet)
        gravar_fila = fila[:a.top] if a.top else fila
        SAIDA_FILA.write_text(json.dumps(gravar_fila, ensure_ascii=False, indent=0), encoding="utf-8")
        print(json.dumps({"processos": len(fila), "gravados": len(gravar_fila),
                          "escore_total": round(sum(e["score"] for e in fila), 2),
                          "valor_ob_total": round(sum(e["valor_ob"] for e in fila), 2),
                          "escore_gravados": round(sum(e["score"] for e in gravar_fila), 2),
                          "credores_com_indeterminado": len(indet), "gravado": str(SAIDA_FILA),
                          "top10": fila[:10]}, ensure_ascii=False, indent=1))
        return 0
    if a.acao == "modelo" and a.cache and Path(a.cache).exists():
        con.close()
        cache = json.loads(Path(a.cache).read_text(encoding="utf-8"))
        ao_modelo = {(pp, c): cand for pp, c, cand in cache["ao_modelo"]}
        resolvidos = {(pp, c): k for pp, c, k in cache["resolvidos"]}
    else:
        linhas, ao_modelo, est = rodar_regra(con, por_cred=por_cred, info=info, pares=pares)
        con.close()
        resolvidos = {(P.chave_sei("SEI-" + ln[5]), ln[6]): P.chave_sei("SEI-" + ln[4])
                      for ln in linhas if ln[9] == REGRA and ln[10] == V.VERIFICADO}
        if a.cache:
            Path(a.cache).write_text(json.dumps({
                "ao_modelo": [[pp, c, cand] for (pp, c), cand in ao_modelo.items()],
                "resolvidos": [[pp, c, k] for (pp, c), k in resolvidos.items()]}), encoding="utf-8")
    if a.acao == "regra":
        print(json.dumps({"pares_por_situacao": est, "linhas": len(linhas),
                          "verificadas": sum(1 for x in linhas if x[10] == V.VERIFICADO),
                          "ao_modelo": len(ao_modelo)}, ensure_ascii=False, indent=1))
        if a.gravar:
            print("gravadas", gravar(a.db, linhas))
        return 0
    # modelo: os pares que a regra mandou (vários contratos citados), por valor pago; + controle positivo
    valor = {par: sum(o[4] for o in pares[par]) for par in ao_modelo}
    alvo = dict(sorted(ao_modelo.items(), key=lambda x: -valor[x[0]])[:a.limite or None])
    gab = {}
    if a.controle:
        # controle positivo: pares que a regra resolveu, de credor com 2+ contratos (escolha não trivial)
        for par, k in sorted((p_, k_) for p_, k_ in resolvidos.items() if len(por_cred[p_[1]]) > 1)[:a.controle]:
            outros = sorted(por_cred[par[1]])[:12]
            alvo[par] = sorted(set(outros) | {k})
            gab[par] = k
    decisoes, meta = rodar_modelo(alvo)
    acertos = sum(1 for par, k in gab.items() if decisoes[par][0] == k and decisoes[par][2] == V.VERIFICADO)
    erros = sum(1 for par, k in gab.items() if decisoes[par][0] not in (None, k))
    novas = []
    for par, (k, cit, estado, motivo) in decisoes.items():
        if par in gab:
            continue
        ids = por_cred[par[1]].get(k, []) if k else []
        if estado == V.VERIFICADO and len(ids) != 1:
            estado, motivo = V.PENDENTE, "processo do contrato com mais de um registro no TCE-RJ"
        if estado == V.INDISPONIVEL:
            continue
        novas += linhas_do_par(par[0], par[1], pares[par], ids[0] if len(ids) == 1 else None, k, info,
                               "leitura do modelo (dupla)", cit, HAIKU, estado, motivo)
    from compliance_agent.llm import claude_api as C
    print(json.dumps({**meta, "pares": len(alvo), "controle": len(gab), "controle_acertos": acertos,
                      "controle_erros": erros,
                      "decisoes": {e: sum(1 for d in decisoes.values() if d[2] == e) for e in
                                   (V.VERIFICADO, V.PENDENTE, V.INDISPONIVEL)},
                      "linhas": len(novas), "balde": C.painel()["baldes"]["extracao_sei"]},
                     ensure_ascii=False, indent=1, default=str))
    if a.gravar:
        print("gravadas", gravar(a.db, novas))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
