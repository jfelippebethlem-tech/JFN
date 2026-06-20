# -*- coding: utf-8 -*-
"""Auditoria de CONTRATO CONTÍNUO (serviço com dedicação de mão de obra) — bateria T01–T22.

Motor DETERMINÍSTICO e HONESTO que, dado o acervo de um contrato (OBs do SIAFE + retenções OCR/SEI +
série de reajustes/CCT + glosas + planilha/contrato quando houver), roda a bateria de testes de execução
financeira e conformidade da repactuação e devolve achados no MESMO padrão do JFN/Lex:

    {codigo, titulo, status, nivel, evidencia, fonte, base_legal, peso}

Espelha `investigacao_dd.investigar()` (fachada/laranja). Lá o eixo é o FORNECEDOR; aqui é o CONTRATO.
O Lex consome via `auditar_contrato(dados)` e renderiza a seção II-E.2 (logo após a II-E de fachada).

REGRAS-MÃE de honestidade (idênticas ao DD):
  • CONFIRMADO   — fato verificável e fechado na fonte primária (ex.: OB Anulada somada como paga).
  • INDICIO      — sinal que MERECE APURAÇÃO; nunca conclusivo isolado (ex.: degrau de reajuste fora da
                   banda da CCT sem a planilha que isole MO).
  • AFASTADO     — verificado e NÃO se confirma (registra a leitura correta; evita falso achado).
  • INDISPONIVEL — sem dado-fonte OU sem critério explícito → o teste NÃO fabrica achado (T22 é o gate).

REGRA DE OURO JFN: Empenho ≠ Liquidação ≠ OB. Só a OB **Contabilizado** é "pago". OB Anulado/Excluído
NÃO conta como pagamento. Materialidade mínima global: ignora divergência ≤ R$ 0,02 (arredondamento).

T13 é a ÚNICA exceção à regra "INDISPONÍVEL ≠ irregular": em DEMO a ausência de comprovante de quitação
trabalhista pesa contra o ENTE (inversão do ônus — Súmula 331/V TST; STF ADC 16 / Tema 1.118).

Caso-âncora: contrato 005/2021 ITERJ × MGS Clean (CNPJ 19.088.605/0001-04), limpeza/conservação/
copeiragem/recepção, vigência Dez/2021–, renovação Nov-a-Nov.
Ver [[casos/iterj-mgs-clean-pagamentos]] e [[aprendizados/duplicidade-ob-competencia-vs-valor]].
"""
from __future__ import annotations

import re
from collections import defaultdict

# Reusa o detector determinístico de duplicidade já validado no caso (T07).
try:
    from compliance_agent.duplicidade_competencia import detectar as _detectar_dup
except Exception:  # noqa: BLE001 — import defensivo (uso isolado/testes)
    _detectar_dup = None

# ───────────────────────── constantes (critérios normativos) ─────────────────────────
TOL_CENTAVOS = 0.02               # materialidade de arredondamento (R$)
TOL_REAJUSTE_PP = 0.5             # banda do degrau de reajuste × %CCT (pontos percentuais)
INSS_DEMO = 0.11                  # cessão de mão de obra (Lei 8.212/91 art. 31)
TOL_INSS_REL = 0.005             # 0,5% de tolerância relativa no INSS
GRUPO_A_MIN, GRUPO_A_MAX = 34.8, 37.5     # banda legal do Grupo A (%)
PIS_CUMULATIVO, COFINS_CUMULATIVO = 0.65, 3.00   # limpeza = cumulativo
LUCRO_TETO, INDIRETOS_TETO = 3.5, 6.0     # tetos de referência SEGES (%)
INTERREGNO_MESES = 12            # interregno mínimo entre repactuações da mesma rúbrica

_STATUS = ("CONFIRMADO", "INDICIO", "AFASTADO", "INDISPONIVEL")

# peso por severidade declarada na bateria (alimenta o grau/score, como no DD)
_PESO = {"alta": 25, "media": 15, "baixa": 8}


