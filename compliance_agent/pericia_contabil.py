# -*- coding: utf-8 -*-
"""Perícia contábil de TODOS os contratos: valor DEVIDO até a data de corte × valor PAGO.

Pergunta do dono (2026-11-13): "quero saber se os valores deles foram pagos a maior ou a menor, até o
presente momento". Cada contrato sai em UMA de cinco classes — CONFORME, A_MAIOR, A_MENOR_ENCERRADO,
A_MENOR_EM_CURSO ou INDETERMINADO (sempre com o motivo) — e as esferas NUNCA se misturam.

ESTADO (Governo do RJ)
  · Contratos: `contratos_tcerj` (dados abertos do TCE-RJ — a única fonte dos contratos do executivo
    estadual; ver `contratos/estado.py`).
  · Pago: SÓ Ordem Bancária do SIAFE (`ob_orcamentaria_siafe`) com status `Contabilizado`. Anulada,
    Excluída e Não contabilizada NÃO são pagamento (a soma sem filtro já inflou totais em bilhões —
    `tests/test_catraca_ob_so_contabilizada.py`). Empenho e liquidação nunca entram.
  · Vínculo OB↔contrato: o MESMO que a casa já usa (`territorio/atribui_estado._pagamentos`,
    `contratos/estado._pagamentos_por_processo`) — par (processo SEI, CNPJ do credor) apontando para
    UM único contrato. Duas correções sobre aquele vínculo, ambas medidas na base real:
      1. o SIAFE grava parte dos processos com ANO DE DOIS DÍGITOS (`SEI-330002/031566/24`); só dígitos
         não casa com o `sei_norm` do TCE-RJ — `chave_sei` canoniza os dois lados;
      2. OB com o mesmo `numero_ob` em outra UG é OUTRA OB (`siafe-pk-numero-ob-apagava-outra-ug`):
         a deduplicação é por (numero_ob, exercicio, ug_emitente), nunca pelo número sozinho.
    Par que aponta para mais de um contrato → INDETERMINADO (dividir a soma seria inventar número).
    OB do credor só em OUTRO processo → INDETERMINADO: no RJ o pagamento corre muitas vezes em processo
    próprio, e atribuí-lo ao contrato por credor seria palpite. INDISPONÍVEL ≠ zero.
  · Cobertura: OB do SIAFE de 2021 em diante. Vigência iniciada antes disso → INDETERMINADO.
    "A menor" só se afirma quando o par (UG, ano) não está parcial (`reporting/cobertura_siafe`);
    "a maior" sobrevive a cobertura parcial, porque o pago medido é PISO.

PREFEITURA DO RIO
  · Contratos e pago: `contasrio_contrato` (Contas Rio / SIAFIC-Rio, consulta pública CCON). O SIAFE é
    do Estado; o município paga pelo SIAFIC-Rio, e o `total_pago` publicado ali é o pago contabilizado
    por contrato — o vínculo é nativo (não há atribuição). Data de corte = data da coleta.

VALOR DEVIDO
  · valor atualizado = valor original + termos (aditivo/apostilamento/reajuste) publicados. Estado: o
    TCE-RJ não publica termos; quando o PNCP publica (`contrato_aditivo`), o valor global do último
    termo prevalece e a vigência prorrogada é usada. Prefeitura: `valor_atualizado` do Contas Rio.
  · prestação continuada → pró-rata da vigência decorrida até o corte; demais → valor global.
  · tolerância: |diferença| < 1% do devido OU < R$ 1.000,00 = CONFORME (parâmetros abaixo).
  · acréscimo acima do teto (25%; 50% em reforma) é indício por si — régua única em `limites_aditivo`,
    lei citada pela data do contrato (8.666/93 art. 65 §1º · 14.133/21 art. 125).

CLI:  python -m compliance_agent.pericia_contabil --saida <pasta> [--db ...] [--pcrj-db ...] [--sem-pdf]
"""
from __future__ import annotations

import argparse
import csv
import html as _html
import os
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from compliance_agent import limites_aditivo

_BASE = Path(__file__).resolve().parent.parent
_DB = os.environ.get("JFN_DB", str(_BASE / "data" / "compliance.db"))
_DB_PCRJ = os.environ.get("JFN_PCRJ_DB", str(_BASE / "data" / "pcrj.db"))

# ── parâmetros declarados no relatório ───────────────────────────────────────────────────────
TOL_PCT = 0.01            # 1% do devido
TOL_ABS = 1_000.00        # R$ 1.000,00
INICIO_COBERTURA_SIAFE = date(2021, 1, 1)
VIGENCIA_PADRAO_DIAS = 370  # acima disso, contrato contínuo sem termo publicado pode ter prorrogação oculta

ESTADO = "Estado do RJ"
PREFEITURA = "Prefeitura do Rio"

CATEGORIAS = ("A_MAIOR", "A_MENOR_ENCERRADO", "A_MENOR_EM_CURSO", "CONFORME", "INDETERMINADO")
ROTULO = {
    "A_MAIOR": "Pago a maior", "A_MENOR_ENCERRADO": "Pago a menor — vigência encerrada",
    "A_MENOR_EM_CURSO": "Pago a menor — em curso", "CONFORME": "Conforme",
    "INDETERMINADO": "Indeterminado",
}
MOTIVOS = {
    "registro_cancelado": "registro do contrato cancelado na fonte",
    "valor_contrato_ausente": "valor do contrato não registrado (ou zero)",
    "credor_sem_documento": "credor sem CPF/CNPJ registrado",
    "processo_sem_sei": "processo sem número SEI canônico — sem chave de vínculo com a OB",
    "vinculo_ambiguo": "o par (processo, credor) aponta para mais de um contrato — OB não atribuível sem palpite",
    "vigencia_anterior_a_cobertura": "vigência iniciada antes de 2021, fora da cobertura do SIAFE",
    "vigencia_nao_registrada": "contrato contínuo sem vigência registrada — pró-rata inaferível",
    "ob_do_credor_fora_do_processo": "o credor recebeu OB, mas só em processo diverso do contrato — "
                                     "pagamento possivelmente em processo próprio; vínculo indeterminável",
    "a_menor_com_ob_fora_do_processo": "pago no processo abaixo do devido, mas o credor recebeu outras OBs na "
                                       "mesma UG em outro processo — o 'a menor' não se sustenta",
    "cobertura_siafe_parcial": "pago no processo abaixo do devido, mas a coleta do SIAFE está parcial na "
                               "UG/exercício — o pago é piso",
    "inicio_nao_registrado": "sem data de início da vigência nem de contratação",
    "registro_de_termo": "o registro é termo de alteração (reequilíbrio/aditivo/apostilamento/prorrogação), "
                         "não o contrato — as OBs do processo pagam o contrato-mãe",
}
SUBTIPO = {"acima_do_valor_global": "acima do valor global atualizado",
           "acima_do_pro_rata": "acima do pró-rata decorrido (dentro do valor global)"}

# ── normalização ─────────────────────────────────────────────────────────────────────────────
_RE_SEI = re.compile(r"SEI[\s\-]*(\d{6})[\s/\-]*(\d{6})[\s/\-]*(\d{4}|\d{2})(?!\d)", re.I)
_RE_SEI_NORM = re.compile(r"^\d{16}$")


def chave_sei(processo: str | None) -> str | None:
    """`SEI-OOOOOO/NNNNNN/AAAA` (ou ano com 2 dígitos) → 16 dígitos. Numeração antiga (E-…) → None."""
    s = str(processo or "").strip().lstrip("*").strip()
    if _RE_SEI_NORM.match(s):
        return s
    m = _RE_SEI.search(s)
    if not m:
        return None
    ano = m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)
    return m.group(1) + m.group(2) + ano


