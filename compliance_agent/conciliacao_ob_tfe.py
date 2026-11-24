# -*- coding: utf-8 -*-
"""Conciliação OB do SIAFE × espelho TFE — por exercício e UG. **OB do SIAFE é a fonte; TFE é espelho e pode ter erro.**

Pedido do dono (24/11/2026): "corrige o painel usando o SIAFE e as OBs. Quero o que tiver de divergência com o TFE
também, mas OBs são o principal; TFE pode ter erro." O pago do SIAFE era 3,0–3,9× o do espelho no mesmo ano e
ninguém tinha conciliado. Este módulo mede, não corrige: nada do que sai daqui vira "pago" — pago é sempre a OB paga
do SIAFE (`cruzamentos_intel._ob_paga`, régua única).

COMO CASA. 1º pelo número da OB + UG emitente (o mesmo formato `AAAAOBnnnnn` dos dois lados; a PK do SIAFE é
número+UG+exercício e o exercício é o do número). O que não casa pelo número tenta credor + valor (±R$ 0,005) + data
de emissão na mesma UG — o TFE mascara CPF, então esse 2º casamento só alcança CNPJ.

COMO EXPLICA (classes; uma por OB, na ordem abaixo):
  lado TFE (OB que o espelho lista):
    casada_numero            — o SIAFE tem a mesma OB, paga
    complementar             — o SIAFE tem, como 'Pagamento Complementar' (não vai ao banco; contá-la é dobro)
    devolvida                — o SIAFE tem, 'Erro no Pagamento' (o banco devolveu)
    reemitida                — o SIAFE tem, e ela foi reemitida e paga por outra (tabela `ob_reemitida`)
    nao_contabilizada        — o SIAFE tem, mas não 'Contabilizado' (cancelada/anulada/em processamento)
    casada_credor_valor_data — número diverge, mas credor+valor+data+UG batem com OB paga do SIAFE
    cobertura_parcial_siafe  — o par (UG, ano) está PARCIAL/INDISPONÍVEL na nossa coleta do SIAFE (régua de
                               `reporting.cobertura_siafe`): a ausência é nossa, não do Estado
    ausente_no_siafe         — o par está coberto e o SIAFE não tem a OB: divergência sem explicação
  lado SIAFE (OB paga):
    casada_numero / casada_credor_valor_data — como acima
    fora_do_universo_tfe     — credor não é CNPJ/CPF (folha, previdência, encargos, repasse entre UGs): o espelho
                               (fornecedor_ob) não publica esse universo
    tfe_defasado             — emitida depois do último dia que o espelho publicou
    ausente_no_tfe           — o espelho deveria ter e não tem
  linha alheia: linha de `ordens_bancarias` sem número `AAAAOB*` ou sem data ISO (página de outra tabela salva como
  OB na reconstrução de 12/08/2026) — contada à parte, nunca somada.

RECORTE: exercícios de 2021 em diante (o período que o painel publica do SIAFE). Custo: uma varredura de cada tabela
com consulta por índice por linha (~minutos com a VM em carga) — por isso a rota guarda o resultado em cache.

CLI: python -m compliance_agent.conciliacao_ob_tfe [--ano 2025]
"""
from __future__ import annotations

import heapq
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from compliance_agent.cruzamentos_intel import _ob_paga
from compliance_agent.reporting.cobertura_siafe import ROTULO_DO_ESTADO, estado_por_contagem
from compliance_agent.reporting.intel_base import SQL_CREDOR_TERCEIRO_SIAFE

_REPO = Path(__file__).resolve().parent.parent
ANO_INICIAL = 2021
ROTULO = "OB do SIAFE é a fonte; TFE é espelho e pode ter erro"
TOL = 0.005
N_AMOSTRA = 15

CLASSES_TFE = ("casada_numero", "complementar", "devolvida", "reemitida", "nao_contabilizada",
               "casada_credor_valor_data", "cobertura_parcial_siafe", "ausente_no_siafe")
CLASSES_SIAFE = ("casada_numero", "casada_credor_valor_data", "fora_do_universo_tfe", "tfe_defasado",
                 "ausente_no_tfe")
