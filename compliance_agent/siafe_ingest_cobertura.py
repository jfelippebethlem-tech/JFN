"""siafe_ingest_cobertura — MEDE o que o JFN tem do SIAFE-Rio 2, por tabela × UG × exercício (só leitura).

POR QUE EXISTE (19/11/2026, pedido do dono: "podemos melhorar muito o ingest do que há no SIAFE"). Antes de
coletar mais, medir: quantas UGs/anos têm NE e NL completas, quanto das NL que as OBs pagas citam existe em
`nl_siafe`, há quanto tempo cada tabela não é lida, quais campos da OB vêm sempre vazios, quantas OBs pagas a
fornecedor estão sem processo, e — o defeito mais silencioso — quantas OBs têm o STATUS CONGELADO no dia da
coleta ('Enviado ao Banco' que depois foi devolvida e a base nunca soube).

Toda célula sai com estado: VERIFICADO (medido no banco), PENDENTE (coleta registrada como incompleta) ou
INDISPONÍVEL (tabela ausente / nada a medir). INDISPONÍVEL ≠ 0 — UG nunca lida não vira "zero NE".

Uso:
    PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_ingest_cobertura            # resumo + JSON
    PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_ingest_cobertura --json      # só o JSON
Grava `data/siafe_ingest_cobertura.json` (o que o painel/relatório lê; nunca recalcular à mão).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DB = _REPO / "data" / "compliance.db"
SAIDA = _REPO / "data" / "siafe_ingest_cobertura.json"
EXERCICIOS = (2024, 2025, 2026)          # SIAFE 2; o SIAFE 1 (2016–2023) saiu do ar
# o que a perícia considera NÃO FINAL: o status pode mudar depois da foto (siafe_status_ob.NAO_FINAIS)
INTERMEDIARIOS = ("Enviado ao Banco", "Aguardando Envio", "Aguardando Geração RE")
CAMPOS_OB = ("ug_pagadora", "tipo", "finalidade", "tipo_ob", "nl", "credor", "ug_liquidante", "competencia",
             "status_envio", "gd", "processo", "re", "pd", "tipo_regularizacao", "qtd_impressoes",
             "assinatura_digital", "vinculacao_pagamento")
# data_emissao é TEXTO DD/MM/AAAA (data-emissao-siafe-e-texto): ISO montado por substr
_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"
_SEI = "'SEI-[0-9][0-9][0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9]'"
_SEI_SEM_PREFIXO = "'[0-9][0-9][0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9]'"


def _tem(con, tabela: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,)).fetchone() is not None


def _pct(a, b) -> float | None:
    return round(100.0 * a / b, 2) if b else None


def medir_ob(con, exercicios=EXERCICIOS) -> dict:
    """Volume, frescor, campos sempre vazios e legibilidade do processo das OBs pagas a fornecedor (CNPJ)."""
    out = {}
    vaz = ", ".join(f"SUM(COALESCE({c},'')='')" for c in CAMPOS_OB)
    for ex in exercicios:
        # ob-qualquer-status: volume e campos vazios de TODA a coleta (metadado; não soma pago)
        r = con.execute(f"SELECT COUNT(*), COUNT(DISTINCT ug_emitente), MAX(coletado_em), {vaz} "
                        "FROM ob_orcamentaria_siafe WHERE exercicio=?", (ex,)).fetchone()
        n = r[0]
        if not n:
            out[ex] = {"estado": "INDISPONÍVEL", "motivo": "nenhuma OB coletada"}
            continue
        vazios = {c: _pct(v, n) for c, v in zip(CAMPOS_OB, r[3:])}
        proc = {k: (q, round(v or 0.0, 2)) for k, q, v in con.execute(
            # ob-qualquer-status: aqui o filtro é status='Contabilizado' (pago) + credor CNPJ — medição, não soma
            f"SELECT CASE WHEN COALESCE(processo,'') IN ('','-') THEN 'vazio' WHEN processo GLOB {_SEI} THEN 'sei' "
            f"WHEN processo GLOB {_SEI_SEM_PREFIXO} THEN 'sei_sem_prefixo' WHEN processo GLOB 'E-[0-9]*' "
            "THEN 'legado_E' ELSE 'outro' END, COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe "
            "WHERE exercicio=? AND status='Contabilizado' AND length(credor)=14 GROUP BY 1", (ex,))}
        tot_forn = sum(q for q, _ in proc.values())
        out[ex] = {"estado": "VERIFICADO", "n": n, "ugs": r[1], "ultima_coleta": r[2],
                   "campos_sempre_vazios": sorted(c for c, p in vazios.items() if p == 100.0),
                   "campos_vazios_pct": {c: p for c, p in vazios.items() if p},
                   "processo_fornecedor": {k: {"n": q, "valor": v, "pct": _pct(q, tot_forn)}
                                           for k, (q, v) in sorted(proc.items())}}
    return out


def _universo(con, ex: int) -> dict[str, float]:
    """UGs que pagaram a fornecedor (OB Contabilizada a CNPJ) no exercício → valor pago. É o universo de NE/NL."""
    return {u: v for u, v in con.execute(
        # ob-qualquer-status: universo de cobertura; status='Contabilizado' explícito, sem somar como 'pago'
        "SELECT ug_emitente, SUM(valor) FROM ob_orcamentaria_siafe WHERE exercicio=? AND status='Contabilizado' "
        "AND length(credor)=14 GROUP BY 1", (ex,))}


def medir_documentos(con, exercicios=EXERCICIOS) -> dict:
    """Por tipo (NE/NL/GD) e exercício: UGs completas × parciais × nunca lidas sobre o universo; para a NL, a
    fração das NL citadas pelas OBs pagas que existem (o controle positivo de `siafe_documento`)."""
    out: dict = {}
    cob = {}
    if _tem(con, "siafe_documento_cobertura"):
        for tipo, ug, ex, comp, n, em in con.execute(
                "SELECT tipo, ug_emitente, exercicio, completo, colhidas, em FROM siafe_documento_cobertura"):
            cob[(tipo, str(ug), int(ex))] = (int(comp), n, em)
    tabelas = {"NE": "ne_siafe", "NL": "nl_siafe", "GD": "gd_siafe"}
    for ex in exercicios:
        uni = _universo(con, ex)
        tot_val = sum(uni.values()) or 0.0
        for tipo, tab in tabelas.items():
            if not _tem(con, tab):
                out.setdefault(tipo, {})[ex] = {"estado": "INDISPONÍVEL", "motivo": f"tabela {tab} ausente"}
                continue
            linhas = dict(con.execute(f"SELECT ug_emitente, COUNT(*) FROM {tab} WHERE exercicio=? GROUP BY 1", (ex,)))
            comp = sorted(u for u in uni if cob.get((tipo, u, ex), (0,))[0] == 1)
            parc = sorted(u for u in uni if (tipo, u, ex) in cob and cob[(tipo, u, ex)][0] == 0)
            nunca = [u for u in uni if (tipo, u, ex) not in cob]
            out.setdefault(tipo, {})[ex] = {
                "estado": "VERIFICADO", "universo_ugs": len(uni), "completas": len(comp), "parciais": len(parc),
                "nunca_lidas": len(nunca), "pct_ugs_completas": _pct(len(comp), len(uni)),
                "pct_valor_pago_em_ugs_completas": _pct(sum(uni[u] for u in comp), tot_val),
                "linhas": sum(linhas.values()), "ugs_com_linhas": len(linhas),
                "ugs_completas": comp, "ugs_parciais": parc}
        if _tem(con, "nl_siafe"):
            c, a, vc, va = con.execute(
                "SELECT COUNT(DISTINCT o.nl||'|'||o.ug_emitente), COUNT(DISTINCT l.numero||'|'||l.ug_emitente), "
                "SUM(o.valor), SUM(CASE WHEN l.numero IS NOT NULL THEN o.valor END) "
                # ob-qualquer-status: cobertura da NL; status='Contabilizado' explícito
                "FROM ob_orcamentaria_siafe o LEFT JOIN nl_siafe l ON l.numero=o.nl AND l.ug_emitente=o.ug_emitente "
                "AND l.exercicio=o.exercicio WHERE o.exercicio=? AND o.status='Contabilizado' AND o.nl LIKE ?",
                (ex, f"{ex}NL%")).fetchone()
            out["NL"][ex]["nl_citadas_pela_ob"] = c
            out["NL"][ex]["nl_citadas_achadas"] = a
            out["NL"][ex]["pct_nl_citadas_achadas"] = _pct(a, c)
            out["NL"][ex]["pct_valor_ob_com_nl"] = _pct(va or 0.0, vc or 0.0)
        if _tem(con, "nl_siafe") and _tem(con, "ne_siafe"):
            c, a = con.execute(
                "SELECT COUNT(DISTINCT l.ne||'|'||l.ug_emitente), COUNT(DISTINCT e.numero||'|'||e.ug_emitente) "
                "FROM nl_siafe l LEFT JOIN ne_siafe e ON e.numero=l.ne AND e.ug_emitente=l.ug_emitente "
                "WHERE l.exercicio=? AND l.ne LIKE ?", (ex, f"{ex}NE%")).fetchone()
            out["NE"][ex]["ne_citadas_pela_nl"] = c
            out["NE"][ex]["pct_ne_citadas_achadas"] = _pct(a, c)
    return out


def medir_status(con, exercicios=EXERCICIOS, hoje: datetime | None = None) -> dict:
    """STATUS CONGELADO: OB Contabilizada em estado intermediário cuja foto nunca foi refeita. Separa as recentes
    (≤ 60 dias, ainda podem estar no banco) das velhas (> 60 dias: o status da base quase certamente envelheceu)
    e mede a 'foto precoce' — OB colhida até 7 dias depois de emitida e nunca relida."""
    hoje = hoje or datetime.now()
    h = hoje.strftime("%Y-%m-%d")
    inn = "(" + ",".join("?" * len(INTERMEDIARIOS)) + ")"
    out = {}
    for ex in exercicios:
        faixas = {f: {"n": n, "valor": round(v or 0.0, 2), "dias": d, "coletada_ate": c} for f, n, v, d, c in con.execute(
            # ob-qualquer-status: medição do status congelado (lê o intermediário de propósito; não soma pago)
            f"SELECT CASE WHEN julianday(?)-julianday({_ISO}) <= 60 THEN 'ate_60d' ELSE 'mais_60d' END, COUNT(*), "
            f"SUM(valor), COUNT(DISTINCT data_emissao), MAX(coletado_em) FROM ob_orcamentaria_siafe WHERE exercicio=? "
            f"AND status='Contabilizado' AND status_envio IN {inn} GROUP BY 1", (h, ex, *INTERMEDIARIOS))}
        precoce = con.execute(
            # ob-qualquer-status: idem — idade da foto, não soma de pago
            f"SELECT COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe WHERE exercicio=? AND status='Contabilizado' "
            f"AND status_envio IN {inn} AND julianday(substr(coletado_em,1,10))-julianday({_ISO}) <= 7 "
            f"AND julianday(?)-julianday({_ISO}) > 7", (ex, *INTERMEDIARIOS, h)).fetchone()
        nao_cont = con.execute(
            # ob-qualquer-status: 'Não contabilizado' pode virar Contabilizado/Anulado — medição
            "SELECT COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe WHERE exercicio=? AND status='Não contabilizado'",
            (ex,)).fetchone()
        envio_vazio = con.execute(
            # ob-qualquer-status: idem
            "SELECT COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe WHERE exercicio=? AND status='Contabilizado' "
            "AND COALESCE(status_envio,'')=''", (ex,)).fetchone()
        rel = (None, 0)
        if _tem(con, "ob_status_recoleta"):
            rel = con.execute("SELECT MAX(recoletado_em), COUNT(*) FROM ob_status_recoleta WHERE exercicio=?",
                              (ex,)).fetchone()
        out[ex] = {"estado": "VERIFICADO", "intermediarios": faixas,
                   "foto_precoce_nunca_relida": {"n": precoce[0], "valor": round(precoce[1] or 0.0, 2)},
                   "nao_contabilizado": {"n": nao_cont[0], "valor": round(nao_cont[1] or 0.0, 2)},
                   "contabilizado_envio_vazio": {"n": envio_vazio[0], "valor": round(envio_vazio[1] or 0.0, 2)},
                   "dias_relidos": rel[1], "ultima_releitura": rel[0]}
    return out


def medir(db=None, exercicios=EXERCICIOS, hoje: datetime | None = None) -> dict:
    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=120)
    try:
        if not _tem(con, "ob_orcamentaria_siafe"):
            return {"estado": "INDISPONÍVEL", "motivo": "ob_orcamentaria_siafe ausente"}
        return {"medido_em": time.strftime("%F %T"), "exercicios": list(exercicios),
                "ob": medir_ob(con, exercicios), "documentos": medir_documentos(con, exercicios),
                "status": medir_status(con, exercicios, hoje)}
    finally:
        con.close()


def _br(x, casas: int = 0) -> str:
    """Número no padrão brasileiro: milhar com ponto, decimal com vírgula."""
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def resumo(m: dict) -> str:
    """Texto curto (log, Telegram, relatório)."""
    if m.get("estado") == "INDISPONÍVEL":
        return f"SIAFE ingest: INDISPONÍVEL ({m.get('motivo')})"
    lin = [f"SIAFE ingest — medido em {m['medido_em']}"]
    for ex in m["exercicios"]:
        ob = m["ob"].get(ex, {})
        if ob.get("estado") != "VERIFICADO":
            lin.append(f"  {ex}: OB INDISPONÍVEL")
            continue
        pv = ob["processo_fornecedor"].get("vazio", {})
        lin.append(f"  {ex}: OB {_br(ob['n'])} em {ob['ugs']} UGs (última coleta {ob['ultima_coleta']}); "
                   f"pagas a fornecedor sem processo: {_br(pv.get('n', 0))} ({_br(pv.get('pct') or 0, 2)}%)")
        for tipo in ("NE", "NL", "GD"):
            d = m["documentos"].get(tipo, {}).get(ex, {})
            if d.get("estado") != "VERIFICADO":
                lin.append(f"    {tipo}: INDISPONÍVEL")
                continue
            extra = ""
            if tipo == "NL" and d.get("nl_citadas_pela_ob"):
                extra = f"; NL citadas pela OB achadas: {d['pct_nl_citadas_achadas']}%"
            lin.append(f"    {tipo}: {d['completas']}/{d['universo_ugs']} UGs completas "
                       f"({d['pct_valor_pago_em_ugs_completas'] or 0}% do valor), {d['parciais']} parciais, "
                       f"{d['nunca_lidas']} nunca lidas{extra}")
        st = m["status"][ex]
        for f, v in sorted(st["intermediarios"].items()):
            lin.append(f"    status congelado {f}: {_br(v['n'])} OB, R$ {_br(v['valor'], 2)} em {v['dias']} dias")
    return "\n".join(lin)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="imprime só o JSON")
    a = ap.parse_args()
    m = medir()
    SAIDA.write_text(json.dumps(m, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(m, ensure_ascii=False, default=str) if a.json else resumo(m))


if __name__ == "__main__":
    main()