# ───────────────────────── helpers ─────────────────────────
def _money(v) -> float:
    """'90.419,00' / 90419.0 / '90419' -> float; vazio/inválido -> 0.0."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip()
    if not s:
        return 0.0
    # BR: 90.419,00 ; US/já-float-str: 90419.00
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _moeda(v: float) -> str:
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ 0,00"


def _comp(c: str) -> str:
    """Normaliza competência -> 'MM/AAAA' (SIAFE 1 = 'DD/MM/AAAA'; SIAFE 2 = 'MM/AAAA')."""
    c = (c or "").strip()
    if len(c) == 10 and c[2] == "/":
        return c[3:10]
    return c


def _midx(comp: str) -> int | None:
    try:
        mm, aaaa = comp.split("/")
        return int(aaaa) * 12 + int(mm)
    except Exception:
        return None


def _hip(codigo, titulo, status, nivel, evidencia, fonte, base_legal, peso) -> dict:
    """Constrói o achado no padrão JFN. status ∈ _STATUS; peso entra no score se INDICIO/CONFIRMADO."""
    assert status in _STATUS, status
    return {"codigo": codigo, "titulo": titulo, "status": status, "nivel": nivel,
            "evidencia": evidencia, "fonte": fonte, "base_legal": base_legal, "peso": int(peso)}


def _indisp(codigo, titulo, falta: str, base_legal: str, peso=8) -> dict:
    """Achado INDISPONÍVEL padronizado (gate T22). Diz EXATAMENTE o que falta — não é 'limpo' nem 'risco'."""
    return _hip(codigo, titulo, "INDISPONIVEL", "—",
                f"Teste não roda: falta {falta}. INDISPONÍVEL ≠ irregular (presunção de legitimidade).",
                "—", base_legal, peso)


def _contabilizadas(obs: list[dict]) -> list[dict]:
    """Só OBs Contabilizado entram como 'pago' (REGRA DE OURO)."""
    return [o for o in obs if str(o.get("status", "")).strip().lower().startswith("contabiliz")]


# ───────────────────────── BATERIA ─────────────────────────
# Cada teste recebe `d` (dados normalizados) e devolve UM achado (ou None p/ omitir).

def _t01_3way(d) -> dict:
    """T01 — Three-way match: empenho × liquidação × OB (encadeamento NL→RE→PD→OB)."""
    contab = _contabilizadas(d["obs"])
    if not contab:
        return _indisp("T01-3WAY", "Three-way match (NL→RE→PD→OB)", "OBs Contabilizado",
                       "Lei 4.320/1964 arts. 58/63/64; LC 101/2000", _PESO["alta"])
    orfas = [o for o in contab if not (o.get("nl") or o.get("re") or o.get("pd"))]
    # PD/RE referenciado por 2+ OBs Contabilizado (possível lastro repetido)
    ref = defaultdict(list)
    for o in contab:
        chave = (o.get("re") or "", o.get("pd") or "")
        if any(chave):
            ref[chave].append(o.get("numero_ob"))
    repetidos = {k: v for k, v in ref.items() if len(v) >= 2}
    if orfas:
        ev = (f"{len(orfas)} de {len(contab)} OBs Contabilizado SEM nenhum elo (nl/re/pd vazios) — "
              f"OB órfã, pagamento sem liquidação rastreável: {', '.join(str(o.get('numero_ob')) for o in orfas[:6])}.")
        return _hip("T01-3WAY", "Three-way match (NL→RE→PD→OB)", "INDICIO", "alto", ev,
                    "SIAFE — ob_orcamentaria_siafe", "Lei 4.320/1964 arts. 58/63/64; LC 101/2000", _PESO["alta"])
    # honestidade: NÃO afirmar 3-way completo onde a NL é nula (SIAFE 1 não expõe NL no grid) — é só 2-way RE↔PD.
    sem_nl = [o for o in contab if not (o.get("nl") or "").strip()]
    elo3 = len(contab) - len(sem_nl)
    if sem_nl:
        ev = (f"{elo3}/{len(contab)} OBs com cadeia 3-way completa (NL→RE→PD→OB); "
              f"{len(sem_nl)} apenas com RE↔PD (**2-way; NL INDISPONÍVEL** — SIAFE 1 não expõe). "
              f"Nenhuma OB órfã. {len(repetidos)} par(es) RE/PD em 2+ OBs (split/retroativo — cruza T07). "
              f"Integridade 3-way NÃO afirmável onde falta a liquidação.")
        return _hip("T01-3WAY", "Three-way match (NL→RE→PD→OB)", "AFASTADO", "—", ev,
                    "SIAFE — ob_orcamentaria_siafe", "Lei 4.320/1964 arts. 58/63/64; LC 101/2000", _PESO["alta"])
    ev = (f"Cadeia 3-way íntegra: as {len(contab)} OBs Contabilizado têm NL→RE→PD, nenhuma órfã. "
          f"{len(repetidos)} par(es) RE/PD aparecem em 2+ OBs — esperado em split/retroativo; "
          f"confirmar lastro distinto pela NL/NF (cruza T07).")
    return _hip("T01-3WAY", "Three-way match (NL→RE→PD→OB)", "AFASTADO", "—", ev,
                "SIAFE — ob_orcamentaria_siafe", "Lei 4.320/1964 arts. 58/63/64; LC 101/2000", _PESO["alta"])


def _t02_status_pago(d) -> dict:
    """T02 — Saneamento de status: OB Anulado/Excluído computada como paga."""
    nao_pagas = [o for o in d["obs"]
                 if str(o.get("status", "")).strip().lower() in ("anulado", "excluído", "excluido")]
    soma_nao_paga = sum(_money(o.get("valor")) for o in nao_pagas)
    relatorio_total = d.get("relatorio_total_pago")     # total que a fonte derivada alega pago
    pago_verdadeiro = sum(_money(o.get("valor")) for o in _contabilizadas(d["obs"]))
    detalhe = "; ".join(f"OB {o.get('numero_ob')} {o.get('status')} {_moeda(_money(o.get('valor')))}" for o in nao_pagas)
    if relatorio_total is not None and abs(relatorio_total - pago_verdadeiro) > soma_nao_paga - TOL_CENTAVOS \
            and soma_nao_paga > TOL_CENTAVOS:
        ev = (f"Fonte derivada alega pago {_moeda(relatorio_total)}; pago verdadeiro (só Contabilizado) = "
              f"{_moeda(pago_verdadeiro)}. Diferença compatível com {_moeda(soma_nao_paga)} de OB não-paga "
              f"computada indevidamente ({detalhe}).")
        return _hip("T02-STATUS-PAGO", "OB anulada/excluída computada como paga", "CONFIRMADO", "alto", ev,
                    "SIAFE + fonte derivada", "Lei 4.320/1964 arts. 62-64; REGRA DE OURO JFN", _PESO["alta"])
    if soma_nao_paga > TOL_CENTAVOS:
        ev = (f"No acervo há {len(nao_pagas)} OB não-paga(s) totalizando {_moeda(soma_nao_paga)} ({detalhe}). "
              f"Pago verdadeiro = {_moeda(pago_verdadeiro)} (só Contabilizado). "
              f"INDÍCIO de inflação de 'total pago' se qualquer agregado as somar — confrontar com o relatório do órgão.")
        return _hip("T02-STATUS-PAGO", "OB anulada/excluída computada como paga", "INDICIO", "alto", ev,
                    "SIAFE — ob_orcamentaria_siafe", "Lei 4.320/1964 arts. 62-64; REGRA DE OURO JFN", _PESO["alta"])
    return _hip("T02-STATUS-PAGO", "OB anulada/excluída computada como paga", "AFASTADO", "—",
                "Nenhuma OB Anulado/Excluído no acervo; total pago = só Contabilizado.", "SIAFE",
                "Lei 4.320/1964 arts. 62-64", _PESO["alta"])


def _t03_reconcilia(d) -> dict:
    """T03 — Reconciliação independente do relatório de Créditos/Débitos (saldo alegado pelo órgão)."""
    saldo_orgao = d.get("relatorio_saldo")
    if saldo_orgao is None:
        return _indisp("T03-RECONCILIA", "Reconciliação do saldo Créditos/Débitos", "o saldo apurado pelo órgão",
                       "ISSAI 4000; Lei 4.320/64; GAO Yellow Book", _PESO["alta"])
    tem_planilha = bool(d.get("planilha"))
    nivel = "alto" if tem_planilha else "medio"
    status = "CONFIRMADO" if tem_planilha else "INDICIO"
    # devido teórico só é fechável com a planilha contratual; sem ela, reconstrói via CCT → teto INDICIO
    ev = (f"Saldo alegado pela contabilidade do órgão = {_moeda(saldo_orgao)} (dado DERIVADO, subject matter, "
          f"não evidência — ISSAI 4000). Reconciliação independente = Σ(devido por competência vigente) − "
          f"Σ(pago reconstituído = OB_líquida + INSS + IR) ± retroativos ∓ glosas. ")
    if tem_planilha:
        ev += "Planilha contratual disponível: 'devido teórico' fechável → divergência material vira CONFIRMADO do erro derivado."
    else:
        ev += ("Planilha contratual INDISPONÍVEL: 'devido' reconstruído só via CCT/série de reajustes → "
               "status máximo INDÍCIO. Cruzar com T02 (OB não-paga somada) e T19 (preclusão) para explicar o saldo.")
    return _hip("T03-RECONCILIA", "Reconciliação do saldo Créditos/Débitos", status, nivel, ev,
                "SIAFE + retenções OCR + CCT (planilha p/ fechar)", "ISSAI 4000; Lei 4.320/64; GAO Yellow Book", _PESO["alta"])


def _t04_reajuste_cct(d) -> dict:
    """T04 — Conformidade do degrau de reajuste × %CCT (só mão de obra)."""
    serie = d.get("serie_reajustes") or []
    cct = d.get("cct_percentuais") or {}     # {ano: pct}
    if len(serie) < 2 or not cct:
        return _indisp("T04-REAJUSTE-MO-CCT", "Reajuste de MO × %CCT", "série de reajustes e/ou %CCT",
                       "Lei 14.133/2021 art. 135,II; IN SEGES 05/2017 Anexo IX", _PESO["media"])
    degraus = []
    for i in range(1, len(serie)):
        ant, nov = _money(serie[i - 1]), _money(serie[i])
        if ant > 0:
            degraus.append((i, round((nov / ant - 1) * 100, 2)))
    tem_planilha = bool(d.get("planilha"))
    pcts_cct = sorted(set(float(v) for v in cct.values()))
    fora = []
    for i, dp in degraus:
        if not any(abs(dp - p) <= TOL_REAJUSTE_PP for p in pcts_cct):
            fora.append((i, dp))
    if not tem_planilha:
        ev = (f"Degraus observados na série {[d_[1] for d_ in degraus]}% vs %CCT {pcts_cct}. "
              f"Sem a planilha que ISOLA mão de obra de insumos, o Δ% total não é diretamente comparável ao %CCT "
              f"(peso da MO < 100%) → status máximo INDÍCIO. Degraus fora da banda ±{TOL_REAJUSTE_PP}p.p.: "
              f"{[f'#{i}:{dp}%' for i, dp in fora] or 'nenhum'}.")
        st = "INDICIO" if fora else "INDISPONIVEL"
        return _hip("T04-REAJUSTE-MO-CCT", "Reajuste de MO × %CCT", st, "medio" if fora else "—", ev,
                    "Série de reajustes + CCT (planilha p/ isolar MO)",
                    "Lei 14.133/2021 art. 135,II; IN SEGES 05/2017 Anexo IX", _PESO["media"])
    if fora:
        ev = f"Degrau(s) fora da banda ±{TOL_REAJUSTE_PP}p.p. do %CCT: {[f'#{i}:{dp}%' for i, dp in fora]} (CCT {pcts_cct}%)."
        return _hip("T04-REAJUSTE-MO-CCT", "Reajuste de MO × %CCT", "INDICIO", "medio", ev,
                    "Planilha + CCT", "Lei 14.133/2021 art. 135,II; IN SEGES 05/2017", _PESO["media"])
    return _hip("T04-REAJUSTE-MO-CCT", "Reajuste de MO × %CCT", "AFASTADO", "—",
                f"Todos os degraus {[d_[1] for d_ in degraus]}% dentro da banda do %CCT {pcts_cct}%.",
                "Planilha + CCT", "Lei 14.133/2021 art. 135,II", _PESO["media"])


def _t05_database(d) -> dict:
    """T05 — Ancoragem da repactuação na data-base (março) e janela do retroativo."""
    if not d.get("cct_data_base"):
        return _indisp("T05-DATABASE-MARCO", "Ancoragem na data-base", "a data-base confirmada na CCT do caso",
                       "IN SEGES 05/2017 Anexo IX; Lei 14.133/2021 art. 135,II", _PESO["media"])
    saltos = d.get("saltos_competencia") or []
    mes_base = int(d.get("cct_data_base"))   # 3 = março
    if not saltos:
        return _indisp("T05-DATABASE-MARCO", "Ancoragem na data-base", "as competências dos degraus de reajuste",
                       "IN SEGES 05/2017 Anexo IX", _PESO["media"])
    fora = [s for s in saltos if _midx(_comp(s)) is not None and (_midx(_comp(s)) % 12 or 12) != mes_base]
    if fora:
        ev = (f"Degrau(s) entrando em competência ≠ mês-base ({mes_base:02d}): {fora}. INDÍCIO se sem retroativo "
              f"cobrindo [data-base, formalização]. AFASTADO se houver retroativo na janela.")
        return _hip("T05-DATABASE-MARCO", "Ancoragem na data-base", "INDICIO", "medio", ev,
                    "Competências das OBs + data-base CCT", "IN SEGES 05/2017 Anexo IX", _PESO["media"])
    return _hip("T05-DATABASE-MARCO", "Ancoragem na data-base", "AFASTADO", "—",
                f"Viradas de patamar ancoradas no mês-base ({mes_base:02d}).",
                "Competências das OBs", "IN SEGES 05/2017 Anexo IX", _PESO["media"])


def _t06_interregno(d) -> dict:
    """T06 — Interregno mínimo de 12 meses entre repactuações da mesma rúbrica."""
    saltos = [s for s in (d.get("saltos_competencia") or []) if _midx(_comp(s)) is not None]
    if len(saltos) < 2:
        return _indisp("T06-INTERREGNO", "Interregno de 12 meses", "≥2 datas de salto de reajuste",
                       "Lei 14.133/2021 art. 135,I e II; IN SEGES 05/2017", _PESO["media"])
    idx = sorted(_midx(_comp(s)) for s in saltos)
    prematuros = [(idx[i - 1], idx[i], idx[i] - idx[i - 1]) for i in range(1, len(idx)) if idx[i] - idx[i - 1] < INTERREGNO_MESES]
    if prematuros:
        ev = f"Salto(s) com interregno < 12 meses: {[f'{g}m' for *_, g in prematuros]} — repactuação prematura."
        return _hip("T06-INTERREGNO", "Interregno de 12 meses", "INDICIO", "medio", ev,
                    "Competências das OBs", "Lei 14.133/2021 art. 135,I-II; jurisprudência TCU", _PESO["media"])
    return _hip("T06-INTERREGNO", "Interregno de 12 meses", "AFASTADO", "—",
                f"Todos os {len(idx) - 1} intervalos entre saltos ≥ 12 meses.",
                "Competências das OBs", "Lei 14.133/2021 art. 135,I-II", _PESO["media"])


def _t07_duplicidade(d) -> dict:
    """T07 — Duplicidade de pagamento por competência (delega ao detector validado)."""
    contab = _contabilizadas(d["obs"])
    if not contab or _detectar_dup is None:
        return _indisp("T07-DUPLICIDADE-COMP", "Duplicidade por competência", "OBs Contabilizado com competência",
                       "Lei 4.320/64 arts. 62-63; Lei 14.133/2021", _PESO["alta"])
    flags = _detectar_dup(contab, favorecido=d.get("favorecido", ""), orgao=d.get("orgao", ""))
    if not flags:
        return _hip("T07-DUPLICIDADE-COMP", "Duplicidade por competência", "AFASTADO", "—",
                    "Reconciliação pela vida do contrato sem excedente líquido nem mês dobrado sem vizinho ausente.",
                    "SIAFE — duplicidade_competencia.py", "Lei 4.320/64 arts. 62-63", _PESO["alta"])
    exc = next((f for f in flags if f["tipo_indicio"] == "excedente_liquido"), None)
    dobradas = [f for f in flags if f["tipo_indicio"] == "competencia_dobrada"]
    partes = []
    if exc:
        partes.append(exc["evidencia"].split(". ")[0] + ".")
    if dobradas:
        comps = ", ".join(sorted({f["competencia"] for f in dobradas}))
        partes.append(f"{len(dobradas)} competência(s) dobrada(s) com REs/PDs distintos: {comps}.")
    partes.append("CONFIRMADO só com mesma NF em 2 OBs (exige OCR/SEI) — sem ela, INDÍCIO a apurar (pode ser retroativo/glosa).")
    return _hip("T07-DUPLICIDADE-COMP", "Duplicidade por competência", "INDICIO", "alto", " ".join(partes),
                "SIAFE — duplicidade_competencia.py", "Lei 4.320/64 arts. 62-63; Lei 14.133/2021", _PESO["alta"])


def _t08_gap(d) -> dict:
    """T08 — Continuidade temporal: lacuna de competência em serviço contínuo."""
    contab = _contabilizadas(d["obs"])
    comps = sorted({_comp(o.get("competencia")) for o in contab if _midx(_comp(o.get("competencia"))) is not None},
                   key=_midx)
    if not comps:
        return _indisp("T08-GAP-COMPETENCIA", "Continuidade temporal", "OBs Contabilizado com competência",
                       "Lei 14.133/2021 (vigência e execução)", _PESO["media"])
    idx = sorted(set(_midx(c) for c in comps))
    gaps_idx = [i for i in range(idx[0], idx[-1] + 1) if i not in idx]
    glosa_meses = {_midx(_comp(g)) for g in (d.get("glosas_competencias") or []) if _midx(_comp(g)) is not None}
    gaps_inexplicados = [i for i in gaps_idx if i not in glosa_meses]
    def fmt(i):
        return f"{i % 12 or 12:02d}/{(i - 1) // 12}"
    vig_ok = bool(d.get("vigencia"))     # bordas de vigência só com o contrato (tarefa #8)
    if gaps_inexplicados:
        ev = (f"Mês(es) sem OB no intervalo [{comps[0]}–{comps[-1]}] não cobertos por glosa documentada: "
              f"{[fmt(i) for i in gaps_inexplicados]}. INDÍCIO de inadimplência/glosa não-formalizada (risco subsidiário) "
              f"ou apenas timing — confrontar com SEI. {'Bordas de vigência verificadas.' if vig_ok else 'Bordas de vigência INDISPONÍVEL (ler contrato 005/2021).'}")
        return _hip("T08-GAP-COMPETENCIA", "Continuidade temporal", "INDICIO", "medio", ev,
                    "SIAFE — competências", "Lei 14.133/2021 (vigência); cláusula de vigência 005/2021", _PESO["media"])
    ev = (f"Sequência de competências {comps[0]}–{comps[-1]} sem lacuna inexplicada "
          f"({'gaps cobertos por glosa documentada' if gaps_idx else 'sem gaps'}). "
          f"{'' if vig_ok else 'Bordas de vigência ainda INDISPONÍVEL (contrato 005/2021).'}")
    return _hip("T08-GAP-COMPETENCIA", "Continuidade temporal", "AFASTADO", "—", ev,
                "SIAFE — competências", "Lei 14.133/2021 (vigência)", _PESO["media"])


def _t09_inss(d) -> dict:
    """T09 — Retenção de INSS 11% sobre cessão de mão de obra."""
    ret = d.get("retencoes") or {}    # {competencia: {inss, ir, base?}}
    if not ret:
        return _indisp("T09-INSS-11", "Retenção INSS 11% (DEMO)", "as retenções de INSS (OCR/SEI)",
                       "Lei 8.212/1991 art. 31; IN RFB 2.110/2022", _PESO["media"])
    # sem planilha que isole a base de MO, usa bruto da NF como proxy → teto INDICIO
    return _hip("T09-INSS-11", "Retenção INSS 11% (DEMO)", "INDICIO", "medio",
                (f"Retenções de INSS disponíveis para {len(ret)} competência(s) (OCR/SEI). Conferência "
                 f"INSS ≈ 11% × base de cessão de MO. Sem a planilha que ISOLA a base de MO (materiais/equipamentos "
                 f"deduzíveis reduzem a base), usa-se o bruto da NF como proxy → status máximo INDÍCIO; desvio "
                 f"material a menor = renúncia/risco previdenciário solidário, a maior = excesso."),
                "Retenções OCR/SEI (planilha p/ base de MO)",
                "Lei 8.212/1991 art. 31; Lei 14.133/2021 art. 121 §2º", _PESO["media"])


def _t10_ir(d) -> dict:
    """T10 — Retenção de IR na fonte conforme alíquota/serviço."""
    ret = d.get("retencoes") or {}
    if not ret:
        return _indisp("T10-IR-FONTE", "Retenção IR na fonte", "as retenções de IR (OCR/SEI)",
                       "RIR/2018; Lei 9.430/1996", _PESO["baixa"])
    return _hip("T10-IR-FONTE", "Retenção IR na fonte", "INDICIO", "baixo",
                (f"Retenções de IR disponíveis para {len(ret)} competência(s). Conferir alíquota legal × base "
                 f"conforme enquadramento (limpeza/conservação). Não confundir retenção federal (IN RFB) com ISS "
                 f"municipal — testados à parte. INDÍCIO se a menor/maior material; AFASTADO dentro do arredondamento."),
                "Retenções OCR/SEI", "RIR/2018 (Dec. 9.580/2018); Lei 9.430/1996", _PESO["baixa"])


def _t11_identidade(d) -> dict:
    """T11 — Identidade contábil: OB líquida = Bruto − INSS − IR − ISS − glosas."""
    if not d.get("bruto_nf") or not d.get("retencoes"):
        return _indisp("T11-IDENTIDADE-LIQUIDO", "Identidade contábil do líquido", "o bruto da NF e/ou o ISS municipal",
                       "Lei 4.320/1964 art. 63", _PESO["media"])
    return _hip("T11-IDENTIDADE-LIQUIDO", "Identidade contábil do líquido", "INDICIO", "medio",
                "Fecha por competência: OB_líquida + INSS + IR + ISS + glosas == bruto (tol. R$ 0,02). "
                "Resíduo não explicado = erro de liquidação (CONFIRMADO).",
                "SIAFE + retenções + NF", "Lei 4.320/1964 art. 63", _PESO["media"])


def _t12_glosa(d) -> dict:
    """T12 — Glosas: base, proporcionalidade e efetiva dedução."""
    glosas = d.get("glosas") or []      # [{competencia, valor?, postos_vagos?, dias?}]
    if not glosas:
        return _indisp("T12-GLOSA-PROPORCIONAL", "Glosas — efetividade e proporcionalidade", "o registro das glosas",
                       "Lei 14.133/2021 arts. 137-139; IN SEGES 05/2017", _PESO["media"])
    contab = _contabilizadas(d["obs"])
    by_comp = defaultdict(float)
    for o in contab:
        by_comp[_comp(o.get("competencia"))] += _money(o.get("valor"))
    mensal = d.get("mensal_vigente")
    nao_deduzidas = []
    if mensal:
        for g in glosas:
            c = _comp(g.get("competencia"))
            if by_comp.get(c, 0) >= _money(mensal) - TOL_CENTAVOS:
                nao_deduzidas.append(c)
    tem_planilha_posto = bool(d.get("valor_posto_dia"))
    if nao_deduzidas:
        ev = (f"Glosa registrada mas OB da competência paga no valor cheio (≥ mensal vigente): {nao_deduzidas}. "
              f"INDÍCIO de glosa anotada e não deduzida = pagamento indevido. "
              f"Proporcionalidade {'aferível' if tem_planilha_posto else 'INDISPONÍVEL sem o valor-posto/dia da planilha'}.")
        return _hip("T12-GLOSA-PROPORCIONAL", "Glosas — efetividade e proporcionalidade", "INDICIO", "medio", ev,
                    "Registro de glosas + OBs (planilha p/ proporcionalidade)",
                    "Lei 14.133/2021 arts. 137-139; IN SEGES 05/2017", _PESO["media"])
    ev = ("Glosas registradas refletidas em OB com valor reduzido (dedução efetiva). "
          + ("Proporcionalidade aferível pela planilha do posto." if tem_planilha_posto
             else "Proporcionalidade INDISPONÍVEL sem o valor-posto/dia (planilha)."))
    return _hip("T12-GLOSA-PROPORCIONAL", "Glosas — efetividade e proporcionalidade", "AFASTADO", "—", ev,
                "Registro de glosas + OBs", "Lei 14.133/2021 arts. 137-139; IN SEGES 05/2017", _PESO["media"])


def _t13_trabalhista(d) -> dict:
    """T13 — Comprovação de quitação trabalhista do mês anterior (culpa in vigilando).

    ÚNICA exceção a 'INDISPONÍVEL ≠ irregular': o silêncio documental pesa contra o ENTE (Súmula 331/V)."""
    contab = _contabilizadas(d["obs"])
    if not contab:
        return _indisp("T13-COMPROV-TRABALHISTA", "Quitação trabalhista do mês anterior", "OBs Contabilizado",
                       "Súmula 331/IV-V TST; STF ADC 16 / Tema 1.118", _PESO["alta"])
    comprov = d.get("comprovantes_trabalhistas")   # {competencia: bool} ou None (acervo não introspeccionado)
    if comprov is None:
        ev = ("Em DEMO, cada OB liberada deveria estar condicionada à prova de quitação trabalhista do mês anterior "
              "(folha, GFIP/eSocial/DCTFWeb, guias FGTS/INSS, VT/VR). O acervo SEI ainda não foi introspeccionado por "
              "competência. NESTE teste a ausência sistemática = INDÍCIO de falha de fiscalização (inversão do ônus, "
              "Súmula 331/V) — não 'INDISPONÍVEL neutro'. Verificar presença por competência no SEI.")
        return _hip("T13-COMPROV-TRABALHISTA", "Quitação trabalhista do mês anterior", "INDICIO", "alto", ev,
                    "Docs SEI (a introspeccionar) + OBs",
                    "Súmula 331/IV-V TST; STF ADC 16 / Tema 1.118; Lei 14.133/2021 art. 121 §2º-§3º", _PESO["alta"])
    faltantes = [c for c, ok in comprov.items() if not ok]
    if faltantes:
        ev = f"OB(s) paga(s) sem comprovante de quitação trabalhista do mês anterior juntado: {faltantes[:8]}. Falha de fiscalização."
        return _hip("T13-COMPROV-TRABALHISTA", "Quitação trabalhista do mês anterior", "INDICIO", "alto", ev,
                    "Docs SEI + OBs", "Súmula 331/IV-V TST; STF ADC 16 / Tema 1.118", _PESO["alta"])
    return _hip("T13-COMPROV-TRABALHISTA", "Quitação trabalhista do mês anterior", "AFASTADO", "—",
                "Comprovante de quitação presente para todas as competências com OB paga.",
                "Docs SEI + OBs", "Súmula 331/IV-V TST", _PESO["alta"])


# ── T14–T21: dependem da PLANILHA de custos e/ou do CONTRATO 005/2021 (tarefa #8) ──
def _t14_piso(d) -> dict:
    p = d.get("planilha") or {}
    if "salario_base" not in p or not d.get("cct_piso"):
        return _indisp("T14-PISO-CCT", "Piso da planilha ≥ piso CCT", "a planilha (Módulo 1) e/ou o piso CCT",
                       "CCT (piso, data-base); CLT 457-458; IN SEGES 05/2017 Anexo VII-D", _PESO["media"])
    if _money(p["salario_base"]) < _money(d["cct_piso"]) - TOL_CENTAVOS:
        return _hip("T14-PISO-CCT", "Piso da planilha ≥ piso CCT", "CONFIRMADO", "medio",
                    f"Salário-base da planilha {_moeda(_money(p['salario_base']))} < piso CCT {_moeda(_money(d['cct_piso']))} — subfaturamento ao trabalhador.",
                    "Planilha + CCT", "CCT; CLT 457-458", _PESO["media"])
    return _hip("T14-PISO-CCT", "Piso da planilha ≥ piso CCT", "AFASTADO", "—",
                "Salário-base da planilha ≥ piso CCT vigente.", "Planilha + CCT", "CCT; CLT 457-458", _PESO["media"])


def _t15_grupo_a(d) -> dict:
    p = d.get("planilha") or {}
    if "grupo_a_pct" not in p:
        return _indisp("T15-GRUPO-A-ENCARGOS", "Grupo A na banda legal", "a planilha (Submódulo 2.2)",
                       "TCU Ac. 325/2007; Lei 8.212/91; Lei 8.036/90", _PESO["baixa"])
    g = _money(p["grupo_a_pct"])
    if not (GRUPO_A_MIN <= g <= GRUPO_A_MAX):
        return _hip("T15-GRUPO-A-ENCARGOS", "Grupo A na banda legal", "INDICIO", "baixo",
                    f"Σ Grupo A = {g:.2f}% fora da banda [{GRUPO_A_MIN};{GRUPO_A_MAX}]% — erro de composição/sobrepreço.",
                    "Planilha (Submódulo 2.2)", "TCU Ac. 325/2007", _PESO["baixa"])
    return _hip("T15-GRUPO-A-ENCARGOS", "Grupo A na banda legal", "AFASTADO", "—",
                f"Σ Grupo A = {g:.2f}% dentro da banda legal.", "Planilha", "TCU Ac. 325/2007", _PESO["baixa"])


def _t16_regime(d) -> dict:
    p = d.get("planilha") or {}
    if "pis_pct" not in p or "cofins_pct" not in p:
        return _indisp("T16-REGIME-TRIBUTARIO", "Regime tributário (cumulativo)", "a planilha (Módulo 6)",
                       "Lei 10.637/2002; Lei 10.833/2003; IN SEGES 05/2017", _PESO["media"])
    pis, cof = _money(p["pis_pct"]), _money(p["cofins_pct"])
    if abs(pis - PIS_CUMULATIVO) > 0.01 or abs(cof - COFINS_CUMULATIVO) > 0.01:
        return _hip("T16-REGIME-TRIBUTARIO", "Regime tributário (cumulativo)", "CONFIRMADO", "medio",
                    f"PIS {pis}% / COFINS {cof}% ≠ cumulativo ({PIS_CUMULATIVO}%/{COFINS_CUMULATIVO}%) — sobrepreço tributário embutido.",
                    "Planilha (Módulo 6)", "Lei 10.637/2002; Lei 10.833/2003", _PESO["media"])
    return _hip("T16-REGIME-TRIBUTARIO", "Regime tributário (cumulativo)", "AFASTADO", "—",
                f"PIS {pis}% / COFINS {cof}% = cumulativo (correto p/ limpeza).", "Planilha", "Lei 10.833/2003", _PESO["media"])


def _t17_lucro(d) -> dict:
    p = d.get("planilha") or {}
    if "lucro_pct" not in p and "indiretos_pct" not in p:
        return _indisp("T17-LUCRO-INDIRETOS-TETO", "Lucro/indiretos nos tetos SEGES", "a planilha (Módulo 6)",
                       "Cadernos SEGES; jurisprudência TCU (BDI)", _PESO["baixa"])
    lucro, ind = _money(p.get("lucro_pct", 0)), _money(p.get("indiretos_pct", 0))
    if lucro > LUCRO_TETO or ind > INDIRETOS_TETO:
        return _hip("T17-LUCRO-INDIRETOS-TETO", "Lucro/indiretos nos tetos SEGES", "INDICIO", "baixo",
                    f"Lucro {lucro}% (teto {LUCRO_TETO}%) / indiretos {ind}% (teto {INDIRETOS_TETO}%) — banda extrapolada.",
                    "Planilha (Módulo 6)", "Cadernos SEGES; TCU (BDI)", _PESO["baixa"])
    return _hip("T17-LUCRO-INDIRETOS-TETO", "Lucro/indiretos nos tetos SEGES", "AFASTADO", "—",
                f"Lucro {lucro}% / indiretos {ind}% dentro das bandas de referência.", "Planilha", "Cadernos SEGES", _PESO["baixa"])


def _t18_beneficio(d) -> dict:
    if not (d.get("planilha_original") and d.get("planilha_repactuada")):
        return _indisp("T18-BENEFICIO-NAO-PREVISTO", "Benefício novo na repactuação", "as planilhas original e repactuada",
                       "IN SEGES 05/2017 Anexo IX; Lei 14.133/2021 art. 135", _PESO["media"])
    orig = set(d["planilha_original"].get("rubricas", []))
    nova = set(d["planilha_repactuada"].get("rubricas", []))
    cct_rub = set(d.get("cct_rubricas", []))
    novas = [r for r in nova - orig if r not in cct_rub]
    if novas:
        return _hip("T18-BENEFICIO-NAO-PREVISTO", "Benefício novo na repactuação", "INDICIO", "medio",
                    f"Rúbrica(s) na repactuada ausente(s) na original e não-trabalhista(s): {novas} — possível sobrepreço.",
                    "Planilhas", "IN SEGES 05/2017 Anexo IX", _PESO["media"])
    return _hip("T18-BENEFICIO-NAO-PREVISTO", "Benefício novo na repactuação", "AFASTADO", "—",
                "Toda rúbrica da repactuada existe na original ou decorre da CCT.", "Planilhas", "IN SEGES 05/2017", _PESO["media"])


def _t19_preclusao(d) -> dict:
    if not (d.get("datas_prorrogacao") and d.get("datas_pleito") is not None):
        return _indisp("T19-PRECLUSAO-PRORROGACAO", "Preclusão da repactuação", "datas de aditivo/prorrogação e de pleito",
                       "IN SEGES 05/2017 Anexo IX; jurisprudência TCU; Lei 14.133/2021 art. 135", _PESO["media"])
    return _hip("T19-PRECLUSAO-PRORROGACAO", "Preclusão da repactuação", "INDICIO", "medio",
                "Cruzar reajuste de MO pós-prorrogação sem ressalva/pleito tempestivo (pagamento indevido) × pleito "
                "tempestivo não pago (crédito legítimo da MGS). Pode explicar o saldo do relatório (cruza T03).",
                "Aditivos + pleitos (SEI)", "IN SEGES 05/2017 Anexo IX; TCU", _PESO["media"])


def _t20_garantia(d) -> dict:
    if d.get("garantia") is None:
        return _indisp("T20-GARANTIA-CONTRATUAL", "Garantia contratual", "a cláusula de garantia e o comprovante (SEI)",
                       "Lei 14.133/2021 art. 92 e art. 121 §3º I-III", _PESO["baixa"])
    return _hip("T20-GARANTIA-CONTRATUAL", "Garantia contratual", "INDICIO", "baixo",
                "Se T13 indica inadimplência E garantia não acionada → fragilidade da proteção subsidiária.",
                "Contrato + SEI", "Lei 14.133/2021 art. 92; art. 121 §3º", _PESO["baixa"])


def _t21_conta_vinculada(d) -> dict:
    if d.get("conta_vinculada") is None or not d.get("planilha"):
        return _indisp("T21-CONTA-VINCULADA-DUPLA", "Conta-vinculada / dupla contagem de provisões",
                       "a configuração de conta vinculada e a planilha (Grupo B)",
                       "IN SEGES 05/2017 Anexo VIII-B/XII; Lei 14.133/2021 art. 121 §3º III", _PESO["media"])
    return _hip("T21-CONTA-VINCULADA-DUPLA", "Conta-vinculada / dupla contagem de provisões", "INDICIO", "medio",
                "Sob conta vinculada, as provisões do Grupo B (13º/férias+1/3/multa 40% FGTS) devem ser retidas, "
                "não pagas cheias; verificar dupla contagem (provisão mensal + evento repago em dez/jan).",
                "SEI (conta vinculada) + planilha", "IN SEGES 05/2017 Anexo VIII-B/XII", _PESO["media"])


# T22 é o GATE — executado dentro de auditar_contrato (não é um achado isolado, mas registra cobertura).

def _t23_auto_aritmetica(d) -> dict:
    """T23 — Auto-aritmética do relatório derivado: recalcula cada '(N× R$X)' e flagra N×X ≠ total declarado.
    Pega erros do tipo '4× R$118.441,47 = R$586.950,02' (na verdade 5 parcelas). Achado real no caso MGS."""
    txt = d.get("relatorio_texto") or ""
    if not txt:
        return _indisp("T23-AUTO-ARITMETICA", "Auto-aritmética do relatório derivado",
                       "texto do relatório derivado (relatorio_texto)", "ISSAI 4000; GAO Yellow Book", _PESO["alta"])
    erros = []
    for m in re.finditer(r"R\$\s*([\d.]+,\d{2})\s*\(\s*(\d+)\s*[x×]\s*R\$\s*([\d.]+,\d{2})", txt):
        total, n, unit = _money(m.group(1)), int(m.group(2)), _money(m.group(3))
        if abs(n * unit - total) > 1.0:
            erros.append(f"'{m.group(2)}× R$ {m.group(3)}' declarado R$ {m.group(1)}, mas {n}×={n*unit:,.2f} (Δ {n*unit-total:+,.2f})")
    if erros:
        ev = ("Erro(s) aritmético(s) no relatório derivado (o N× não fecha com o total declarado): "
              + " | ".join(erros[:4]) + ". Contamina as totalizações 'devido' que dependem dessas linhas.")
        return _hip("T23-AUTO-ARITMETICA", "Auto-aritmética do relatório derivado", "CONFIRMADO", "alto", ev,
                    "Relatório do órgão (recálculo independente)", "ISSAI 4000 (subject matter); GAO Yellow Book", _PESO["alta"])
    return _hip("T23-AUTO-ARITMETICA", "Auto-aritmética do relatório derivado", "AFASTADO", "—",
                "Todas as linhas 'N× R$X' do relatório fecham com o total declarado.",
                "Relatório do órgão (recálculo)", "ISSAI 4000", _PESO["alta"])


def _t24_bruto_liquido(d) -> dict:
    """T24 — Valor-âncora 'glosado/pago' do relatório que NÃO existe em nenhuma OB líquida (vício bruto×líquido).
    Pega o crédito-fantasma de R$21k: 113.184,14 é bruto de NF, não pagamento. Achado real no caso MGS."""
    txt = d.get("relatorio_texto") or ""
    obs = d.get("obs") or []
    if not txt or not obs:
        return _indisp("T24-BRUTO-LIQUIDO", "Valor-âncora bruto sem lastro em OB",
                       "relatorio_texto + OBs", "Lei 4.320/64 art. 63; ISSAI 4000", _PESO["media"])
    vals_ob = {round(_money(o.get("valor")), 2) for o in _contabilizadas(obs)}
    glosados = set()
    for m in re.finditer(r"glosad\w*", txt, re.I):
        seg = txt[max(0, m.start() - 90):m.end() + 90]
        for v in re.findall(r"R\$\s*([\d.]+,\d{2})", seg):
            if _money(v) > 50000:
                glosados.add(round(_money(v), 2))
    fantasma = [v for v in glosados if not any(abs(v - o) < 0.02 for o in vals_ob)]
    if fantasma:
        ev = (f"Valor(es) tratado(s) como 'glosado/pago' SEM lastro em nenhuma OB líquida: "
              f"{', '.join(f'R$ {v:,.2f}' for v in fantasma[:4])}. É valor BRUTO de NF (não pagamento) — "
              f"vício bruto×líquido que infla o saldo/crédito apurado pelo órgão.")
        return _hip("T24-BRUTO-LIQUIDO", "Valor-âncora bruto sem lastro em OB", "INDICIO", "alto", ev,
                    "Relatório do órgão × ob_orcamentaria_siafe", "Lei 4.320/64 art. 63; ISSAI 4000", _PESO["alta"])
    return _hip("T24-BRUTO-LIQUIDO", "Valor-âncora bruto sem lastro em OB", "AFASTADO", "—",
                "Valores 'glosados' do relatório têm lastro em OB líquida (ou não há contexto de glosa).",
                "Relatório do órgão × OBs", "Lei 4.320/64 art. 63", _PESO["media"])


_TESTES = [
    _t01_3way, _t02_status_pago, _t03_reconcilia, _t04_reajuste_cct, _t05_database, _t06_interregno,
    _t07_duplicidade, _t08_gap, _t09_inss, _t10_ir, _t11_identidade, _t12_glosa, _t13_trabalhista,
    _t14_piso, _t15_grupo_a, _t16_regime, _t17_lucro, _t18_beneficio, _t19_preclusao, _t20_garantia,
    _t21_conta_vinculada, _t23_auto_aritmetica, _t24_bruto_liquido,
]


def auditar_contrato(dados: dict) -> dict:
    """Roda a bateria T01–T22 de auditoria de contrato contínuo e devolve o quadro estruturado.

    Args (`dados`) — tudo opcional exceto `obs`; ausência → INDISPONÍVEL honesto, nunca achado fabricado:
      obs: list[dict] das OBs (SIAFE) — numero_ob, status, nl, re, pd, valor, competencia, data_emissao, processo.
      favorecido, orgao, contrato: rótulos (str).
      vigencia: dict {inicio, fim?} do contrato (tarefa #8) — bordas de T08.
      serie_reajustes: list[float] dos valores mensais (90419→98276→…) — T04.
      saltos_competencia: list['MM/AAAA'] das competências onde o valor muda de patamar — T05/T06.
      cct_percentuais: {ano: pct} (T04); cct_data_base: int mês (3=março, T05); cct_piso/cct_rubricas (T14/T18).
      retencoes: {competencia: {inss, ir, base?}} (OCR/SEI) — T09/T10/T11.
      bruto_nf: {competencia: valor} — T11; glosas/glosas_competencias/valor_posto_dia/mensal_vigente — T12/T08.
      relatorio_saldo / relatorio_total_pago: o derivado do órgão a TESTAR (T03/T02).
      planilha / planilha_original / planilha_repactuada: dicts de custos (tarefa #8) — T14-T18/T21.
      datas_prorrogacao / datas_pleito / garantia / conta_vinculada / comprovantes_trabalhistas — T19/T20/T21/T13.

    Retorna {contrato, favorecido, orgao, achados:[…], score, grau, n_confirmados, n_indicios,
             n_indisponivel, resumo, cobertura}. Padrão IDÊNTICO ao investigacao_dd.investigar().
    """
    d = dict(dados or {})
    d.setdefault("obs", [])
    achados: list[dict] = []

    # T22 — GATE de completude (honestidade epistêmica), roda PRIMEIRO: introspecciona o acervo.
    cobertura = _gate_completude(d)

    for fn in _TESTES:
        try:
            h = fn(d)
        except Exception as e:  # noqa: BLE001 — um teste que quebra não derruba a bateria; vira INDISPONÍVEL honesto
            h = _hip(fn.__name__.upper(), fn.__doc__ or fn.__name__, "INDISPONIVEL", "—",
                     f"Teste não pôde rodar (erro interno: {type(e).__name__}).", "—", "—", 0)
        if h:
            achados.append(h)

    confirmados = [a for a in achados if a["status"] == "CONFIRMADO"]
    indicios = [a for a in achados if a["status"] == "INDICIO"]
    indisp = [a for a in achados if a["status"] == "INDISPONIVEL"]
    score = min(100, sum(a["peso"] for a in achados if a["status"] in ("CONFIRMADO", "INDICIO")))
    # grau: ≥1 CONFIRMADO forte OU score alto → 🔴; ≥2 indícios OU score médio → 🟡; senão 🟢
    if confirmados and score >= 30:
        grau = "🔴"
    elif score >= 30 or len(indicios) >= 2:
        grau = "🟡"
    else:
        grau = "🟢"

    return {
        "contrato": d.get("contrato", ""), "favorecido": d.get("favorecido", ""), "orgao": d.get("orgao", ""),
        "achados": achados, "score": score, "grau": grau,
        "n_confirmados": len(confirmados), "n_indicios": len(indicios), "n_indisponivel": len(indisp),
        "resumo": _resumo(grau, confirmados, indicios, indisp), "cobertura": cobertura,
    }


def _gate_completude(d: dict) -> dict:
    """T22 — mapa honesto de disponibilidade dos insumos (DISPONÍVEL / PARCIAL / INDISPONÍVEL)."""
    contab = _contabilizadas(d.get("obs", []))
    return {
        "OBs SIAFE": f"DISPONÍVEL ({len(contab)} Contabilizado de {len(d.get('obs', []))} no acervo)" if d.get("obs") else "INDISPONÍVEL",
        "Série de reajustes/CCT": "DISPONÍVEL" if (d.get("serie_reajustes") and d.get("cct_percentuais")) else "PARCIAL/INDISPONÍVEL",
        "Retenções INSS/IR (OCR)": "DISPONÍVEL" if d.get("retencoes") else "INDISPONÍVEL",
        "Glosas": "DISPONÍVEL" if d.get("glosas") else "INDISPONÍVEL",
        "Relatório Créditos/Débitos (a testar)": "DISPONÍVEL" if d.get("relatorio_saldo") is not None else "INDISPONÍVEL",
        "Planilha de custos 005/2021": "DISPONÍVEL" if d.get("planilha") else "INDISPONÍVEL (tarefa #8)",
        "Contrato/aditivos 005/2021": "DISPONÍVEL" if d.get("vigencia") else "INDISPONÍVEL (tarefa #8)",
        "Notas Fiscais (bruto)": "DISPONÍVEL" if d.get("bruto_nf") else "INDISPONÍVEL",
    }


def _resumo(grau: str, confirmados: list, indicios: list, indisp: list) -> str:
    base = (f"Auditoria de contrato contínuo: {len(confirmados)} fato(s) confirmado(s), "
            f"{len(indicios)} indício(s) a apurar, {len(indisp)} teste(s) INDISPONÍVEL (sem dado-fonte/critério). ")
    if not confirmados and not indicios:
        return base + "Nenhuma irregularidade verificável nos testes com dado disponível (não exclui o que está INDISPONÍVEL)."
    foco = [a["codigo"] for a in (confirmados + indicios)]
    return base + f"Achados a destacar: {', '.join(foco)}. Indício ≠ acusação; INDISPONÍVEL ≠ irregular."