EXPLICACAO = {
    "complementar": "Pagamento Complementar no SIAFE — não vai ao banco; somar seria dobro",
    "devolvida": "SIAFE: 'Erro no Pagamento' — o banco devolveu",
    "reemitida": "SIAFE: reemitida e paga por outra OB (ob_reemitida)",
    "nao_contabilizada": "SIAFE: não Contabilizada (cancelada/anulada/em processamento)",
    "casada_credor_valor_data": "mesmo credor, valor, data e UG — número da OB diverge entre as fontes",
    "cobertura_parcial_siafe": "par (UG, ano) PARCIAL/INDISPONÍVEL na coleta do SIAFE da casa — lacuna nossa",
    "ausente_no_siafe": "par coberto e o SIAFE não tem a OB — divergência sem explicação (conferir no SIAFE)",
    "fora_do_universo_tfe": "credor não é CNPJ/CPF (folha, previdência, repasse entre UGs) — o espelho não publica",
    "tfe_defasado": "emitida depois do último dia publicado pelo espelho",
    "ausente_no_tfe": "o espelho deveria listar e não lista — erro/omissão do espelho",
}
_DMY_DE_ISO = "substr(o.data_emissao,9,2)||'/'||substr(o.data_emissao,6,2)||'/'||substr(o.data_emissao,1,4)"
_ISO_S = "substr(s.data_emissao,7,4)||'-'||substr(s.data_emissao,4,2)||'-'||substr(s.data_emissao,1,2)"


def _db(db: str | Path | None) -> Path:
    return Path(db or os.environ.get("JFN_DB") or _REPO / "data" / "compliance.db")


def _vazio_par() -> dict[str, Any]:
    return {"siafe_n": 0, "siafe_valor": 0.0, "tfe_n": 0, "tfe_valor": 0.0, "siafe_linhas": 0, "tfe_ausentes": 0,
            "tfe": {c: [0, 0.0] for c in CLASSES_TFE}, "siafe": {c: [0, 0.0] for c in CLASSES_SIAFE},
            "casadas_valor_diverge": [0, 0.0]}


def _push(heap: list, n: int, item: tuple) -> None:
    if len(heap) < n:
        heapq.heappush(heap, item)
    elif item[0] > heap[0][0]:
        heapq.heapreplace(heap, item)


