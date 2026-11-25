# -*- coding: utf-8 -*-
"""Recorte de uma LENTE (config/lentes.yaml) para o painel — a visão `lente_<nome>` do E15 (O7.2, plano §3.6 e §8).

Uma visão por lente, materializada pelo E15 (compliance_agent/aplicacao/estagios/materializar.py) e lida pela rota
`/api/esteira/lente?lente=<nome>` (rotas/esteira.py). O painel NUNCA calcula isto em request: o seletor global de lente
mostra a visão pronta e, em cada aba, diz quais consultas foram recortadas pela lente e quais mostram o universo
inteiro (rota ainda sem recorte) — nunca um "filtrado" que não foi.

Conteúdo, por esfera (cada número com fonte e estado; INDISPONÍVEL ≠ 0):
  estado      OB do SIAFE (`ob_orcamentaria_siafe`) que casam com a lente (`lentes.casa`, a mesma régua da fila
              única): universo (todas as OB do recorte, qualquer status), pago (régua canônica `_ob_paga`), fora da
              soma (anulada, excluída, devolvida, complementar…), DETERMINÁVEL (OB paga com nº de processo legível —
              liga ao SEI) × INDETERMINADO (OB paga sem nº de processo ou com nº que não é SEI-RJ: não liga ao SEI,
              mostrado ao lado do valor),
              UGs, credores (CPF mascarado), achados dos detectores no recorte por status — `nao_avaliavel` visível —
              com o tier do registro, e o topo da fila única com os COMPONENTES da prioridade (ordem de exame, não
              probabilidade);
  prefeitura  contratos do ContasRio dos órgãos da lente: valor atualizado, empenhado, liquidado e pago SEPARADOS
              (empenho não é pagamento), contratos sem pago informado contados à parte;
  emendas     emendas dos recortes da lente: empenhado, liquidado e pago SEPARADOS (pago aqui é OB federal, SIAFI —
              não é SIAFE), por ano e por destino.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from compliance_agent.fluxo import lentes as L

RAIZ = Path(__file__).resolve().parents[2]
ENV_FONTE = "JFN_LENTES_FONTE"           # compliance.db (padrão data/compliance.db, só-leitura)
ENV_PCRJ = "JFN_LENTES_PCRJ"             # pcrj.db
ENV_ACHADOS = "JFN_LENTES_ACHADOS"       # achados.db
VERSAO = "lente.v1"
_OB_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"
TOPO = 15
ROTULO_ORDEM = ("ordem de exame da fila única (prioridade explicável, plano §3.7): NÃO é probabilidade de "
                "irregularidade nem nota de risco — cada componente está ao lado")


def _ro(caminho: Path | str) -> sqlite3.Connection:
    p = Path(caminho)
    if not p.exists():
        raise FileNotFoundError(f"fonte só-leitura ausente: {p}")
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def _caminho(env: str, padrao: str) -> Path:
    return Path(os.environ.get(env) or (RAIZ / "data" / padrao))


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="seconds")


def _tabela(con, nome: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,)).fetchone() is not None


def _r2(v) -> float:
    return round(float(v or 0.0), 2)


# ── estado: OB do SIAFE ─────────────────────────────────────────────────────────────────────────────────────────
def recorte_ob(fonte: sqlite3.Connection, lente: L.Lente) -> dict:
    """Uma varredura agrupada de `ob_orcamentaria_siafe`; cada grupo passa por `lentes.casa` (mesma régua da fila)."""
    from compliance_agent.dominio import processo_id as PI
    from compliance_agent.dominio.pagamento import ob_paga_sql
    from compliance_agent.governo_couto import doc_exibivel, mascarar_texto
    pago = ob_paga_sql(fonte)
    desde = f"CASE WHEN {_OB_ISO} >= '{lente.desde}' THEN 1 ELSE 0 END" if lente.desde else "0"
    tot = {"obs": 0, "valor_bruto": 0.0, "obs_pagas": 0, "valor_pago": 0.0, "com_proc_n": 0, "com_proc_v": 0.0,
           "sem_proc_n": 0, "sem_proc_v": 0.0, "ilegivel_n": 0, "ilegivel_v": 0.0}
    por_ug: dict[str, list] = {}
    por_cred: dict[str, list] = {}
    processos: set[str] = set()
    ultima = None
    for proc, ug, cred, nome, no_periodo, eh_pago, n, v, ult in fonte.execute(
            f"SELECT COALESCE(processo,''), ug_emitente, COALESCE(credor,''), MAX(nome_credor), {desde}, "
            f"CASE WHEN {pago} THEN 1 ELSE 0 END, COUNT(*), SUM(valor), MAX({_OB_ISO}) "
            # ob-qualquer-status: paga/não paga classificada por {pago} (ob_paga_sql) na própria linha; só eh_pago soma
            "FROM ob_orcamentaria_siafe GROUP BY 1, 2, 3, 5, 6"):
        chave = PI.chave_processo(proc) if proc else None
        data = (lente.desde if no_periodo else "0000-00-00") if lente.desde else None
        if not L.casa(lente, {str(ug or "")}, chave, {cred} if cred else (), data):
            continue
        v = float(v or 0.0)
        tot["obs"] += n
        tot["valor_bruto"] += v
        if not eh_pago:
            continue
        tot["obs_pagas"] += n
        tot["valor_pago"] += v
        if not proc:
            tot["sem_proc_n"] += n
            tot["sem_proc_v"] += v
        elif chave is None:
            tot["ilegivel_n"] += n
            tot["ilegivel_v"] += v
        else:
            tot["com_proc_n"] += n
            tot["com_proc_v"] += v
            processos.add(chave)
        u = por_ug.setdefault(str(ug or ""), [0, 0.0])
        u[0] += n
        u[1] += v
        c = por_cred.setdefault(cred, [nome or "", 0, 0.0])
        c[1] += n
        c[2] += v
        if ult and (ultima is None or ult > ultima):
            ultima = ult
    idx = _indice_ug()
    credores = []
    for doc, (nome, n, v) in sorted(por_cred.items(), key=lambda x: -x[1][2])[:TOPO]:
        tipo, exib = doc_exibivel(doc)
        credores.append({"tipo": tipo, "doc": exib, "nome": mascarar_texto(nome or ""), "n_obs": n, "pago": _r2(v)})
    pg = tot["valor_pago"]
    return {
        "fonte": "SIAFE-Rio 2 — ob_orcamentaria_siafe; pago = régua canônica _ob_paga (Contabilizada, sem devolvida "
                 "pelo banco, sem complementar, sem reemitida, com número)",
        "natureza": "pago", "estado": "VERIFICADO",
        "universo": {"n": tot["obs"], "obs": tot["obs"], "valor_bruto_todos_status": _r2(tot["valor_bruto"]),
                     "obs_pagas": tot["obs_pagas"], "valor_pago": _r2(pg),
                     "fora_da_soma": {"obs": tot["obs"] - tot["obs_pagas"],
                                      "valor": _r2(tot["valor_bruto"] - pg),
                                      "o_que_e": "OB anulada, excluída, não contabilizada, devolvida pelo banco, "
                                                 "complementar ou reemitida — não é pagamento"},
                     "credores": len(por_cred), "processos_legiveis": len(processos), "ultima_ob_paga": ultima},
        "determinavel": {"obs": tot["com_proc_n"], "valor": _r2(tot["com_proc_v"]),
                         "o_que_e": "OB paga com nº de processo legível — liga ao SEI-RJ"},
        "indeterminado": {"sem_processo": {"obs": tot["sem_proc_n"], "valor": _r2(tot["sem_proc_v"])},
                          "processo_nao_sei": {"obs": tot["ilegivel_n"], "valor": _r2(tot["ilegivel_v"]),
                                               "o_que_e": "o campo processo da OB não traz nº SEI-RJ reconhecível "
                                                          "(ex.: '123/2024', nº físico antigo)"},
                          "o_que_e": "OB paga que NÃO liga a processo: o pagamento é real, o vínculo com o SEI é "
                                     "INDISPONÍVEL (não é zero, não é regular nem irregular)"},
        "cobertura": {"fracao_do_pago_ligavel_ao_sei": round(tot["com_proc_v"] / pg, 4) if pg else None},
        "ugs": [{"ug": u, "sigla": idx.get(u), "n_obs": n, "pago": _r2(v)}
                for u, (n, v) in sorted(por_ug.items(), key=lambda x: -x[1][1])[:TOPO]],
        "credores_topo": credores,
    }


def _indice_ug() -> dict:
    try:
        return json.loads(Path(L.INDICE_UG).read_text(encoding="utf-8")).get("ugs") or {}
    except FileNotFoundError:
        return {}


def achados_no_recorte(con_ach: sqlite3.Connection, lente: L.Lente) -> dict:
    """Achados da geração 2 (achados.db, `achado_detector`: UG × processo) que caem na lente, por detector e status,
    com o tier do registro. `confirmado` é "a regra disparou" (INDÍCIO de triagem), não confirmação humana;
    `nao_avaliavel` é INDISPONÍVEL e fica visível; UG escrita em texto sem código conferível é contada à parte."""
    from compliance_agent.adaptadores.achados import regra_do_detector
    from compliance_agent.dominio import processo_id as PI
    from compliance_agent.qualidade import detectores as R
    if lente.desde or lente.regra_credor:
        return {"estado": "INDETERMINAVEL",
                "motivo": "achado_detector não grava a data do fato nem o credor — não há como recortar por esta "
                          "lente sem inventar"}
    if not _tabela(con_ach, "achado_detector"):
        return {"estado": "INDISPONIVEL", "motivo": "achados.db sem a tabela achado_detector"}
    siglas: dict[str, set[str]] = {}
    for ug, sig in _indice_ug().items():
        siglas.setdefault(str(sig).strip(), set()).add(str(ug))
    reg = R.carregar()
    por: dict[tuple, int] = {}
    ug_texto = 0
    for ug, det, proc, status, n in con_ach.execute(
            "SELECT ug, detector, processo, status, COUNT(*) FROM achado_detector GROUP BY 1, 2, 3, 4"):
        ug = str(ug or "")
        ugs = {ug} if ug.isdigit() else siglas.get(ug.split(" - ", 1)[0].strip(), set())
        if ug and not ug.isdigit() and not ugs:
            ug_texto += n
        if L.casa(lente, ugs, PI.chave_processo(proc or ""), (), None):
            por[(det, status)] = por.get((det, status), 0) + n
    dets: dict[str, dict] = {}
    for (det, status), n in por.items():
        rid = regra_do_detector(det)
        e = reg.get(rid) or {}
        t = R.campos_calculados(e) if e else {"tier": None, "tier_motivo": "fora do registro"}
        d = dets.setdefault(det, {"detector": det, "registro": rid, "tier": t["tier"], "tier_motivo": t["tier_motivo"],
                                  "confirmado": 0, "descartado": 0, "nao_avaliavel": 0})
        d[status if status in ("confirmado", "descartado", "nao_avaliavel") else "outro"] = (
            d.get(status if status in ("confirmado", "descartado", "nao_avaliavel") else "outro", 0) + n)
    lista = sorted(dets.values(), key=lambda x: -(x["confirmado"] + x["nao_avaliavel"]))
    return {"estado": "VERIFICADO", "fonte": "achados.db — achado_detector (detectores da geração 2, por UG)",
            "totais": {k: sum(x.get(k, 0) for x in lista) for k in ("confirmado", "descartado", "nao_avaliavel")},
            "leitura": "confirmado = a regra disparou (indício de triagem, não confirmação humana) · nao_avaliavel = "
                       "faltou dado para o detector responder (INDISPONÍVEL, nunca zero)",
            "base_ug_em_texto_nao_conferivel": {"achados": ug_texto,
                                                "o_que_e": "achados da BASE INTEIRA (não só da lente) com UG escrita "
                                                           "em texto cuja sigla não está no índice do SIAFE — podem "
                                                           "ser da lente e não são contados nela (INDISPONÍVEL)"},
            "detectores": lista}


def fila_topo(fonte: sqlite3.Connection, lentes_res: dict, nome: str, sinais: dict | None) -> list[dict]:
    """O topo da fila única com a lente (arvore.fila), cada item com os COMPONENTES da prioridade."""
    from compliance_agent.aplicacao.estagios import arvore as A
    sel = A.fila(fonte, lentes_res, nome, extras={}, sinais=sinais)
    out = []
    for it, e in sel[:TOPO]:
        s = e["sinais"]
        out.append({"processo": it.processo, "ob_paga": _r2(it.ob_paga), "posicao_inteiro": e["inteiro"],
                    "componentes": {"escalar_valor": e["escalar_valor"], "bonus_lente": e["bonus_lente"],
                                    "direta_grande": e["direta_grande"], "couto": s["couto"],
                                    **{k: s[k] for k in ("manual", "legivel", "contratacao_direta", "lacuna_provada",
                                                         "osint", "folha")}},
                    "lente_motivo": e["lente_motivo"].get(nome), "fontes": e["fontes"]})
    return out


# ── prefeitura: ContasRio ───────────────────────────────────────────────────────────────────────────────────────
def recorte_pcrj(con: sqlite3.Connection, lente: L.Lente) -> dict:
    from compliance_agent.governo_couto import doc_exibivel, mascarar_texto
    cods = set(lente.orgaos_pcrj)
    t = {"n": 0, "valor_atualizado": 0.0, "empenhado": 0.0, "liquidado": 0.0, "pago": 0.0, "sem_pago": 0}
    por_org: dict[str, list] = {}
    por_ug: dict[str, list] = {}
    por_fav: dict[str, list] = {}
    ult = None
    for orgao, ug, doc, nome, va, emp, liq, pg, col in con.execute(
            "SELECT orgao, ug, favorecido_doc, favorecido_nome, valor_atualizado, total_empenhado, total_liquidado, "
            "total_pago, coletado_em FROM contasrio_contrato"):
        if str(orgao or "").partition(" - ")[0].strip() not in cods:
            continue
        t["n"] += 1
        for k, v in (("valor_atualizado", va), ("empenhado", emp), ("liquidado", liq)):
            t[k] += float(v or 0.0)
        if pg is None:
            t["sem_pago"] += 1
        else:
            t["pago"] += float(pg)
        o = por_org.setdefault(orgao, [0, 0.0])
        o[0] += 1
        o[1] += float(pg or 0.0)
        u = por_ug.setdefault(ug or "", [0, 0.0])
        u[0] += 1
        u[1] += float(pg or 0.0)
        f = por_fav.setdefault(str(doc or ""), [nome or "", 0, 0.0])
        f[1] += 1
        f[2] += float(pg or 0.0)
        ult = max(ult or "", str(col or "")) or None
    fav = []
    for doc, (nome, n, v) in sorted(por_fav.items(), key=lambda x: -x[1][2])[:TOPO]:
        tipo, exib = doc_exibivel(doc)
        fav.append({"tipo": tipo, "doc": exib, "nome": mascarar_texto(nome), "contratos": n, "pago": _r2(v)})
    return {"fonte": "ContasRio (Prefeitura do Rio) — contasrio_contrato no pcrj.db; pago = total pago do contrato "
                     "no ContasRio (empenho e liquidação separados — não são pagamento)",
            "natureza": "pago", "estado": "VERIFICADO", "coletado_em": ult,
            "universo": {"n": t["n"], "contratos": t["n"], "valor_atualizado": _r2(t["valor_atualizado"]),
                         "empenhado": _r2(t["empenhado"]), "liquidado": _r2(t["liquidado"]), "pago": _r2(t["pago"])},
            "indeterminado": {"contratos_sem_pago_informado": t["sem_pago"],
                              "o_que_e": "contrato sem total pago no ContasRio: INDISPONÍVEL, não R$ 0,00"},
            "orgaos": [{"orgao": k, "contratos": n, "pago": _r2(v)} for k, (n, v) in
                       sorted(por_org.items(), key=lambda x: -x[1][1])],
            "ugs": [{"ug": k, "contratos": n, "pago": _r2(v)} for k, (n, v) in
                    sorted(por_ug.items(), key=lambda x: -x[1][1])[:TOPO]],
            "favorecidos_topo": fav}


# ── emendas ─────────────────────────────────────────────────────────────────────────────────────────────────────
def recorte_emendas(con: sqlite3.Connection, lente: L.Lente) -> dict:
    marcas = ",".join("?" * len(lente.emendas_recortes))
    args = list(lente.emendas_recortes)
    n, emp, liq, pg = con.execute(f"SELECT COUNT(*), SUM(empenhado), SUM(liquidado), SUM(pago) FROM emendas "
                                  f"WHERE recorte IN ({marcas})", args).fetchone()
    anos = [{"ano": a, "n": k, "empenhado": _r2(e), "liquidado": _r2(li), "pago": _r2(p)} for a, k, e, li, p in
            con.execute(f"SELECT ano, COUNT(*), SUM(empenhado), SUM(liquidado), SUM(pago) FROM emendas WHERE recorte "
                        f"IN ({marcas}) GROUP BY 1 ORDER BY 1", args)]
    dest = [{"localidade": loc, "n": k, "pago": _r2(p)} for loc, k, p in
            con.execute(f"SELECT localidade_gasto, COUNT(*), SUM(pago) FROM emendas WHERE recorte IN ({marcas}) "
                        f"GROUP BY 1 ORDER BY 3 DESC LIMIT {TOPO}", args)]
    fora = con.execute(f"SELECT COUNT(*) FROM emendas WHERE recorte NOT IN ({marcas}) OR recorte IS NULL",
                       args).fetchone()[0]
    return {"fonte": "Portal da Transparência (CGU) — tabela emendas; pago aqui é OB FEDERAL (SIAFI), não SIAFE",
            "natureza": "pago", "estado": "VERIFICADO",
            "universo": {"n": n, "emendas": n, "empenhado": _r2(emp), "liquidado": _r2(liq), "pago": _r2(pg)},
            "fora_da_lente": {"emendas": fora, "o_que_e": "recortes fora da lente (autor do RJ sem destino no RJ)"},
            "por_ano": anos, "destinos_topo": dest}


# ── montagem ────────────────────────────────────────────────────────────────────────────────────────────────────
def _filtro_legivel(l: L.Lente) -> list[str]:
    f = []
    if l.ugs:
        f.append("UG " + ", ".join(sorted(l.ugs)))
    if l.orgao_sei:
        f.append("órgão SEI (prefixo derivado do SIAFE) " + ", ".join(sorted(l.orgao_sei)))
    if l.regra_processo:
        f.append("processos de contrato de obra (derivados do TCE-RJ)")
    if l.regra_credor:
        f.append("credores com sócio em benefício (derivados)")
    if l.desde:
        f.append(f"fato a partir de {l.desde} ({l.desde_ref})")
    if l.orgaos_pcrj:
        f.append("órgãos da Prefeitura " + ", ".join(f"{c} {n}" for c, n in l.conferir_pcrj))
    if l.emendas_recortes:
        f.append("emendas com recorte " + ", ".join(l.emendas_recortes))
    return f


def calcular(nome: str, *, fonte: sqlite3.Connection | None = None, fonte_pcrj: sqlite3.Connection | None = None,
             achados: sqlite3.Connection | None = None, sinais: dict | None = None,
             lentes_cfg: dict | None = None) -> dict:
    """O corpo da visão `lente_<nome>`. Fontes omitidas são abertas só-leitura nos caminhos padrão (ou nos `JFN_LENTES_*`)."""
    t0 = time.monotonic()
    cfg = lentes_cfg if lentes_cfg is not None else L.carregar()
    if nome not in cfg:
        raise KeyError(nome)
    lente = cfg[nome]
    fechar = []
    if fonte is None and lente.esfera in ("estado", "emendas"):
        fonte = _ro(_caminho(ENV_FONTE, "compliance.db"))
        fechar.append(fonte)
    if fonte_pcrj is None and lente.esfera == "prefeitura":
        fonte_pcrj = _ro(_caminho(ENV_PCRJ, "pcrj.db"))
        fechar.append(fonte_pcrj)
    try:
        res, medidas = L.resolver({nome: lente}, fonte, externas=bool(lente.regra_credor), fonte_pcrj=fonte_pcrj)
        lente = res[nome]
        corpo = {"ok": True, "versao": VERSAO, "lente": nome, "descricao": lente.descricao, "esfera": lente.esfera,
                 "filtro": _filtro_legivel(lente), "derivacao": medidas.get(nome, {}), "paridade": lente.paridade,
                 "prioridade": lente.prioridade, "cota_esforco": lente.cota_esforco, "cota_ref": lente.cota_ref,
                 "eixos_extra": list(lente.eixos_extra), "produto": lente.produto}
        if lente.esfera == "estado":
            corpo.update(recorte_ob(fonte, lente))
            if achados is None and _caminho(ENV_ACHADOS, "achados.db").exists():
                achados = _ro(_caminho(ENV_ACHADOS, "achados.db"))
                fechar.append(achados)
            corpo["achados"] = (achados_no_recorte(achados, lente) if achados is not None else
                                {"estado": "INDISPONIVEL", "motivo": "achados.db ausente"})
            if lente.desde and not lente.alcance():
                corpo["fila"] = {"estado": "NAO_SE_APLICA",
                                 "motivo": "a cota Couto já intercala o período em TODA a fila (config/foco.yaml); "
                                           "a lente não monta fila própria"}
            else:
                corpo["fila"] = {"rotulo": ROTULO_ORDEM, "itens": fila_topo(fonte, res, nome, sinais)}
        elif lente.esfera == "prefeitura":
            corpo.update(recorte_pcrj(fonte_pcrj, lente))
        else:
            corpo.update(recorte_emendas(fonte, lente))
        corpo["segundos"] = round(time.monotonic() - t0, 2)
        return corpo
    finally:
        for c in fechar:
            c.close()


def resposta(lente: str):
    """A função 'legado' que o E15 chama para materializar `lente_<nome>` (devolve Response, como as rotas)."""
    from starlette.responses import JSONResponse
    try:
        corpo = calcular(lente)
    except KeyError:
        return JSONResponse({"ok": False, "erro": f"lente desconhecida: {lente}"}, status_code=404)
    return JSONResponse(corpo, headers={"X-JFN-Lente": lente})


if __name__ == "__main__":   # python -m compliance_agent.aplicacao.lentes_resumo <lente>  (diagnóstico, só leitura)
    print(json.dumps(calcular(sys.argv[1]), ensure_ascii=False, indent=1)[:20000])