def parse_data(s: Any) -> date | None:
    """DD/MM/AAAA (SIAFE, TCE-RJ, Contas Rio) ou ISO com/sem 'T'. Texto inválido → None."""
    t = str(s or "").strip()
    if not t:
        return None
    try:
        if re.match(r"^\d{2}/\d{2}/\d{4}", t):
            return datetime.strptime(t[:10], "%d/%m/%Y").date()
        if re.match(r"^\d{4}-\d{2}-\d{2}", t):
            return datetime.strptime(t[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return None


def _digitos(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


def mascarar_doc(doc: Any) -> str:
    """CPF sempre mascarado (LGPD, regra da casa); CNPJ formatado."""
    d = _digitos(doc)
    if len(d) == 11:
        return f"{d[:3]}.***.***-{d[-2:]}"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return d


# ── natureza e regime ────────────────────────────────────────────────────────────────────────
_RE_CONTINUA = re.compile(
    r"CONT[ÍI]NU|PRESTA[ÇC][ÃA]O\s+DE\s+SERVI|SERVI[ÇC]OS?\s+DE\s+(LIMPEZA|VIGIL|MANUTEN|CONSERVA|"
    r"APOIO|TRANSPORTE|ALIMENTA|LAVANDERIA|PORTARIA|RECEP|COPEIRAG|TELEFONIA|INTERNET|GEST)|"
    r"LOCA[ÇC][ÃA]O|ALUGUEL|VIGIL[ÂA]NCIA|LIMPEZA|M[ÃA]O\s+DE\s+OBRA|TERCEIRIZ|GERENCIAMENTO|"
    r"MANUTEN[ÇC][ÃA]O\s+(PREVENTIVA|CORRETIVA|PREDIAL)|OUTSOURCING|LICEN[ÇC]A\s+DE\s+USO|SUBSCRI|"
    r"ASSINATURA|OPERA[ÇC][ÃA]O\s+E\s+MANUTEN|GEST[ÃA]O\s+(DE|DA|DO)\s", re.I)
_RE_PONTUAL = re.compile(r"AQUISI[ÇC]|COMPRA\b|\bOBRAS?\b|REFORMA|CONSTRU[ÇC]|FORNECIMENTO\s+DE", re.I)


_RE_UTILIDADE = re.compile(r"ENERGIA\s+EL[ÉE]TRICA|[ÁA]GUA\s+E\s+(COLETA\s+DE\s+)?ESGOTO|G[ÁA]S\s+CANALIZADO|"
                           r"FORNECIMENTO\s+DE\s+([ÁA]GUA|ENERGIA|G[ÁA]S)|SANEAMENTO\s+B[ÁA]SICO|"
                           r"TELEFONIA|SEGURO\s+(PATRIMONIAL|DE\s+VE[ÍI]CULO|PREDIAL)", re.I)
# Registro que é o TERMO de alteração, não o contrato: medido na base real (2026-11-13) — um
# "contrato" de R$ 30,5 mi cujo objeto é "o reequilíbrio econômico-financeiro do valor contratual"
# recebia como "pago" todas as OBs do contrato-mãe do mesmo processo (R$ 72,5 mi → falso "a maior").
_RE_TERMO = re.compile(r"REEQUIL[ÍI]BRIO\s+ECON|TERMO\s+ADITIVO|APOSTILAMENTO|REPACTUA[ÇC][ÃA]O|"
                       r"PRORROGA[ÇC][ÃA]O\s+(DO\s+PRAZO|DA\s+VIG|DO\s+CONTRATO)", re.I)
# Parceria/repasse (OS, OSC, contrato de gestão, fomento): o desembolso ANTECIPADO é da natureza do
# instrumento — "acima do pró-rata" ali não é indício de antecipação irregular por si.
_RE_PARCERIA = re.compile(r"CONTRATO\s+DE\s+GEST[ÃA]O|ORGANIZA[ÇC][ÃA]O\s+(SOCIAL|DA\s+SOCIEDADE\s+CIVIL)|"
                          r"TERMO\s+DE\s+(COLABORA|FOMENTO)|\bREPASSE\b|GERENCIAMENTO,?\s+OPERACIONALIZA", re.I)


def e_registro_de_termo(objeto: str | None) -> bool:
    return bool(_RE_TERMO.search(objeto or ""))


def e_parceria(objeto: str | None) -> bool:
    return bool(_RE_PARCERIA.search(objeto or ""))


def e_continuada(objeto: str | None) -> bool:
    """Heurística declarada: aquisição/obra é pontual, salvo se o objeto diz 'contínuo' ou é
    serviço público de fornecimento continuado (energia, água/esgoto, gás, telefonia, seguro)."""
    o = objeto or ""
    if not o.strip():
        return False
    if _RE_UTILIDADE.search(o):
        return True
    if _RE_PONTUAL.search(o) and not re.search(r"CONT[ÍI]NU", o, re.I):
        return False
    return bool(_RE_CONTINUA.search(o))


_INICIO_14133 = date(2021, 4, 1)
_FIM_TRANSICAO = date(2023, 12, 30)   # Lei 14.133/21, art. 191 c/c LC 198/2023


def regime_legal(d: date | None) -> tuple[str, str]:
    """Regime do contrato pela data — a lei do teto de acréscimo citada na peça."""
    a8666 = limites_aditivo.ato_normativo("8666")
    a14133 = limites_aditivo.ato_normativo("14133")
    if d is None:
        return "indeterminado", f"{a8666} ou {a14133} (data não registrada; teto idêntico)"
    if d < _INICIO_14133:
        return "8666", a8666
    if d <= _FIM_TRANSICAO:
        return "transicao", f"{a8666} ou {a14133} (regime de transição, art. 191; teto idêntico)"
    return "14133", a14133


# ── devido e classificação ───────────────────────────────────────────────────────────────────

def valor_devido(valor_atualizado: float, continuada: bool, inicio: date | None, fim: date | None,
                 corte: date) -> tuple[float | None, str]:
    """`(devido, critério)`. Contínuo → pró-rata dos dias decorridos (inclusive) sobre a vigência."""
    if not continuada:
        return float(valor_atualizado), "valor global atualizado (objeto de execução não continuada)"
    if not inicio or not fim or fim < inicio:
        return None, "prestação continuada sem vigência registrada: pró-rata inaferível"
    total = (fim - inicio).days + 1
    if corte < inicio:
        return 0.0, f"pró-rata: vigência ainda não iniciada no corte (0/{total} dias)"
    decorridos = min((min(corte, fim) - inicio).days + 1, total)
    v = float(valor_atualizado) * decorridos / total
    return v, f"pró-rata da vigência decorrida ({decorridos}/{total} dias)"


RAZAO_DESPROPORCIONAL = 100.0


def desproporcional(valor: float, pago: float) -> bool:
    """Valor registrado e pago a duas ordens de grandeza um do outro → erro de registro provável.

    Medido na base real (2026-11-13): no Contas Rio, um evento de R$ 2.388.161,80 pago estava registrado
    com valor de R$ 2.388.161.800,00 (×1.000), e locações de veículo com R$ 2,1 bi de valor e R$ 220 mil
    pagos. Classificar isso como "a menor" punha R$ bilhões de déficit fictício no consolidado. Não se
    esconde: o caso vai a INDETERMINADO com lista própria no relatório."""
    if not pago or pago <= 0 or not valor or valor <= 0:
        return False
    return valor / pago >= RAZAO_DESPROPORCIONAL or pago / valor >= RAZAO_DESPROPORCIONAL


def dentro_da_tolerancia(diferenca: float, devido: float) -> bool:
    d = abs(diferenca)
    return d < TOL_ABS or (devido > 0 and d < TOL_PCT * devido)


def classificar(pago: float, devido: float, valor_global: float, *,
                encerrado: bool) -> tuple[str, str, float]:
    """`(categoria, subtipo, diferença = pago − devido)`."""
    dif = float(pago) - float(devido)
    if dentro_da_tolerancia(dif, devido):
        return "CONFORME", "", dif
    if dif > 0:
        excede_global = not dentro_da_tolerancia(pago - valor_global, valor_global) and pago > valor_global
        return "A_MAIOR", ("acima_do_valor_global" if excede_global else "acima_do_pro_rata"), dif
    return ("A_MENOR_ENCERRADO" if encerrado else "A_MENOR_EM_CURSO"), "", dif


# ── Estado: carga ────────────────────────────────────────────────────────────────────────────

def _con_ro(db: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)


def _tem(con, tabela: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
                       (tabela,)).fetchone() is not None


def corte_siafe(con) -> date | None:
    """Data da OB contabilizada mais recente — 'até o presente momento' é até onde a coleta chega."""
    ex = con.execute("SELECT MAX(exercicio) FROM ob_orcamentaria_siafe "
                     "WHERE status='Contabilizado'").fetchone()[0]
    if ex is None:
        return None
    r = con.execute(
        "SELECT MAX(substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)) "
        "FROM ob_orcamentaria_siafe WHERE status='Contabilizado' AND exercicio=?", (ex,)).fetchone()[0]
    return parse_data(r)


def _obs_por_credor(con, credores: set[str]) -> tuple[dict, dict]:
    """OB contabilizada por credor, deduplicada por (numero_ob, exercicio, ug_emitente)."""
    vistos: set = set()
    por_credor: dict[str, list] = defaultdict(list)
    for num, ex, ug, dt, proc, cred, val, nl, comp in con.execute(
            "SELECT numero_ob, exercicio, ug_emitente, data_emissao, processo, credor, valor, nl, competencia "
            "FROM ob_orcamentaria_siafe WHERE status='Contabilizado'"):
        c = _digitos(cred)
        if c not in credores:
            continue
        k = (num, ex, str(ug))
        if k in vistos:
            continue
        vistos.add(k)
        # (data, chave do processo, UG, valor, NL, competência, número da OB)
        por_credor[c].append((parse_data(dt), chave_sei(proc), str(ug), float(val or 0), nl or "", comp or "", num))
    # contagem das não contabilizadas por (processo, credor) — informativo, NUNCA somado
    nao_contab: dict[tuple, int] = defaultdict(int)
    for proc, cred in con.execute(
            # ob-qualquer-status: só CONTA as anuladas/excluídas para o relatório declarar o que excluiu
            "SELECT processo, credor FROM ob_orcamentaria_siafe WHERE status<>'Contabilizado'"):
        c = _digitos(cred)
        if c in credores:
            nao_contab[(chave_sei(proc), c)] += 1
    return por_credor, nao_contab


def _termos_pncp(con, chaves: set[tuple]) -> dict[tuple, dict]:
    """(chave SEI, CNPJ) → termos publicados no PNCP para o contrato. Só fecha par → contrato único."""
    if not (_tem(con, "contrato_aditivo") and _tem(con, "pcrj_contratos")):
        return {}
    termos: dict[str, list] = defaultdict(list)
    for r in con.execute(
            "SELECT numero_controle_pncp, sequencial_termo, objeto, valor_acrescido, valor_global, "
            "prazo_aditado_dias, vigencia_fim, qualif_acrescimo, qualif_vigencia, qualif_reajuste, "
            "fundamento_legal, data_assinatura, tipo_termo, processo FROM contrato_aditivo"):
        if chave_sei(r[13]):
            termos[r[0]].append(r)
    if not termos:
        return {}
    ctrl = list(termos)
    base: dict[str, tuple] = {}
    for i in range(0, len(ctrl), 500):
        lote = ctrl[i:i + 500]
        for r in con.execute(
                "SELECT numero_controle_pncp, fornecedor_documento, valor_inicial, valor_global, vigencia_fim "
                f"FROM pcrj_contratos WHERE numero_controle_pncp IN ({','.join('?' * len(lote))})", lote):
            base[r[0]] = r
    por_par: dict[tuple, list] = defaultdict(list)
    for nc, ts in termos.items():
        if nc not in base:
            continue
        par = (chave_sei(ts[0][13]), _digitos(base[nc][1]))
        if par in chaves:
            por_par[par].append(nc)
    out = {}
    for par, ncs in por_par.items():
        if len(ncs) != 1:          # dois contratos PNCP no mesmo par: não escolher
            continue
        nc = ncs[0]
        ts = sorted(termos[nc], key=lambda t: (t[1] or 0, t[11] or ""))
        globais = [t[4] for t in ts if t[4]]
        fins = [parse_data(t[6]) for t in ts if parse_data(t[6])]
        out[par] = {
            "controle_pncp": nc, "valor_inicial": base[nc][2],
            "valor_global": globais[-1] if globais else base[nc][3],
            "vigencia_fim": max(fins) if fins else parse_data(base[nc][4]),
            "n_termos": len(ts),
            "aditivos": [{"objeto": t[2], "valor_acrescido": t[3], "prazo_aditado_dias": t[5],
                          "qualif_acrescimo": t[7], "qualif_vigencia": t[8], "qualif_reajuste": t[9],
                          "fundamento_legal": t[10]} for t in ts],
        }
    return out


def _cobertura_pares(con, pares: set[tuple]) -> dict[tuple, str]:
    """(UG, ano) → coberto/parcial/nunca_coletado/sem_referencia — mesmo critério de
    `reporting.cobertura_siafe.estado_do_par` (identidade do número de OB contra o espelho), em lote."""
    from compliance_agent.reporting.cobertura_siafe import PISO_AUSENCIA

    out: dict[tuple, str] = {}
    if not _tem(con, "ordens_bancarias"):
        return {p: "sem_referencia" for p in pares}
    por_ug: dict[str, set] = defaultdict(set)
    for ug, ano in pares:
        por_ug[ug].add(ano)
    for ug, anos in por_ug.items():
        siafe: dict[str, set] = defaultdict(set)
        for num, dt in con.execute(
                # ob-qualquer-status: metadado de cobertura (existência do número), não soma
                "SELECT numero_ob, data_emissao FROM ob_orcamentaria_siafe WHERE ug_emitente=?", (ug,)):
            siafe[str(dt or "")[6:10]].add(num)
        esp: dict[str, set] = defaultdict(set)
        for num, dt in con.execute("SELECT numero_ob, data_emissao FROM ordens_bancarias "
                                   "WHERE ug_codigo=? AND numero_ob IS NOT NULL", (ug,)):
            esp[str(dt or "")[:4]].add(num)
        for ano in anos:
            e = esp.get(ano, set())
            s = siafe.get(ano, set())
            if not e:
                out[(ug, ano)] = "sem_referencia"
            elif not s:
                out[(ug, ano)] = "nunca_coletado"
            else:
                out[(ug, ano)] = "parcial" if len(e - s) / len(e) >= PISO_AUSENCIA else "coberto"
    return out


def sinais_duplicidade(obs: list[tuple]) -> dict:
    """Dois sinais sobre as OBs de UM contrato (não mudam a classe; vão às ressalvas):
    · mesma NL + mesmo valor em mais de uma OB — a liquidação é paga uma vez;
    · mesma competência + mesmo valor com NL distinta — lente de competência (só a NF fecha)."""
    por_nl: dict[tuple, list] = defaultdict(list)
    por_comp: dict[tuple, set] = defaultdict(set)
    for o in obs:
        if o[4]:
            por_nl[(o[4], round(o[3], 2))].append(o)
        if o[5]:
            por_comp[(o[5], round(o[3], 2))].add(o[4] or o[6])
    n_nl = sum(len(v) - 1 for v in por_nl.values() if len(v) > 1)
    v_nl = sum(k[1] * (len(v) - 1) for k, v in por_nl.items() if len(v) > 1)
    n_cp = sum(len(v) - 1 for v in por_comp.values() if len(v) > 1)
    v_cp = sum(k[1] * (len(v) - 1) for k, v in por_comp.items() if len(v) > 1)
    return {"obs_mesma_nl": n_nl, "valor_mesma_nl": round(v_nl, 2),
            "obs_mesma_competencia": n_cp, "valor_mesma_competencia": round(v_cp, 2)}


def _resultado_base(esfera: str, **kw) -> dict:
    r = {"esfera": esfera, "id": "", "orgao": "", "ug": "", "contrato": "", "processo": "", "fornecedor": "",
         "fornecedor_doc": "", "objeto": "", "status_fonte": "", "data_contrato": "", "vig_inicio": "",
         "vig_fim": "", "continuada": False, "regime": "", "lei_teto": "", "valor_inicial": None,
         "valor_atualizado": None, "criterio_valor": "", "devido": None, "criterio_devido": "", "pago": None,
         "fonte_pago": "", "n_obs": 0, "vinculo": "", "categoria": "INDETERMINADO", "subtipo": "",
         "diferenca": None, "excesso_global": None, "motivo": "", "ressalvas": "", "acrescimo_pct": None,
         "teto_acrescimo": None, "estouro_art125": None, "obs_nao_contabilizadas": 0,
         "obs_anteriores_ao_contrato": 0, "valor_obs_anteriores": 0.0, "encerrado": False, "corte": "",
         "obs_mesma_nl": 0, "valor_mesma_nl": 0.0, "obs_mesma_competencia": 0, "valor_mesma_competencia": 0.0}
    r.update(kw)
    return mascarar_textos(r)


_RE_CPF_TXT = re.compile(r"\b(\d{3})\.\d{3}\.\d{3}-(\d{2})\b")


def mascarar_textos(r: dict) -> dict:
    """CPF formatado dentro de texto livre (objeto, nome) — medido: 2 objetos reais traziam CPF em claro."""
    for c in ("objeto", "fornecedor", "ressalvas"):
        if r.get(c):
            r[c] = _RE_CPF_TXT.sub(r"\1.***.***-\2", r[c])
    return r


def avaliar_estado(db: str | Path = _DB, *, corte: date | None = None) -> list[dict]:
    """Um resultado por linha de `contratos_tcerj` — nenhum contrato some do resultado."""
    con = _con_ro(db)
    try:
        corte = corte or corte_siafe(con) or date.today()
        contratos = con.execute(
            "SELECT id, processo, sei_norm, data_contratacao, valor_contrato, status, unidade, objeto, "
            "fornecedor, cnpj, vig_inicio, vig_fim, num_contratacao FROM contratos_tcerj").fetchall()
        grupos: dict[tuple, list] = defaultdict(list)
        chave_de: dict[str, tuple] = {}
        for c in contratos:
            k = (chave_sei(c[2] or c[1]), _digitos(c[9]))
            chave_de[c[0]] = k
            if (c[5] or "").strip() != "Cancelado" and k[0] and k[1]:
                grupos[k].append(c[0])
        credores = {k[1] for k in chave_de.values() if k[1]}
        procs_do_credor: dict[str, set] = defaultdict(set)
        for (p, cr) in grupos:
            procs_do_credor[cr].add(p)
        obs, nao_contab = _obs_por_credor(con, credores)
        pncp = _termos_pncp(con, {k for k, v in grupos.items() if len(v) == 1})

        res = [_avaliar_um_estado(c, chave_de[c[0]], grupos, obs, nao_contab, pncp, procs_do_credor, corte)
               for c in contratos]
        # cobertura só onde ela decide (o "a menor" no processo)
        pares = {p for r in res for p in r.get("_checar", ())}
        cob = _cobertura_pares(con, pares) if pares else {}
        for r in res:
            if r.get("_checar"):
                ruins = sorted(f"{u}/{a}" for (u, a) in r.pop("_checar")
                               if cob.get((u, a)) in ("parcial", "nunca_coletado"))
                if ruins:
                    r.update(categoria="INDETERMINADO", motivo="cobertura_siafe_parcial", subtipo="")
                    r["ressalvas"] = _junta(r["ressalvas"], "pares (UG/ano) parciais: " + ", ".join(ruins))
            r.pop("_checar", None)
        return res
    finally:
        con.close()


def _junta(a: str, b: str) -> str:
    return f"{a} · {b}" if a else b


def _avaliar_um_estado(c, chave, grupos, obs, nao_contab, pncp, procs_do_credor, corte) -> dict:
    (cid, processo, _sn, data_contr, valor, status, unidade, objeto, fornecedor, cnpj, vig_ini, vig_fim,
     num) = c
    d_contr = parse_data(data_contr)
    ini = parse_data(vig_ini)
    fim = parse_data(vig_fim)
    regime, lei = regime_legal(ini or d_contr)
    continuada = e_continuada(objeto)
    r = _resultado_base(
        ESTADO, id=cid, orgao=(unidade or "").strip(), contrato=num or "", processo=processo or "",
        fornecedor=(fornecedor or "").strip(), fornecedor_doc=mascarar_doc(cnpj), objeto=(objeto or "").strip(),
        status_fonte=(status or "").strip(), data_contrato=d_contr.isoformat() if d_contr else "",
        vig_inicio=ini.isoformat() if ini else "", vig_fim=fim.isoformat() if fim else "",
        continuada=continuada, regime=regime, lei_teto=lei, valor_inicial=valor, valor_atualizado=valor,
        criterio_valor="valor registrado no TCE-RJ (a fonte não publica termos aditivos)",
        fonte_pago="SIAFE-Rio — OB Orçamentária, status Contabilizado", corte=corte.isoformat())
    k_proc, k_cred = chave
    r["obs_nao_contabilizadas"] = nao_contab.get(chave, 0) if k_proc else 0

    if r["status_fonte"] == "Cancelado":
        return {**r, "motivo": "registro_cancelado"}
    if not valor or float(valor) <= 0:
        return {**r, "motivo": "valor_contrato_ausente"}
    if not k_cred:
        return {**r, "motivo": "credor_sem_documento"}
    if not k_proc:
        return {**r, "motivo": "processo_sem_sei"}
    if e_registro_de_termo(objeto):
        return {**r, "motivo": "registro_de_termo"}
    if len(grupos.get(chave, ())) > 1:
        return {**r, "motivo": "vinculo_ambiguo",
                "ressalvas": f"{len(grupos[chave])} contratos no mesmo par (processo, credor)"}

    # termos publicados no PNCP atualizam valor e vigência
    t = pncp.get(chave)
    if t:
        if t["valor_global"]:
            r["valor_atualizado"] = float(t["valor_global"])
        if t["valor_inicial"]:
            r["valor_inicial"] = float(t["valor_inicial"])
        if t["vigencia_fim"] and (not fim or t["vigencia_fim"] > fim):
            fim = t["vigencia_fim"]
            r["vig_fim"] = fim.isoformat()
        r["criterio_valor"] = (f"valor global atualizado pelo último de {t['n_termos']} termo(s) publicado(s) "
                               f"no PNCP ({t['controle_pncp']})")
        est = limites_aditivo.estouro(r["valor_inicial"], t["aditivos"],
                                      "reforma" if re.search(r"REFORMA", objeto or "", re.I) else None,
                                      regime="8666" if regime == "8666" else "14133")
        if est.get("aferivel"):
            r.update(acrescimo_pct=est["pct"], teto_acrescimo=est["teto"], estouro_art125=bool(est["estourou"]))

    inicio_ref = min([d for d in (ini, d_contr) if d], default=None)
    if inicio_ref is None:
        return {**r, "motivo": "inicio_nao_registrado"}
    if inicio_ref < INICIO_COBERTURA_SIAFE:
        return {**r, "motivo": "vigencia_anterior_a_cobertura"}

    encerrado = r["status_fonte"] == "Encerrado" or bool(fim and fim < corte)
    r["encerrado"] = encerrado
    # pró-rata desde o INÍCIO MAIS ANTIGO conhecido: a vigência registrada pode ser a do período
    # prorrogado corrente, enquanto valor e pago são acumulados desde a contratação
    devido, crit = valor_devido(r["valor_atualizado"], continuada, inicio_ref if ini else None, fim, corte)
    r["criterio_devido"] = crit
    if continuada and ini and fim and (fim - ini).days > VIGENCIA_PADRAO_DIAS and not t:
        r["ressalvas"] = _junta(r["ressalvas"], f"vigência registrada de {(fim - ini).days + 1} dias sem termo "
                                                "publicado: o valor pode não refletir prorrogação")
    if e_parceria(objeto):
        r["ressalvas"] = _junta(r["ressalvas"], "parceria/contrato de gestão/repasse: desembolso antecipado é "
                                                "da natureza do instrumento")

    lista = obs.get(k_cred, [])
    no_proc = [o for o in lista if o[1] == k_proc and o[0] and o[0] >= inicio_ref and o[0] <= corte]
    anteriores = [o for o in lista if o[1] == k_proc and o[0] and o[0] < inicio_ref]
    r["obs_anteriores_ao_contrato"] = len(anteriores)
    r["valor_obs_anteriores"] = round(sum(o[3] for o in anteriores), 2)
    if anteriores:
        r["ressalvas"] = _junta(r["ressalvas"], f"{len(anteriores)} OB(s) do mesmo processo anteriores ao "
                                                "contrato excluídas da soma")
    fora = [o for o in lista if o[1] != k_proc and o[0] and inicio_ref <= o[0] <= corte]

    if not no_proc:
        if fora:
            return {**r, "motivo": "ob_do_credor_fora_do_processo"}
        pago, r["vinculo"] = 0.0, "credor_sem_ob"
        r["ressalvas"] = _junta(r["ressalvas"], "nenhuma OB contabilizada ao credor no SIAFE desde o início "
                                                "(pago zero medido na coleta — piso)")
    else:
        pago, r["vinculo"] = round(sum(o[3] for o in no_proc), 2), "processo_e_credor"
    ugs = sorted({o[2] for o in no_proc})
    r.update(pago=pago, n_obs=len(no_proc), ug=",".join(ugs))
    r.update(sinais_duplicidade(no_proc))
    if r["obs_mesma_nl"]:
        r["ressalvas"] = _junta(r["ressalvas"], f"{r['obs_mesma_nl']} OB(s) a mais para a MESMA nota de liquidação "
                                                f"e mesmo valor (R$ {fmt_brl(r['valor_mesma_nl'])}) — possível "
                                                "pagamento em duplicidade ou reemissão a conferir")
    if r["obs_mesma_competencia"]:
        r["ressalvas"] = _junta(r["ressalvas"], f"{r['obs_mesma_competencia']} OB(s) de mesmo valor e mesma "
                                                f"competência com NL distinta (R$ {fmt_brl(r['valor_mesma_competencia'])})"
                                                " — lente de competência: só a nota fiscal fecha")

    if devido is None:
        if pago > r["valor_atualizado"] and not dentro_da_tolerancia(pago - r["valor_atualizado"],
                                                                     r["valor_atualizado"]):
            r["ressalvas"] = _junta(r["ressalvas"], f"pago (R$ {fmt_brl(pago)}) supera o valor registrado, mas "
                                                    "sem vigência não se sabe a quantos períodos o valor se refere")
        return {**r, "motivo": "vigencia_nao_registrada"}
    if desproporcional(r["valor_atualizado"], pago):
        return {**r, "devido": round(devido, 2), "diferenca": round(pago - devido, 2),
                "motivo": "valor_desproporcional"}

    cat, sub, dif = classificar(pago, devido, r["valor_atualizado"], encerrado=encerrado)
    r.update(devido=round(devido, 2), categoria=cat, subtipo=sub, diferenca=round(dif, 2))
    if cat == "A_MAIOR" and pago > r["valor_atualizado"]:
        r["excesso_global"] = round(pago - r["valor_atualizado"], 2)
    if cat.startswith("A_MENOR") and r["vinculo"] == "processo_e_credor":
        outros = procs_do_credor.get(k_cred, set()) - {k_proc}
        alheias = [o for o in fora if o[2] in ugs and o[1] not in outros]
        if alheias:
            return {**r, "categoria": "INDETERMINADO", "subtipo": "", "motivo": "a_menor_com_ob_fora_do_processo",
                    "ressalvas": _junta(r["ressalvas"], f"{len(alheias)} OB(s) do credor na mesma UG em outro "
                                                        f"processo (R$ {fmt_brl(sum(o[3] for o in alheias))})")}
        anos = range(inicio_ref.year, min(corte, fim or corte).year + 1)
        r["_checar"] = [(u, str(a)) for u in ugs for a in anos]
    return r


# ── Prefeitura ───────────────────────────────────────────────────────────────────────────────

def avaliar_prefeitura(db: str | Path = _DB_PCRJ) -> list[dict]:
    """Um resultado por linha de `contasrio_contrato`. Pago = total pago no SIAFIC-Rio por contrato."""
    con = _con_ro(db)
    try:
        if not _tem(con, "contasrio_contrato"):
            return []
        linhas = con.execute(
            "SELECT contrato, favorecido_doc, favorecido_nome, orgao, ug, objeto, situacao, vigencia_ini, "
            "vigencia_fim, processo, valor_atualizado, total_pago, coletado_em, data_publicacao "
            "FROM contasrio_contrato").fetchall()
    finally:
        con.close()
    return [_avaliar_um_pcrj(row) for row in linhas]


def _avaliar_um_pcrj(row) -> dict:
    (cid, doc, nome, orgao, ug, objeto, sit, vini, vfim, proc, v_atual, pago, coletado, dpub) = row
    corte = parse_data(coletado) or date.today()
    ini, fim = parse_data(vini), parse_data(vfim)
    regime, lei = regime_legal(ini or parse_data(dpub))
    continuada = e_continuada(objeto)
    r = _resultado_base(
        PREFEITURA, id=str(cid), orgao=(orgao or "").strip(), ug=(ug or "").strip(), contrato=str(cid),
        processo=proc or "", fornecedor=(nome or "").strip(), fornecedor_doc=mascarar_doc(doc),
        objeto=(objeto or "").strip(), status_fonte=(sit or "").strip(),
        data_contrato=(parse_data(dpub).isoformat() if parse_data(dpub) else ""),
        vig_inicio=ini.isoformat() if ini else "", vig_fim=fim.isoformat() if fim else "",
        continuada=continuada, regime=regime, lei_teto=lei, valor_inicial=None, valor_atualizado=v_atual,
        criterio_valor="valor atualizado publicado no Contas Rio (inclui termos registrados)",
        fonte_pago="SIAFIC-Rio — total pago por contrato (Contas Rio/CCON)", corte=corte.isoformat(),
        vinculo="contrato_nativo")
    if not v_atual or float(v_atual) <= 0:
        return {**r, "motivo": "valor_contrato_ausente"}
    if not _digitos(doc):
        return {**r, "motivo": "credor_sem_documento"}
    if pago is None:
        return {**r, "motivo": "pago_indisponivel"}
    pago = float(pago)
    encerrado = r["status_fonte"] in ("Encerrado", "Vencida") or bool(fim and fim < corte)
    r.update(pago=round(pago, 2), encerrado=encerrado)
    # A vigência do Contas Rio é a do período PRORROGADO corrente (medido: 4.697 de 14.420 contratos com
    # início de vigência posterior ao ano do contrato), enquanto valor atualizado e total pago são
    # ACUMULADOS desde a assinatura. Pró-rata sobre o período corrente fabricou R$ 2,6 bi de "a maior"
    # na primeira rodada; o início certo é o mais antigo conhecido (data de publicação do contrato).
    d_pub = parse_data(dpub)
    inicio = min([d for d in (ini, d_pub) if d], default=None) if ini else None
    devido, crit = valor_devido(float(v_atual), continuada, inicio, fim, corte)
    r["criterio_devido"] = crit
    if e_parceria(objeto):
        r["ressalvas"] = "parceria/contrato de gestão/repasse: desembolso antecipado é da natureza do instrumento"
    if devido is None:
        if pago > v_atual and not dentro_da_tolerancia(pago - v_atual, v_atual):
            r["ressalvas"] = _junta(r["ressalvas"], f"pago (R$ {fmt_brl(pago)}) supera o valor atualizado, mas "
                                                    "sem vigência não se sabe a quantos períodos o valor se refere")
        return {**r, "motivo": "vigencia_nao_registrada"}
    if desproporcional(float(v_atual), pago):
        return {**r, "devido": round(devido, 2), "diferenca": round(pago - devido, 2),
                "motivo": "valor_desproporcional"}
    cat, sub, dif = classificar(pago, devido, float(v_atual), encerrado=encerrado)
    r.update(devido=round(devido, 2), categoria=cat, subtipo=sub, diferenca=round(dif, 2))
    if cat == "A_MAIOR" and pago > v_atual:
        r["excesso_global"] = round(pago - v_atual, 2)
    return r


MOTIVOS["pago_indisponivel"] = "total pago não publicado para o contrato"
MOTIVOS["valor_desproporcional"] = ("valor registrado e pago a 100 vezes ou mais um do outro — erro de registro "
                                    "provável; listado à parte para conferência")


# ── consolidação ─────────────────────────────────────────────────────────────────────────────

def consolidar(resultados: list[dict], por: str) -> list[dict]:
    """Por 'orgao' ou 'fornecedor' (CPF/CNPJ), SEMPRE dentro da esfera. Somas só do determinado."""
    campo = {"orgao": "orgao", "fornecedor": "fornecedor_doc"}[por]
    g: dict[tuple, dict] = {}
    for r in resultados:
        k = (r["esfera"], r[campo] or "(não informado)")
        a = g.setdefault(k, {"esfera": k[0], "chave": k[1], "nome": r["fornecedor"] if por == "fornecedor" else k[1],
                             "n": 0, **{f"n_{c.lower()}": 0 for c in CATEGORIAS},
                             "devido_determinado": 0.0, "pago_determinado": 0.0, "excesso_a_maior": 0.0,
                             "excesso_global": 0.0, "deficit_encerrado": 0.0, "valor_contratado": 0.0})
        a["n"] += 1
        a[f"n_{r['categoria'].lower()}"] += 1
        a["valor_contratado"] += float(r["valor_atualizado"] or 0)
        if r["categoria"] != "INDETERMINADO":
            a["devido_determinado"] += float(r["devido"] or 0)
            a["pago_determinado"] += float(r["pago"] or 0)
        if r["categoria"] == "A_MAIOR":
            a["excesso_a_maior"] += float(r["diferenca"] or 0)
            a["excesso_global"] += float(r["excesso_global"] or 0)
        if r["categoria"] == "A_MENOR_ENCERRADO":
            a["deficit_encerrado"] += -float(r["diferenca"] or 0)
    for a in g.values():
        a["n_a_menor_enc"] = a["n_a_menor_encerrado"]
        a["n_a_menor_curso"] = a["n_a_menor_em_curso"]
    return sorted(g.values(), key=lambda a: (a["esfera"], -a["excesso_a_maior"], -a["n"]))


def resumo(resultados: list[dict]) -> dict:
    """Contagens e somas por esfera (o que vai ao sumário executivo e à resposta ao dono)."""
    out: dict[str, dict] = {}
    for r in resultados:
        e = out.setdefault(r["esfera"], {"n": 0, **{c: 0 for c in CATEGORIAS}, "motivos": defaultdict(int),
                                          "subtipos": defaultdict(int), "excesso_a_maior": 0.0,
                                          "excesso_global": 0.0, "deficit_encerrado": 0.0,
                                          "pago_determinado": 0.0, "devido_determinado": 0.0,
                                          "n_estouro_art125": 0, "n_art125_aferivel": 0})
        e["n"] += 1
        e[r["categoria"]] += 1
        if r["categoria"] == "INDETERMINADO":
            e["motivos"][r["motivo"]] += 1
        else:
            e["pago_determinado"] += float(r["pago"] or 0)
            e["devido_determinado"] += float(r["devido"] or 0)
        if r["categoria"] == "A_MAIOR":
            e["subtipos"][r["subtipo"]] += 1
            e["excesso_a_maior"] += float(r["diferenca"] or 0)
            e["excesso_global"] += float(r["excesso_global"] or 0)
        if r["categoria"] == "A_MENOR_ENCERRADO":
            e["deficit_encerrado"] += -float(r["diferenca"] or 0)
        if r["estouro_art125"] is not None:
            e["n_art125_aferivel"] += 1
            e["n_estouro_art125"] += int(bool(r["estouro_art125"]))
    for e in out.values():
        e["motivos"] = dict(sorted(e["motivos"].items(), key=lambda kv: -kv[1]))
        e["subtipos"] = dict(e["subtipos"])
    return out


# ── saída ────────────────────────────────────────────────────────────────────────────────────

def fmt_brl(v: Any) -> str:
    if v is None or v == "":
        return "—"
    s = f"{float(v):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_int(n: int) -> str:
    return f"{int(n):,}".replace(",", ".")


CAMPOS_CSV = ["esfera", "id", "orgao", "ug", "contrato", "processo", "fornecedor", "fornecedor_doc", "objeto",
              "status_fonte", "data_contrato", "vig_inicio", "vig_fim", "encerrado", "continuada", "regime",
              "lei_teto", "valor_inicial", "valor_atualizado", "criterio_valor", "devido", "criterio_devido",
              "pago", "fonte_pago", "n_obs", "vinculo", "categoria", "subtipo", "diferenca", "excesso_global",
              "motivo", "motivo_texto", "ressalvas", "acrescimo_pct", "teto_acrescimo", "estouro_art125",
              "obs_nao_contabilizadas", "obs_anteriores_ao_contrato", "valor_obs_anteriores",
              "obs_mesma_nl", "valor_mesma_nl", "obs_mesma_competencia", "valor_mesma_competencia", "corte"]


def escrever_csv(resultados: list[dict], destino: str | Path) -> int:
    with open(destino, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_CSV, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for r in resultados:
            w.writerow({**r, "motivo_texto": MOTIVOS.get(r["motivo"], "")})
    return len(resultados)


def _ordem(r: dict) -> tuple:
    return (r["esfera"] != ESTADO, CATEGORIAS.index(r["categoria"]), -(r["diferenca"] or 0)
            if r["categoria"] == "A_MAIOR" else (r["diferenca"] or 0), r["orgao"], r["id"])


def ordenar(resultados: list[dict]) -> list[dict]:
    return sorted(resultados, key=_ordem)


# ── relatório (produto da casa: render_html + PDF A4 paginado) ──────────────────────────────────
_E = _html.escape

_CSS_EXTRA = """<style>
 table.anx th, table.anx td { font-size:6.4px; padding:1.6px 3px; line-height:1.25; }
 table.anx td.n, table.cons td.n, table.res td.n { text-align:right; white-space:nowrap; }
 table.cons th, table.cons td { font-size:7.6px; padding:2.5px 4px; }
 table.res td, table.res th { font-size:9px; }
 .cat-A_MAIOR { color:#b71c1c; font-weight:700; } .cat-A_MENOR_ENCERRADO { color:#e65100; font-weight:700; }
 .cat-A_MENOR_EM_CURSO { color:#8a6d00; } .cat-CONFORME { color:#2e7d32; } .cat-INDETERMINADO { color:#666; }
 .callout { border-left:4px solid #b71c1c; background:#fdecea; padding:8px 12px; margin:8px 0; border-radius:0 4px 4px 0; }
 ol.sumario a { color:#1f4e79; text-decoration:none; } ol.sumario li { margin:2px 0; }
 thead { display: table-header-group; } tr { page-break-inside: avoid; }
</style>"""


def _sec(ancora: str, titulo: str, corpo: str, quebra: bool = False) -> dict:
    return {"titulo": titulo, "html": f'<a id="{ancora}"></a>' + corpo, "page_break": quebra}


def campo_txt(v: Any, n: int) -> str:
    """Trunca célula SEMPRE com reticência (o texto integral está no CSV)."""
    t = ("" if v is None else str(v)).strip().replace("\n", " ")
    return t if len(t) <= n else t[:n].rstrip() + "…"


def _celula_cat(cat: str, sub: str = "") -> str:
    t = ROTULO[cat] + (f" ({SUBTIPO[sub]})" if sub else "")
    return f'<span class="cat-{cat}">{_E(t)}</span>'


def _tabela_resumo(rs: dict) -> str:
    linhas = []
    for esf in (ESTADO, PREFEITURA):
        e = rs.get(esf)
        if not e:
            continue
        linhas.append(
            f"<tr><td><b>{_E(esf)}</b></td><td class='n'>{fmt_int(e['n'])}</td>"
            f"<td class='n'>{fmt_int(e['CONFORME'])}</td><td class='n'>{fmt_int(e['A_MAIOR'])}</td>"
            f"<td class='n'>{fmt_int(e['A_MENOR_ENCERRADO'])}</td><td class='n'>{fmt_int(e['A_MENOR_EM_CURSO'])}</td>"
            f"<td class='n'>{fmt_int(e['INDETERMINADO'])}</td><td class='n'>{fmt_brl(e['excesso_a_maior'])}</td>"
            f"<td class='n'>{fmt_brl(e['excesso_global'])}</td><td class='n'>{fmt_brl(e['deficit_encerrado'])}</td></tr>")
    return ("<table class='res'><thead><tr><th>Esfera</th><th>Contratos</th><th>Conforme</th><th>Pago a maior</th>"
            "<th>A menor (encerrado)</th><th>A menor (em curso)</th><th>Indeterminado</th>"
            "<th>Excesso sobre o devido (R$)</th><th>Excesso sobre o valor global (R$)</th>"
            "<th>Déficit em contratos encerrados (R$)</th></tr></thead><tbody>" + "".join(linhas) + "</tbody></table>")


def _tabela_motivos(e: dict) -> str:
    linhas = "".join(f"<tr><td>{_E(MOTIVOS.get(m, m))}</td><td class='mono'>{_E(m)}</td>"
                     f"<td class='n'>{fmt_int(n)}</td></tr>" for m, n in e["motivos"].items())
    return ("<table class='res'><thead><tr><th>Motivo da indeterminação</th><th>Código</th><th>Contratos</th>"
            "</tr></thead><tbody>" + linhas + "</tbody></table>")


def _prosa_caso(i: int, r: dict) -> str:
    dev = (f"R$ {fmt_brl(r['devido'])} ({_E(r['criterio_devido'])})" if r["devido"] is not None
           else f"inaferível pelo pró-rata ({_E(r['criterio_devido'])}); comparado ao valor global")
    exc = (f" O pago supera o próprio valor global atualizado em <b>R$ {fmt_brl(r['excesso_global'])}</b>."
           if r.get("excesso_global") else
           " O pago está dentro do valor global, mas à frente do que a vigência decorrida justifica — "
           "indício de pagamento antecipado ou de vigência/valor registrados em descompasso.")
    vinc = ("OBs contabilizadas no SIAFE ao mesmo credor, no próprio processo do contrato"
            if r["esfera"] == ESTADO else "total pago por contrato no SIAFIC-Rio")
    n_obs = f" em {fmt_int(r['n_obs'])} OB(s)" if r["esfera"] == ESTADO else ""
    ress = f" <i>Ressalvas: {_E(r['ressalvas'])}.</i>" if r.get("ressalvas") else ""
    return (f"<p><b>{i}. {_E(r['orgao'])} — contrato {_E(r['contrato'] or r['id'])}</b> "
            f"(processo {_E(r['processo'] or '—')}), fornecedor {_E(r['fornecedor'])} "
            f"({_E(r['fornecedor_doc'])}). Objeto: {_E(campo_txt(r['objeto'], 260))}. "
            f"Valor atualizado R$ {fmt_brl(r['valor_atualizado'])} ({_E(r['criterio_valor'])}); "
            f"vigência {_E(r['vig_inicio'] or '—')} a {_E(r['vig_fim'] or '—')}. Devido no corte: {dev}. "
            f"Pago: <b>R$ {fmt_brl(r['pago'])}</b>{n_obs} ({vinc}). "
            f"Diferença: <b>R$ {fmt_brl(r['diferenca'])}</b>.{exc}{ress}</p>")


def _tabela_consolidada(itens: list[dict], rotulo: str) -> str:
    linhas = []
    for a in itens:
        doc = "" if rotulo.startswith("Órgão") else f"<br><span class='mono'>{_E(a['chave'])}</span>"
        linhas.append(
            f"<tr><td>{_E(campo_txt(a['nome'], 70))}{doc}</td>"
            f"<td class='n'>{fmt_int(a['n'])}</td><td class='n'>{fmt_int(a['n_conforme'])}</td>"
            f"<td class='n'>{fmt_int(a['n_a_maior'])}</td><td class='n'>{fmt_int(a['n_a_menor_enc'])}</td>"
            f"<td class='n'>{fmt_int(a['n_a_menor_curso'])}</td><td class='n'>{fmt_int(a['n_indeterminado'])}</td>"
            f"<td class='n'>{fmt_brl(a['devido_determinado'])}</td><td class='n'>{fmt_brl(a['pago_determinado'])}</td>"
            f"<td class='n'>{fmt_brl(a['excesso_a_maior'])}</td><td class='n'>{fmt_brl(a['deficit_encerrado'])}</td></tr>")
    return (f"<table class='cons'><thead><tr><th>{_E(rotulo)}</th><th>Contr.</th><th>Conf.</th><th>A maior</th>"
            "<th>A menor enc.</th><th>A menor curso</th><th>Indet.</th><th>Devido determinado (R$)</th>"
            "<th>Pago determinado (R$)</th><th>Excesso a maior (R$)</th><th>Déficit encerrados (R$)</th></tr>"
            "</thead><tbody>" + "".join(linhas) + "</tbody></table>")


MARCA_LINHA_ANEXO = "<tr class='ct'>"


def _tabela_anexo(itens: list[dict], inicio: int = 1) -> str:
    linhas = []
    for i, r in enumerate(itens, start=inicio):
        nota = MOTIVOS.get(r["motivo"], "") if r["categoria"] == "INDETERMINADO" else r["criterio_devido"]
        linhas.append(
            f"{MARCA_LINHA_ANEXO}<td class='n'>{i}</td><td>{_E(campo_txt(r['orgao'], 38))}</td>"
            f"<td>{_E(r['contrato'] or r['id'])}<br>{_E(r['processo'])}</td>"
            f"<td>{_E(campo_txt(r['fornecedor'], 40))}<br>{_E(r['fornecedor_doc'])}</td>"
            f"<td>{_E(r['vig_inicio'] or '—')}<br>{_E(r['vig_fim'] or '—')}</td>"
            f"<td class='n'>{fmt_brl(r['valor_atualizado'])}</td><td class='n'>{fmt_brl(r['devido'])}</td>"
            f"<td class='n'>{fmt_brl(r['pago'])}</td><td class='n'>{fmt_brl(r['diferenca'])}</td>"
            f"<td>{_celula_cat(r['categoria'], r['subtipo'])}</td><td>{_E(campo_txt(nota, 90))}</td></tr>")
    return ("<table class='anx'><thead><tr><th>#</th><th>Órgão</th><th>Contrato / processo</th>"
            "<th>Fornecedor</th><th>Vigência</th><th>Valor atualizado</th><th>Devido no corte</th>"
            "<th>Pago</th><th>Diferença</th><th>Classificação</th><th>Critério / motivo</th></tr></thead><tbody>"
            + "".join(linhas) + "</tbody></table>")


LEGENDA_ANEXO = (
    "<p>Ordem: pago a maior (maior diferença primeiro), a menor encerrado, a menor em curso, conforme, "
    "indeterminado. Valores em R$. \"—\" = indisponível (nunca zero). O CSV que acompanha este relatório traz "
    "todas as colunas, inclusive objeto completo, UG, número de OBs, ressalvas e percentual de acréscimo.</p>")


def blocos_por_esfera(resultados: list[dict]) -> list[tuple[str, list[dict]]]:
    ordenados = ordenar(resultados)
    return [(esf, [r for r in ordenados if r["esfera"] == esf]) for esf in (ESTADO, PREFEITURA)]


def corpo_fornecedores(cons_f: list[dict]) -> str:
    return "".join(f"<h3>{_E(esf)}</h3>" + _tabela_consolidada([a for a in cons_f if a["esfera"] == esf],
                                                               "Fornecedor") for esf in (ESTADO, PREFEITURA))


def montar_ctx_volume(titulo: str, subtitulo: str, corpo: str, emitido: date | None = None) -> dict:
    """Volume anexo no MESMO render da casa (capa, proveniência, hash)."""
    emitido = emitido or date.today()
    return {"classificacao": "RESERVADO — PERÍCIA CONTÁBIL · ANEXO", "titulo": titulo, "subtitulo": subtitulo,
            "data": emitido.strftime("%d/%m/%Y"), "sem_indice": True, "top_flags": [],
            "metodologia": "Confronto devido × pago por Ordem Bancária contabilizada; Lei 4.320/64, arts. 58–65",
            "secoes": [{"titulo": titulo, "html": _CSS_EXTRA + corpo}], "proveniencia": [],
            "ressalva": ("Indícios para apuração; presunção de legitimidade dos atos administrativos. INDETERMINADO "
                         "não equivale a zero. CPF de pessoa física mascarado."),
            "_dados": {"titulo": titulo, "subtitulo": subtitulo}}


def montar_ctx(resultados: list[dict], *, n_base: dict[str, int], emitido: date | None = None,
               volumes: list[dict] | None = None) -> dict:
    """Contexto do `render_html` da casa. Nada é cortado: o anexo traz TODOS os contratos."""
    rs = resumo(resultados)
    emitido = emitido or date.today()
    est, pre = rs.get(ESTADO, {}), rs.get(PREFEITURA, {})
    cortes = {e: max((r["corte"] for r in resultados if r["esfera"] == e), default="") for e in (ESTADO, PREFEITURA)}
    a_maior = {e: sorted([r for r in resultados if r["esfera"] == e and r["categoria"] == "A_MAIOR"],
                         key=lambda r: -(r["diferenca"] or 0)) for e in (ESTADO, PREFEITURA)}
    tol = f"{TOL_PCT * 100:.0f}% do devido ou R$ {fmt_brl(TOL_ABS)}"
    secoes = []

    sumario = ("<ol class='sumario'>" + "".join(
        f"<li><a href='#{a}'>{_E(t)}</a></li>" for a, t in [
            ("s1", "Sumário executivo"), ("s2", "Objeto, escopo e data de corte"),
            ("s3", "Metodologia e critérios"), ("s4", "Resultados — Estado do RJ"),
            ("s5", "Resultados — Prefeitura do Rio"), ("s6", "Maiores casos de pagamento a maior"),
            ("s7", "Acréscimos acima do teto legal"),
            ("s7b", "Sinais de pagamento em duplicidade"),
            ("s7c", "Valores registrados desproporcionais ao pago"), ("s8", "Consolidado por órgão / UG"),
            ("s9", "Consolidado por fornecedor"), ("s10", "Limitações e ressalvas"),
            ("s11", "Anexo — tabela por contrato (todos os contratos)")]) + "</ol>")
    secoes.append(_sec("s0", "Sumário", _CSS_EXTRA + sumario))

    def _frase(esf, e):
        if not e:
            return ""
        return (f"<p><b>{_E(esf)}.</b> Foram periciados <b>{fmt_int(e['n'])}</b> contratos (a totalidade da base "
                f"desta esfera). Resultado: {fmt_int(e['CONFORME'])} conforme(s); <b>{fmt_int(e['A_MAIOR'])} pago(s) a "
                f"maior</b>, com excesso de <b>R$ {fmt_brl(e['excesso_a_maior'])}</b> sobre o devido no corte "
                f"(dos quais R$ {fmt_brl(e['excesso_global'])} acima do próprio valor global atualizado); "
                f"{fmt_int(e['A_MENOR_ENCERRADO'])} pago(s) a menor com vigência encerrada (déficit de "
                f"R$ {fmt_brl(e['deficit_encerrado'])}); {fmt_int(e['A_MENOR_EM_CURSO'])} a menor em curso; e "
                f"{fmt_int(e['INDETERMINADO'])} indeterminado(s), cada um com o motivo declarado.</p>")

    top = []
    for esf in (ESTADO, PREFEITURA):
        for r in a_maior[esf][:10]:
            top.append(f"<tr><td>{_E(esf)}</td><td>{_E(campo_txt(r['orgao'], 50))}</td>"
                       f"<td>{_E(r['contrato'] or r['id'])}</td><td>{_E(campo_txt(r['fornecedor'], 45))}</td>"
                       f"<td class='n'>{fmt_brl(r['devido'])}</td><td class='n'>{fmt_brl(r['pago'])}</td>"
                       f"<td class='n'>{fmt_brl(r['diferenca'])}</td></tr>")
    secoes.append(_sec("s1", "1. Sumário executivo", (
        "<p>Esta perícia confronta, contrato a contrato, o <b>valor devido</b> até a data de corte com o "
        "<b>valor efetivamente pago</b>, e classifica cada instrumento em uma de cinco situações: pago a maior, "
        "pago a menor com vigência encerrada, pago a menor em curso, conforme, ou indeterminado. Pagamento, "
        "aqui, é exclusivamente a Ordem Bancária contabilizada (Estado) ou o total pago registrado no sistema "
        "contábil do Município (Prefeitura) — empenho e liquidação nunca são tratados como pagamento.</p>"
        + _frase(ESTADO, est) + _frase(PREFEITURA, pre) + _tabela_resumo(rs)
        + "<div class='callout'><b>Leitura obrigatória.</b> Cada classificação é <b>indício</b> para apuração, "
          "não acusação; vale a presunção de legitimidade dos atos administrativos. \"Pago a menor\" em contrato "
          "vigente não é irregularidade por si — pode refletir defasagem normal entre execução, liquidação e "
          "pagamento. INDETERMINADO não é zero: significa que a base disponível não permite afirmar o pago "
          "sem palpite, e o motivo vem declarado.</div>"
        + "<h4>Os dez maiores pagamentos a maior por esfera (diferença pago − devido)</h4>"
        + "<table class='res'><thead><tr><th>Esfera</th><th>Órgão</th><th>Contrato</th><th>Fornecedor</th>"
          "<th>Devido (R$)</th><th>Pago (R$)</th><th>Diferença (R$)</th></tr></thead><tbody>"
        + "".join(top) + "</tbody></table>")))

    secoes.append(_sec("s2", "2. Objeto, escopo e data de corte", (
        f"<p><b>Universo.</b> Todos os contratos das duas bases de contratos disponíveis, sem amostragem: "
        f"<b>{fmt_int(n_base.get(ESTADO, 0))}</b> registros de contratos do Estado do RJ publicados pelo "
        f"Tribunal de Contas do Estado (dados abertos, contratações de 2023 em diante) e "
        f"<b>{fmt_int(n_base.get(PREFEITURA, 0))}</b> contratos do Município do Rio de Janeiro publicados no "
        f"portal Contas Rio. As esferas são tratadas separadamente e nunca somadas entre si.</p>"
        f"<p><b>Data de corte.</b> \"Até o presente momento\" significa até onde as fontes chegam: para o Estado, a "
        f"Ordem Bancária contabilizada mais recente na base (<b>{_E(cortes[ESTADO])}</b>); para a Prefeitura, a "
        f"data da consulta ao Contas Rio (<b>{_E(cortes[PREFEITURA])}</b>). Relatório emitido em "
        f"{emitido.strftime('%d/%m/%Y')}.</p>")))

    secoes.append(_sec("s3", "3. Metodologia e critérios", (
        "<h4>3.1 Valor pago</h4>"
        "<p><b>Estado.</b> Somente Ordem Bancária (OB) do SIAFE-Rio com situação <i>Contabilizado</i>. OBs anuladas, "
        "excluídas ou não contabilizadas são contadas e informadas, mas nunca somadas. A identidade de uma OB é o "
        "trio (número, exercício, UG emitente) — o mesmo número em outra UG é outra OB. A data de emissão é lida "
        "como data (DD/MM/AAAA), não como texto.</p>"
        "<p><b>Prefeitura.</b> O Município não usa o SIAFE estadual; o pago é o <i>total pago</i> por contrato "
        "registrado no SIAFIC-Rio e publicado no Contas Rio (consulta CCON), que já vem vinculado ao contrato.</p>"
        "<h4>3.2 Vínculo entre pagamento e contrato (Estado)</h4>"
        "<p>A OB traz o número do processo administrativo; o contrato registrado no TCE-RJ também. Uma OB é "
        "atribuída a um contrato quando <b>o processo SEI e o CPF/CNPJ do credor coincidem</b> e esse par aponta "
        "para <b>um único</b> contrato. Os números de processo são canonizados nos dois lados (o SIAFE grava parte "
        "deles com ano de dois dígitos). OBs do mesmo processo emitidas antes do início do contrato são excluídas "
        "e declaradas. Quando o par aponta para mais de um contrato, ou quando o credor só recebeu OBs em "
        "processo diverso do contrato (o pagamento no Estado corre frequentemente em processo próprio de "
        "pagamento), o contrato é INDETERMINADO: atribuir pagamento por credor seria palpite. Quando o credor "
        "não recebeu nenhuma OB contabilizada desde o início da vigência, o pago zero é medido — e informado "
        "como piso da coleta.</p>"
        "<h4>3.3 Valor devido</h4>"
        "<p>Valor atualizado = valor original + termos aditivos, apostilamentos, reajustes e reequilíbrios "
        "publicados. O TCE-RJ não publica termos aditivos; quando o Portal Nacional de Contratações Públicas "
        "publica termos do mesmo processo e credor, o valor global do último termo e a vigência prorrogada "
        "prevalecem. Para <b>prestação continuada</b> (identificada pelo objeto: serviços contínuos, locação, "
        "limpeza, vigilância, manutenção, mão de obra, gerenciamento, licenças), o devido é o <b>pró-rata da "
        "vigência decorrida</b> até o corte (dias decorridos ÷ dias de vigência); para os demais objetos "
        "(aquisição, obra, serviço pontual), o devido é o valor global. O critério aplicado consta em cada "
        "contrato no anexo e no CSV.</p>"
        "<h4>3.4 Classificação e tolerância</h4>"
        f"<p>Diferença = pago − devido. <b>Conforme</b>: |diferença| abaixo de {tol} (parâmetros explícitos). "
        "<b>Pago a maior</b>: diferença positiva fora da tolerância — subdividido em <i>acima do valor global</i> "
        "(o pago supera o valor total atualizado do contrato) e <i>acima do pró-rata</i> (dentro do global, mas "
        "à frente da vigência decorrida). <b>Pago a menor</b>: diferença negativa fora da tolerância, separada em "
        "<i>vigência encerrada</i> (possível saldo, descumprimento ou dívida do Estado) e <i>em curso</i>. Um "
        "\"a menor\" só é afirmado se o credor não recebeu outras OBs na mesma UG em processo não vinculado a outro "
        "contrato, e se a coleta do SIAFE não está parcial na UG e no exercício; senão, é INDETERMINADO.</p>"
        "<h4>3.5 Cobertura temporal</h4>"
        "<p>O SIAFE-Rio está coberto a partir de 2021. Contrato com vigência iniciada antes disso é INDETERMINADO "
        "para efeito de pago a maior/menor.</p>"
        "<h4>3.6 Acréscimo acima do teto legal</h4>"
        "<p>Acréscimo quantitativo acima de 25% do valor inicial atualizado (50% para reforma de edifício ou de "
        "equipamento) é indício por si — Lei 14.133/2021, art. 125, ou Lei 8.666/1993, art. 65, §1º, conforme a "
        "data do contrato (no regime de transição, 2021–2023, cita-se ambos; o teto é idêntico). Prorrogação, "
        "reajuste e reequilíbrio não consomem o teto; termo misto é declarado como lacuna. O limite é inclusivo "
        "(\"até 25%\"): exatamente 25% é lícito.</p>")))

    for anc, num, esf, e in (("s4", 4, ESTADO, est), ("s5", 5, PREFEITURA, pre)):
        if not e:
            secoes.append(_sec(anc, f"{num}. Resultados — {esf}", "<p>Base indisponível nesta esfera.</p>"))
            continue
        sub = "".join(f"<li>{_E(SUBTIPO.get(s, s))}: {fmt_int(n)}</li>" for s, n in e["subtipos"].items())
        secoes.append(_sec(anc, f"{num}. Resultados — {esf}", (
            _tabela_resumo({esf: e})
            + f"<p>Pago determinado (soma do pago dos contratos classificados): "
              f"<b>R$ {fmt_brl(e['pago_determinado'])}</b>, contra devido de R$ {fmt_brl(e['devido_determinado'])}.</p>"
            + (f"<p>Pagos a maior por subtipo:</p><ul>{sub}</ul>" if sub else "")
            + "<h4>Motivos de indeterminação</h4>" + _tabela_motivos(e))))

    casos = []
    for esf in (ESTADO, PREFEITURA):
        lst = a_maior[esf]
        casos.append(f"<h3>{_E(esf)} — {fmt_int(len(lst))} contrato(s) pago(s) a maior</h3>")
        casos.extend(_prosa_caso(i, r) for i, r in enumerate(lst[:30], 1))
        if len(lst) > 30:
            casos.append(f"<p class='nota'>Exibidos em prosa os 30 maiores de {fmt_int(len(lst))}; os demais "
                         "constam, todos, no anexo (ordenados por diferença) e no CSV.</p>")
    secoes.append(_sec("s6", "6. Maiores casos de pagamento a maior", "".join(casos), quebra=True))

    est125 = [r for r in resultados if r["estouro_art125"]]
    afer = sum(1 for r in resultados if r["estouro_art125"] is not None)
    linhas125 = "".join(
        f"<tr><td>{_E(r['esfera'])}</td><td>{_E(campo_txt(r['orgao'], 45))}</td><td>{_E(r['contrato'])}</td>"
        f"<td class='n'>{fmt_brl(r['valor_inicial'])}</td><td class='n'>{(r['acrescimo_pct'] or 0) * 100:.2f}%</td>"
        f"<td class='n'>{(r['teto_acrescimo'] or 0) * 100:.0f}%</td><td>{_E(r['lei_teto'])}</td></tr>" for r in est125)
    secoes.append(_sec("s7", "7. Acréscimos acima do teto legal", (
        f"<p>O teto só é aferível quando há termos publicados com natureza identificável e valor inicial "
        f"conhecido: <b>{fmt_int(afer)}</b> contrato(s) nessa condição; <b>{fmt_int(len(est125))}</b> com "
        "acréscimo quantitativo acima do teto. Na Prefeitura, o Contas Rio publica apenas o valor atualizado — "
        "sem o valor inicial e a natureza de cada termo, o percentual não é aferível e nada é afirmado.</p>"
        + ("<table class='res'><thead><tr><th>Esfera</th><th>Órgão</th><th>Contrato</th><th>Valor inicial (R$)</th>"
           "<th>Acréscimo</th><th>Teto</th><th>Norma</th></tr></thead><tbody>" + linhas125 + "</tbody></table>"
           if est125 else ""))))

    dup = sorted([r for r in resultados if r["obs_mesma_nl"] or r["obs_mesma_competencia"]],
                 key=lambda r: -(r["valor_mesma_nl"] + r["valor_mesma_competencia"]))
    linhas_dup = "".join(
        f"<tr><td>{_E(campo_txt(r['orgao'], 45))}</td><td>{_E(r['contrato'])}<br>{_E(r['processo'])}</td>"
        f"<td>{_E(campo_txt(r['fornecedor'], 40))}</td><td>{_celula_cat(r['categoria'], r['subtipo'])}</td>"
        f"<td class='n'>{fmt_int(r['obs_mesma_nl'])}</td><td class='n'>{fmt_brl(r['valor_mesma_nl'])}</td>"
        f"<td class='n'>{fmt_int(r['obs_mesma_competencia'])}</td>"
        f"<td class='n'>{fmt_brl(r['valor_mesma_competencia'])}</td></tr>" for r in dup)
    secoes.append(_sec("s7b", "7-A. Sinais de pagamento em duplicidade (Estado)", (
        "<p>Entre as OBs vinculadas a cada contrato, dois padrões merecem conferência documental: (i) <b>mais de "
        "uma OB contabilizada para a mesma Nota de Liquidação e o mesmo valor</b> — a liquidação se paga uma "
        "vez; a segunda OB pode ser duplicidade ou reemissão após devolução bancária, o que só o extrato da "
        "conta pagadora esclarece; (ii) <b>OBs de mesmo valor e mesma competência com liquidações distintas</b> — "
        "em contrato de parcela fixa, é o padrão do pagamento em dobro da mesma competência, mas também é o de "
        "itens distintos de igual valor; só a nota fiscal fecha. Os sinais não alteram a classificação do "
        f"contrato. Contratos com algum sinal: <b>{fmt_int(len(dup))}</b>.</p>"
        + ("<table class='cons'><thead><tr><th>Órgão</th><th>Contrato / processo</th><th>Fornecedor</th>"
           "<th>Classificação</th><th>OBs extra mesma NL</th><th>Valor (R$)</th><th>OBs extra mesma competência</th>"
           "<th>Valor (R$)</th></tr></thead><tbody>" + linhas_dup + "</tbody></table>" if dup else ""))))

    desp = sorted([r for r in resultados if r["motivo"] == "valor_desproporcional"],
                  key=lambda r: (r["esfera"], -abs(r["diferenca"] or 0)))
    linhas_desp = "".join(
        f"<tr><td>{_E(r['esfera'])}</td><td>{_E(campo_txt(r['orgao'], 40))}</td><td>{_E(r['contrato'])}</td>"
        f"<td>{_E(campo_txt(r['fornecedor'], 38))}</td><td class='n'>{fmt_brl(r['valor_atualizado'])}</td>"
        f"<td class='n'>{fmt_brl(r['pago'])}</td>"
        f"<td class='n'>{fmt_brl((r['valor_atualizado'] or 0) / r['pago'] if r['pago'] else None)}</td></tr>"
        for r in desp)
    secoes.append(_sec("s7c", "7-B. Valores registrados desproporcionais ao pago", (
        f"<p>Em <b>{fmt_int(len(desp))}</b> contrato(s), o valor registrado e o pago estão a cem vezes ou mais um do "
        "outro (por exemplo, valor exatamente mil vezes o pago, típico de vírgula decimal deslocada no cadastro). "
        "Classificá-los como pagos a menor ou a maior somaria bilhões fictícios ao consolidado; por isso são "
        "INDETERMINADOS — mas listados aqui, integralmente, porque registro de valor errado em portal de "
        "transparência é, ele próprio, falha de controle a ser apontada.</p>"
        + ("<table class='cons'><thead><tr><th>Esfera</th><th>Órgão</th><th>Contrato</th><th>Fornecedor</th>"
           "<th>Valor registrado (R$)</th><th>Pago (R$)</th><th>Valor ÷ pago</th></tr></thead><tbody>"
           + linhas_desp + "</tbody></table>" if desp else ""))))

    cons_o = consolidar(resultados, "orgao")
    cons_f = consolidar(resultados, "fornecedor")
    secoes.append(_sec("s8", "8. Consolidado por órgão / UG", "".join(
        f"<h3>{_E(esf)}</h3>" + _tabela_consolidada([a for a in cons_o if a["esfera"] == esf], "Órgão / unidade")
        for esf in (ESTADO, PREFEITURA)), quebra=True))
    if volumes is None:
        corpo_f = ("<p>Todos os fornecedores, ordenados por excesso pago a maior. CPF de pessoa física mascarado.</p>"
                   + corpo_fornecedores(cons_f))
    else:
        top_f = [a for a in cons_f if a["n_a_maior"]][:40]
        corpo_f = ("<p>Abaixo, os fornecedores com contrato pago a maior (até 40, por excesso). A lista INTEGRAL — "
                   f"{fmt_int(len(cons_f))} fornecedores nas duas esferas — está no volume próprio indicado na "
                   "seção 11.</p>" + _tabela_consolidada(top_f, "Fornecedor"))
    secoes.append(_sec("s9", "9. Consolidado por fornecedor", corpo_f, quebra=True))

    secoes.append(_sec("s10", "10. Limitações e ressalvas", (
        "<ul>"
        "<li><b>No Estado, a indeterminação é majoritária — e isso é, em si, um achado de transparência.</b> O "
        "pagamento costuma tramitar em processo administrativo próprio, distinto do processo do contrato, e a OB "
        "não registra o número do contrato. Sem essa chave, atribuir OB a contrato pelo credor seria palpite.</li>"
        "<li>O TCE-RJ não publica termos aditivos: onde o PNCP também não os publica, o devido é o valor registrado, "
        "e prorrogação não refletida no valor pode produzir falso \"a maior\" em contrato contínuo — a ressalva "
        "aparece no contrato quando a vigência registrada excede um ano.</li>"
        "<li>A natureza continuada é inferida do objeto; o critério aplicado está em cada linha.</li>"
        "<li>Contrato encerrado recentemente pode ter saldo ainda não pago por defasagem normal entre liquidação e "
        "pagamento.</li>"
        "<li>Os totais do SIAFE são piso onde a coleta está parcial; por isso um \"a maior\" se sustenta com "
        "cobertura parcial, mas um \"a menor\" não.</li>"
        "<li>Prefeitura: o pago é o total publicado por contrato no SIAFIC-Rio, sem detalhamento de cada "
        "pagamento nesta base; não há data por pagamento, e o corte é a data da consulta.</li>"
        "</ul>")))

    if volumes is None:
        corpo_anexo = LEGENDA_ANEXO + "".join(
            f"<h3>{_E(esf)} — {fmt_int(len(b))} contratos</h3>" + _tabela_anexo(b)
            for esf, b in blocos_por_esfera(resultados))
    else:
        corpo_anexo = (
            "<p>Com mais de cinquenta mil contratos, a tabela integral não cabe num único arquivo de impressão: ela "
            "segue em volumes numerados, com a numeração dos contratos CONTÍNUA entre as partes de cada esfera. "
            "Nada foi cortado — a soma das linhas dos volumes é igual ao número de contratos da base, e isso foi "
            "conferido na geração.</p>"
            "<table class='res'><thead><tr><th>Volume</th><th>Conteúdo</th><th>Linhas</th></tr></thead><tbody>"
            + "".join(f"<tr><td class='mono'>{_E(v['arquivo'])}</td><td>{_E(v['conteudo'])}</td>"
                      f"<td class='n'>{fmt_int(v['linhas'])}</td></tr>" for v in volumes)
            + "</tbody></table>")
    secoes.append(_sec("s11", "11. Anexo — tabela por contrato (todos os contratos)", corpo_anexo, quebra=True))

    return {
        "classificacao": "RESERVADO — PERÍCIA CONTÁBIL",
        "titulo": "Perícia Contábil de Contratos — Valor Devido × Valor Pago",
        "subtitulo": (f"Estado do RJ ({fmt_int(est.get('n', 0))} contratos) e Prefeitura do Rio "
                      f"({fmt_int(pre.get('n', 0))} contratos) · esferas apuradas separadamente"),
        "data": emitido.strftime("%d/%m/%Y"),
        "metodologia": "Confronto devido × pago por Ordem Bancária contabilizada; Lei 4.320/64, arts. 58–65",
        "sem_indice": True,
        "top_flags": [f"{esf}: {fmt_int(rs[esf]['A_MAIOR'])} a maior · R$ {fmt_brl(rs[esf]['excesso_a_maior'])}"
                      for esf in (ESTADO, PREFEITURA) if esf in rs],
        "secoes": secoes,
        "proveniencia": [
            {"dado": "Contratos do Estado", "estado": "REAL", "fonte": "TCE-RJ — Dados Abertos (contratos_estado)",
             "data": "coleta mais recente"},
            {"dado": "Ordens Bancárias (Estado)", "estado": "REAL", "fonte": "SIAFE-Rio — OB Orçamentária",
             "data": cortes[ESTADO]},
            {"dado": "Termos aditivos (Estado)", "estado": "REAL", "fonte": "PNCP — termos de contrato",
             "data": "coleta mais recente"},
            {"dado": "Contratos e pagos (Prefeitura)", "estado": "REAL",
             "fonte": "Contas Rio — SIAFIC-Rio (consulta CCON)", "data": cortes[PREFEITURA]},
        ],
        "ressalva": ("Indícios para apuração; presunção de legitimidade dos atos administrativos. Nenhum dado "
                     "indisponível foi fabricado; INDETERMINADO não equivale a zero. CPF de pessoa física mascarado."),
        "_dados": {"resumo": rs, "n_base": n_base},
    }


async def _pdf_paginado(html_path: str, destino: str, timeout_s: float = 3600.0) -> str:
    """Mesmo motor do `render_html.html_to_pdf` (Playwright, A4), com rodapé NUMERADO — pedido
    expresso desta peça ("numeração de páginas"), diferente da diretriz geral sem numeração.

    Lê o HTML do DISCO (`goto file://`): com ~55 mil contratos o documento passa de 25 MB, e o
    `set_content` estoura o timeout padrão de 30 s do Playwright antes de terminar de carregar."""
    import asyncio

    from playwright.async_api import async_playwright

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = await b.new_page()
            page.set_default_timeout(timeout_s * 1000)
            await asyncio.wait_for(page.goto(Path(html_path).resolve().as_uri(), wait_until="load"), timeout_s)
            await asyncio.wait_for(page.pdf(
                path=destino, format="A4", print_background=True, display_header_footer=True,
                header_template="<span></span>",
                footer_template=("<div style='font-family:Georgia,serif;font-size:7.5px;color:#888;width:100%;"
                                 "padding:0 12mm;display:flex;justify-content:space-between;'>"
                                 "<span>Controle Externo — RJ · Perícia contábil de contratos · indícios, nunca "
                                 "acusação</span><span>Página <span class='pageNumber'></span> de "
                                 "<span class='totalPages'></span></span></div>"),
                margin={"top": "12mm", "bottom": "13mm", "left": "9mm", "right": "9mm"}), timeout_s)
        finally:
            await b.close()
    return destino


def garantir_neutro_exceto_dados(html: str, resultados: list[dict]) -> None:
    """Gate de neutralidade sobre o TEXTO PRÓPRIO do relatório. Nome de terceiro não é vazamento: a base
    real tem fornecedor chamado "Instituto Hermes Pardini", e o gate por palavra o confundia com um nome
    interno (o mesmo erro do 'iterj' — `reporting/neutralidade`). Remove-se o que veio da fonte e o resto
    tem de sair limpo."""
    from compliance_agent.reporting.neutralidade import garantir_neutro

    campos = ("fornecedor", "orgao", "objeto", "processo", "contrato", "ressalvas")
    neutros = [{**r, **{c: "x" for c in campos}} for r in resultados]
    ctx = montar_ctx(neutros, n_base={})
    texto = " ".join([ctx["titulo"], ctx["subtitulo"], ctx["ressalva"], *ctx["top_flags"],
                      *(s["titulo"] + s["html"] for s in ctx["secoes"])])
    garantir_neutro(texto, "perícia contábil")
    # e o documento final só pode conter termo listado se ele vier de nome de terceiro
    from compliance_agent.reporting.neutralidade import termos_proibidos
    dados = " ".join(str(r.get(c) or "") for r in resultados for c in campos).lower()
    sobra = [t for t in termos_proibidos(html) if t.lower() not in dados]
    if sobra:
        raise AssertionError(f"perícia contábil contém termo interno proibido: {sobra}")


LINHAS_POR_VOLUME = 8_000   # medido: 54.638 linhas num só HTML (28,5 MB) → Chromium a 5 GB e "Printing failed"
NOME_BASE = "pericia-contabil-contratos"


def planejar_volumes(resultados: list[dict], por_volume: int = LINHAS_POR_VOLUME) -> list[dict]:
    """Fatia o anexo em volumes com numeração CONTÍNUA por esfera. Soma das linhas = base."""
    vols = []
    for letra, (esf, bloco) in zip("AB", blocos_por_esfera(resultados)):
        partes = max(1, -(-len(bloco) // por_volume))
        for k in range(partes):
            fatia = bloco[k * por_volume:(k + 1) * por_volume]
            ini = k * por_volume + 1
            vols.append({"arquivo": f"{NOME_BASE}-anexo-{letra}{k + 1}.pdf", "esfera": esf, "itens": fatia,
                         "inicio": ini, "linhas": len(fatia),
                         "conteudo": f"Anexo {letra} — {esf}, parte {k + 1}/{partes}: contratos "
                                     f"{fmt_int(ini)} a {fmt_int(ini + len(fatia) - 1)} de {fmt_int(len(bloco))}"})
    return vols


def gerar(saida: str | Path, *, db: str | Path = _DB, db_pcrj: str | Path = _DB_PCRJ, pdf: bool = True,
          reusar: bool = False) -> dict:
    """Roda as duas esferas e grava: CSV integral, volume principal e volumes anexos (HTML + PDF A4
    paginado). Confere que a soma das linhas dos anexos é igual ao número de contratos da base."""
    import asyncio
    import pickle

    from compliance_agent.reporting.neutralidade import termos_proibidos
    from compliance_agent.reporting.render_html import render_html

    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    cache = saida / ".resultados.pkl"
    if reusar and cache.exists():
        res = [mascarar_textos(r) for r in pickle.loads(cache.read_bytes())]
    else:
        res = avaliar_estado(db) + avaliar_prefeitura(db_pcrj)
        cache.write_bytes(pickle.dumps(res))
    n_base = {e: sum(1 for r in res if r["esfera"] == e) for e in (ESTADO, PREFEITURA)}
    escrever_csv(ordenar(res), saida / f"{NOME_BASE}.csv")

    vols = planejar_volumes(res)
    cons_f = consolidar(res, "fornecedor")
    docs = [(f"{NOME_BASE}.pdf", render_html(montar_ctx(res, n_base=n_base, volumes=[
        *({k: v for k, v in x.items() if k != "itens"} for x in vols),
        {"arquivo": f"{NOME_BASE}-anexo-C-fornecedores.pdf", "conteudo": "Anexo C — consolidado integral por "
         "fornecedor, duas esferas", "linhas": len(cons_f)}])))]
    linhas = 0
    for v in vols:
        html = render_html(montar_ctx_volume(
            f"Perícia Contábil de Contratos — {v['conteudo'].split(':')[0]}", v["conteudo"],
            LEGENDA_ANEXO + f"<h3>{_E(v['esfera'])}</h3>" + _tabela_anexo(v["itens"], v["inicio"])))
        linhas += html.count(MARCA_LINHA_ANEXO)
        docs.append((v["arquivo"], html))
    docs.append((f"{NOME_BASE}-anexo-C-fornecedores.pdf", render_html(montar_ctx_volume(
        "Perícia Contábil de Contratos — Anexo C — Consolidado por fornecedor",
        f"{fmt_int(len(cons_f))} fornecedores · esferas separadas · CPF mascarado", corpo_fornecedores(cons_f)))))
    if linhas != len(res):
        raise AssertionError(f"anexos com {linhas} linhas para {len(res)} contratos")
    tudo_html = "\n".join(h for _, h in docs)
    garantir_neutro_exceto_dados(tudo_html, res)
    out = {"csv": str(saida / f"{NOME_BASE}.csv"), "n_base": n_base, "linhas_anexo": linhas,
           "termos_em_nomes_de_terceiros": termos_proibidos(tudo_html), "arquivos": [], "resumo": resumo(res)}
    for nome, html in docs:
        hp = saida / nome.replace(".pdf", ".html")
        hp.write_text(html, encoding="utf-8")
        if pdf:
            asyncio.run(_pdf_paginado(str(hp), str(saida / nome)))
        out["arquivos"].append(str(saida / nome) if pdf else str(hp))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Perícia contábil de todos os contratos (devido × pago).")
    ap.add_argument("--saida", required=True)
    ap.add_argument("--db", default=_DB)
    ap.add_argument("--pcrj-db", default=_DB_PCRJ)
    ap.add_argument("--sem-pdf", action="store_true")
    ap.add_argument("--reusar", action="store_true", help="reusa a varredura gravada em --saida (.resultados.pkl)")
    a = ap.parse_args(argv)
    out = gerar(a.saida, db=a.db, db_pcrj=a.pcrj_db, pdf=not a.sem_pdf, reusar=a.reusar)
    print({k: v for k, v in out.items() if k != "resumo"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