def medir(db: str | Path | None = None, *, ano_inicial: int = ANO_INICIAL, anos: list[int] | None = None,
          amostra: int = N_AMOSTRA) -> dict[str, Any]:
    """Conciliação inteira. Devolve `por_ano`, `por_ug` (pares com maior divergência), amostras das maiores OB só num
    lado e as casadas com valor diferente. INDISPONÍVEL ≠ 0: sem uma das tabelas, `ok=False` e o motivo."""
    caminho = _db(db)
    if not caminho.exists():
        return {"ok": False, "indisponivel": True, "motivo": "compliance.db ausente", "rotulo": ROTULO}
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=60)
    try:
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"ob_orcamentaria_siafe", "ordens_bancarias"} <= tabelas:
            return {"ok": False, "indisponivel": True, "rotulo": ROTULO,
                    "motivo": "falta ob_orcamentaria_siafe ou ordens_bancarias no banco"}
        paga_s = _ob_paga(con, "s")
        paga_s2 = _ob_paga(con, "s2")
        tem_reem = "ob_reemitida" in tabelas
        filtro_ano_t = "CAST(substr(o.data_emissao,1,4) AS INTEGER) >= ?"
        filtro_ano_s = "CAST(substr(s.data_emissao,7,4) AS INTEGER) >= ?"
        p_ano: list[Any] = [ano_inicial]
        if anos:
            q = ",".join("?" * len(anos))
            filtro_ano_t += f" AND CAST(substr(o.data_emissao,1,4) AS INTEGER) IN ({q})"
            filtro_ano_s += f" AND CAST(substr(s.data_emissao,7,4) AS INTEGER) IN ({q})"
            p_ano += [int(a) for a in anos]

        tfe_ultimo = con.execute("SELECT MAX(data_emissao) FROM ordens_bancarias "
                                 "WHERE numero_ob GLOB '[0-9][0-9][0-9][0-9]OB*'").fetchone()[0]
        tfe_ultimo = str(tfe_ultimo)[:10] if tfe_ultimo else None
        alheias_n, alheias_v = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN typeof(valor) IN ('real','integer') AND abs(valor) < 1e12 "
            "THEN valor END),0) FROM ordens_bancarias WHERE NOT (COALESCE(numero_ob,'') GLOB '[0-9][0-9][0-9][0-9]OB*' "
            "AND COALESCE(data_emissao,'') GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*')").fetchone()

        pares: dict[tuple[str, str], dict[str, Any]] = {}
        nomes_ug: dict[str, str] = {}
        so_tfe: list = []
        so_siafe: list = []
        diverge: list = []

        # ── lado TFE: cada OB do espelho contra o SIAFE ─────────────────────────────────────────────────────────
        reem = ("EXISTS (SELECT 1 FROM ob_reemitida r WHERE r.ob=s.numero_ob AND r.ug=s.ug_emitente)"
                if tem_reem else "0")
        sql_t = f"""
            SELECT substr(o.data_emissao,1,4), o.ug_codigo, o.ug_nome, o.numero_ob, o.data_emissao, o.valor,
                   o.favorecido_cpf, o.favorecido_nome,
                   s.numero_ob IS NOT NULL, CASE WHEN s.numero_ob IS NULL THEN 0 WHEN {paga_s} THEN 1 ELSE 0 END,
                   s.valor, s.status, s.status_envio, s.tipo_regularizacao, {reem},
                   -- ob-qualquer-status: confronto com o espelho; a régua de paga vem em {paga_s2}
                   CASE WHEN s.numero_ob IS NULL THEN EXISTS (SELECT 1 FROM ob_orcamentaria_siafe s2
                        WHERE s2.credor=o.favorecido_cpf AND s2.ug_emitente=o.ug_codigo
                        AND s2.data_emissao={_DMY_DE_ISO} AND abs(s2.valor-o.valor) < {TOL} AND {paga_s2})
                   ELSE 0 END
            FROM ordens_bancarias o
            LEFT JOIN ob_orcamentaria_siafe s ON s.numero_ob=o.numero_ob AND s.ug_emitente=o.ug_codigo
                 AND s.exercicio=CAST(substr(o.numero_ob,1,4) AS INTEGER)
            WHERE o.numero_ob GLOB '[0-9][0-9][0-9][0-9]OB*'
              AND o.data_emissao GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*' AND {filtro_ano_t}"""
        pendentes_cobertura: list[tuple] = []   # (par, valor, amostra) dos ausentes — classe decidida no fim
        for (ano, ug, ug_nome, num, data, v, doc, nome, tem, paga, sv, st, ste, treg, reemitida,
             casa2) in con.execute(sql_t, p_ano):
            ug = str(ug or "")
            v = float(v or 0)
            par = pares.setdefault((ano, ug), _vazio_par())
            if ug_nome and ug not in nomes_ug:
                nomes_ug[ug] = ug_nome
            par["tfe_n"] += 1
            par["tfe_valor"] += v
            if not tem:
                par["tfe_ausentes"] += 1
            if paga:
                c = "casada_numero"
                if abs(float(sv or 0) - v) > TOL:
                    par["casadas_valor_diverge"][0] += 1
                    par["casadas_valor_diverge"][1] += abs(float(sv or 0) - v)
                    _push(diverge, amostra, (abs(float(sv or 0) - v), num, ug, data, v, float(sv or 0), nome))
            elif tem:
                c = ("complementar" if (treg or "") == "Pagamento Complementar" else
                     "devolvida" if (ste or "") == "Erro no Pagamento" else
                     "reemitida" if reemitida else "nao_contabilizada")
            elif casa2:
                c = "casada_credor_valor_data"
            else:
                pendentes_cobertura.append(((ano, ug), v, (v, num, ug, data, doc, nome)))
                continue
            par["tfe"][c][0] += 1
            par["tfe"][c][1] += v
            if c not in ("casada_numero", "casada_credor_valor_data"):
                _push(so_tfe, amostra, (v, num, ug, data, doc, nome, c, st, ste))

        # ── lado SIAFE: cada OB (qualquer situação, para a régua de cobertura) contra o espelho ─────────────────
        # ob-qualquer-status: a classificação paga/não paga é feita por {paga_s} na própria linha
        sql_s = f"""
            SELECT substr(s.data_emissao,7,4), s.ug_emitente, s.numero_ob, {_ISO_S}, s.valor, s.credor,
                   s.nome_credor, {paga_s}, ({SQL_CREDOR_TERCEIRO_SIAFE.replace('credor', 's.credor')}),
                   CASE WHEN {paga_s} THEN EXISTS (SELECT 1 FROM ordens_bancarias o
                        WHERE o.numero_ob=s.numero_ob AND o.ug_codigo=s.ug_emitente) ELSE 0 END
            -- ob-qualquer-status (classificação paga/não paga por {paga_s} acima)
            FROM ob_orcamentaria_siafe s WHERE {filtro_ano_s}"""
        sql_casa2 = ("SELECT 1 FROM ordens_bancarias o WHERE o.favorecido_cpf=? AND o.data_emissao=? "
                     "AND o.ug_codigo=? AND abs(o.valor-?) < ? LIMIT 1")
        for ano, ug, num, iso, v, credor, nome, paga, terceiro, casa1 in con.execute(sql_s, p_ano):
            ug = str(ug or "")
            par = pares.setdefault((ano, ug), _vazio_par())
            par["siafe_linhas"] += 1
            if not paga:
                continue
            v = float(v or 0)
            par["siafe_n"] += 1
            par["siafe_valor"] += v
            if casa1:
                c = "casada_numero"
            elif not terceiro:
                c = "fora_do_universo_tfe"
            elif con.execute(sql_casa2, (credor, iso, ug, v, TOL)).fetchone():
                c = "casada_credor_valor_data"
            elif tfe_ultimo and iso > tfe_ultimo:
                c = "tfe_defasado"
            else:
                c = "ausente_no_tfe"
            par["siafe"][c][0] += 1
            par["siafe"][c][1] += v
            if c in ("ausente_no_tfe",):
                _push(so_siafe, amostra, (v, num, ug, iso, credor, nome, c))

        # ── cobertura por par (régua de cobertura_siafe) e classe final dos ausentes do lado TFE ───────────────
        rotulo_par: dict[tuple[str, str], str] = {}
        for k, par in pares.items():
            e = estado_por_contagem(par["tfe_n"], par["tfe_ausentes"], par["siafe_linhas"])
            par["cobertura"] = ROTULO_DO_ESTADO.get(e["estado"], "INDISPONÍVEL")
            par["pct_ausente_siafe"] = e.get("pct_ausente")
            rotulo_par[k] = par["cobertura"]
        for k, v, item in pendentes_cobertura:
            c = "ausente_no_siafe" if rotulo_par.get(k) == "VERIFICADO" else "cobertura_parcial_siafe"
            pares[k]["tfe"][c][0] += 1
            pares[k]["tfe"][c][1] += v
            _push(so_tfe, amostra, (*item, c, None, None))
    finally:
        con.close()
    return _montar(pares, nomes_ug, so_tfe, so_siafe, diverge, tfe_ultimo, (alheias_n, alheias_v), ano_inicial)


def _cls(d: dict[str, list]) -> dict[str, dict[str, Any]]:
    return {c: {"n": n, "valor": round(v, 2)} for c, (n, v) in d.items() if n}


def _montar(pares, nomes_ug, so_tfe, so_siafe, diverge, tfe_ultimo, alheias, ano_inicial) -> dict[str, Any]:
    por_ano: dict[str, dict[str, Any]] = {}
    for (ano, _ug), p in pares.items():
        a = por_ano.setdefault(ano, {**_vazio_par(), "pares": 0, "pares_parciais": 0, "pares_indisponiveis": 0})
        for k in ("siafe_n", "siafe_valor", "tfe_n", "tfe_valor"):
            a[k] += p[k]
        for lado in ("tfe", "siafe"):
            for c, (n, v) in p[lado].items():
                a[lado][c][0] += n
                a[lado][c][1] += v
        a["casadas_valor_diverge"][0] += p["casadas_valor_diverge"][0]
        a["casadas_valor_diverge"][1] += p["casadas_valor_diverge"][1]
        a["pares"] += 1
        a["pares_parciais"] += p["cobertura"] == "PARCIAL"
        a["pares_indisponiveis"] += p["cobertura"] == "INDISPONÍVEL"

    def _linha(ano, p, ug=None):
        out = {"ano": ano, "siafe_pago_n": p["siafe_n"], "siafe_pago_valor": round(p["siafe_valor"], 2),
               "tfe_n": p["tfe_n"], "tfe_valor": round(p["tfe_valor"], 2),
               "diferenca": round(p["siafe_valor"] - p["tfe_valor"], 2),
               "razao_siafe_tfe": round(p["siafe_valor"] / p["tfe_valor"], 2) if p["tfe_valor"] else None,
               "casadas_numero": p["tfe"]["casada_numero"][0],
               "casadas_credor_valor_data": p["siafe"]["casada_credor_valor_data"][0],
               "so_siafe_n": sum(n for c, (n, _v) in p["siafe"].items() if not c.startswith("casada")),
               "so_tfe_n": sum(n for c, (n, _v) in p["tfe"].items() if not c.startswith("casada")),
               "casadas_valor_diverge": {"n": p["casadas_valor_diverge"][0],
                                         "soma_abs": round(p["casadas_valor_diverge"][1], 2)},
               "classes_tfe": _cls(p["tfe"]), "classes_siafe": _cls(p["siafe"])}
        if ug is not None:
            out.update({"ug": ug, "ug_nome": nomes_ug.get(ug, ""), "cobertura_siafe": p["cobertura"],
                        "pct_ausente_siafe": p.get("pct_ausente_siafe")})
        else:
            out.update({"pares": p["pares"], "pares_parciais": p["pares_parciais"],
                        "pares_indisponiveis": p["pares_indisponiveis"]})
        return out

    linhas_ug = [_linha(a, p, ug) for (a, ug), p in pares.items()]
    linhas_ug.sort(key=lambda x: abs(x["diferenca"]), reverse=True)
    por_ug: list[dict[str, Any]] = []   # os 25 pares de maior |diferença| de CADA exercício
    for a in sorted(por_ano):
        por_ug += [x for x in linhas_ug if x["ano"] == a][:25]

    def _ex(lst, campos):
        return [dict(zip(campos, x)) | {"explicacao": EXPLICACAO.get(dict(zip(campos, x)).get("classe"), "")}
                for x in sorted(lst, reverse=True)]

    return {
        "ok": True, "rotulo": ROTULO,
        "recorte": (f"exercícios de {ano_inicial} em diante · SIAFE = OB paga (régua _ob_paga) · TFE = "
                    "ordens_bancarias com número AAAAOB* e data válida · casamento por nº da OB + UG, depois "
                    "credor + valor + data + UG"),
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "tfe_ultimo_dia": tfe_ultimo,
        "explicacao_classes": EXPLICACAO,
        "por_ano": [_linha(a, por_ano[a]) for a in sorted(por_ano)],
        "por_ug": por_ug, "por_ug_total": len(linhas_ug), "por_ug_criterio": "25 pares de maior |diferença| por exercício",
        "maiores_so_tfe": _ex(so_tfe, ("valor", "numero_ob", "ug", "data", "doc", "favorecido", "classe",
                                       "status_siafe", "status_envio_siafe")),
        "maiores_so_siafe": _ex(so_siafe, ("valor", "numero_ob", "ug", "data", "credor", "favorecido", "classe")),
        "maiores_casadas_valor_diverge": [dict(zip(("dif_abs", "numero_ob", "ug", "data", "valor_tfe",
                                                    "valor_siafe", "favorecido"), x)) for x in sorted(diverge,
                                                                                               reverse=True)],
        "linhas_alheias_tfe": {"n": alheias[0], "valor_bruto": round(float(alheias[1] or 0), 2),
                               "nota": "linhas de outra tabela dentro de ordens_bancarias — fora de toda soma"},
    }


def _main(argv: list[str]) -> int:
    anos = [int(argv[argv.index("--ano") + 1])] if "--ano" in argv else None
    r = medir(anos=anos)
    if not r.get("ok"):
        print(json.dumps(r, ensure_ascii=False))
        return 1
    print(r["rotulo"], "·", r["recorte"])
    print(f"{'ano':>4} {'SIAFE pago (R$)':>22} {'TFE (R$)':>22} {'razão':>6} {'casadas':>9} {'só SIAFE':>9} "
          f"{'só TFE':>8}")
    for a in r["por_ano"]:
        print(f"{a['ano']:>4} {a['siafe_pago_valor']:>22,.2f} {a['tfe_valor']:>22,.2f} "
              f"{a['razao_siafe_tfe'] or 0:>6} {a['casadas_numero']:>9,} {a['so_siafe_n']:>9,} {a['so_tfe_n']:>8,}")
    if "--json" in argv:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
