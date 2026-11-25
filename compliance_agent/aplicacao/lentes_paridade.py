# -*- coding: utf-8 -*-
"""PARIDADE de cada lente (config/lentes.yaml) contra o script/relatório específico que ela substitui (O7.2; plano
mestre v2 §3.6 "Paridade antes de apagar"; mapa ~/vault/refatoracao/mapa-scripts-estagios-20261124.md).

Cada função recebe as fontes só-leitura, roda a régua ANTIGA (a função/consulta do próprio script, importada quando
existe — porte sem reescrever) e a NOVA (a lente pela mesma `lentes.casa` da fila e do painel), e devolve
`{lente, antigo, novo, contido, diferencas}`: `contido` = o que o antigo selecionava está na lente; cada diferença
vem com a causa (falso positivo corrigido, regra errada, fora do escopo por decisão). tests/test_lentes_completas.py
roda estas funções sobre fixtures; a CLI roda sobre o snapshot da parada e imprime o relatório.

    python -m compliance_agent.aplicacao.lentes_paridade [--lente X] [--fonte ~/snapshot-20261124/compliance.db]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from compliance_agent.fluxo import lentes as L

RAIZ = Path(__file__).resolve().parents[2]
_OB_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"


def _siglas(indice: Path | None = None) -> dict[str, set[str]]:
    from compliance_agent.aplicacao.estagios.arvore import _siglas_ug
    return _siglas_ug(indice)


def _ugs_da_unidade(unidade: str | None, siglas: dict[str, set[str]]) -> set[str]:
    return siglas.get(str(unidade or "").split(" - ", 1)[0].strip(), set())


# ── bombeiros: tools/sei_bombeiros_sweep.py (fila de contratos FUNESBOM) ──────────────────────────────────────────
def bombeiros(lente: L.Lente, fila: list[dict], fonte: sqlite3.Connection, indice: Path | None = None) -> dict:
    """Os contratos que o sweep antigo drenava (fila sem a cascata, decisão do dono de 13/11) caem na lente?"""
    from compliance_agent.dominio import processo_id as PI
    from tools.sei_bombeiros_sweep import _cascata
    tipo = {x.get("sei"): x.get("tipo") for x in fila}
    alvo = [x for x in fila if not _cascata(x, tipo)]
    ugs_proc: dict[str, set[str]] = {}
    sig = _siglas(indice)
    for proc, uni in fonte.execute("SELECT processo, unidade FROM contratos_tcerj WHERE COALESCE(processo,'')<>''"):
        k = PI.chave_processo(proc)
        if k:
            ugs_proc.setdefault(k, set()).update(_ugs_da_unidade(uni, sig))
    fora, ilegivel, motivo = [], [], {}
    for x in alvo:
        k = PI.chave_processo(x.get("sei") or "")
        if not k:
            ilegivel.append(x.get("sei"))
            continue
        m = L.casa(lente, ugs_proc.get(k, set()), k)
        if m:
            motivo[m.split(":")[0]] = motivo.get(m.split(":")[0], 0) + 1
        else:
            fora.append(k)
    return {"lente": lente.nome, "antigo": {"fila": len(fila), "sem_cascata": len(alvo)},
            "novo": {"na_lente": len(alvo) - len(fora) - len(ilegivel), "por_motivo": motivo},
            "contido": not fora, "diferencas": {"fora_da_lente": sorted(fora)[:200], "n_fora": len(fora),
                                                "sei_ilegivel": ilegivel[:50], "n_sei_ilegivel": len(ilegivel)}}


# ── couto: compliance_agent/governo_couto._execucao ─────────────────────────────────────────────────────────────
def couto(lente: L.Lente, fonte: sqlite3.Connection) -> dict:
    from compliance_agent.aplicacao.lentes_resumo import recorte_ob
    from compliance_agent.governo_couto import _execucao
    antigo = _execucao(fonte, None)
    novo = recorte_ob(fonte, lente)["universo"]
    cols = {r[1] for r in fonte.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}
    base = (f"exercicio={int(lente.desde[:4])} AND {_OB_ISO} >= '{lente.desde}' AND status='Contabilizado' "
            "AND COALESCE(status_envio,'')<>'Erro no Pagamento' AND TRIM(COALESCE(numero_ob,''))<>''")
    # ob-qualquer-status: decompõe a diferença antigo × novo — complementar e reemitida são justamente o que _ob_paga exclui
    comp = (fonte.execute(f"SELECT COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe WHERE {base} AND "
                          "COALESCE(tipo_regularizacao,'')='Pagamento Complementar'").fetchone()
            if "tipo_regularizacao" in cols else (0, 0.0))
    tem_re = fonte.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ob_reemitida'").fetchone()
    # ob-qualquer-status: idem — 1ª OB reemitida, fora da soma de pago por definição
    reem = (fonte.execute(f"SELECT COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe o WHERE {base} AND "
                          "COALESCE(tipo_regularizacao,'')<>'Pagamento Complementar' AND EXISTS (SELECT 1 FROM "
                          "ob_reemitida r WHERE r.ob=o.numero_ob AND r.ug=o.ug_emitente)").fetchone()
            if tem_re else (0, 0.0))
    # ob-qualquer-status: contagem de cobertura (OB do período lançada em outro exercício), não soma
    fora_periodo = fonte.execute(f"SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE {_OB_ISO} >= ? AND exercicio<>?",
                                 (lente.desde, int(lente.desde[:4]))).fetchone()[0]
    dn = (antigo.get("n_obs") or 0) - novo["obs_pagas"]
    dv = round((antigo.get("pago") or 0.0) - novo["valor_pago"], 2)
    explicado_n = int(comp[0] or 0) + int(reem[0] or 0)
    explicado_v = round(float(comp[1] or 0.0) + float(reem[1] or 0.0), 2)
    return {"lente": lente.nome, "antigo": {"n_obs": antigo.get("n_obs"), "pago": antigo.get("pago")},
            "novo": {"n_obs": novo["obs_pagas"], "pago": novo["valor_pago"]},
            "contido": dn == explicado_n and abs(dv - explicado_v) < 0.01,
            "diferencas": {"n": dn, "valor": dv,
                           "pagamento_complementar": {"n": int(comp[0] or 0), "valor": round(float(comp[1] or 0), 2),
                                                      "causa": "não vai ao banco: a OB principal já paga (dobro)"},
                           "reemitida": {"n": int(reem[0] or 0), "valor": round(float(reem[1] or 0), 2),
                                         "causa": "a 1ª OB reemitida não é pagamento"},
                           "sem_explicacao": {"n": dn - explicado_n, "valor": round(dv - explicado_v, 2)},
                           "ob_do_periodo_em_outro_exercicio": fora_periodo}}


# ── mgs_iterj: tools/_arquivo/mgs_iterj_2021/relatorio_iterj_mgs_padrao.py ─────────────────────────────────────
_SCRIPT_MGS = RAIZ / "tools/_arquivo/mgs_iterj_2021/relatorio_iterj_mgs_padrao.py"


def _constante_do_script(caminho: Path, nome: str) -> str:
    """Valor literal de `nome = "..."` no script antigo (que roda no import e não pode ser importado): a paridade
    usa o MESMO alvo que a régua antiga usava, sem copiar o CNPJ para cá (PAD-12)."""
    import ast
    for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Assign) and any(isinstance(t, ast.Name) and t.id == nome for t in no.targets) \
                and isinstance(no.value, ast.Constant):
            return str(no.value.value)
    raise LookupError(f"{nome} não está em {caminho}")


MGS = _constante_do_script(_SCRIPT_MGS, "CNPJ")


def mgs_iterj(lente: L.Lente, fonte: sqlite3.Connection) -> dict:
    from compliance_agent.dominio import processo_id as PI
    from compliance_agent.dominio.pagamento import ob_paga_sql
    pago = ob_paga_sql(fonte)
    linhas = fonte.execute(f"SELECT ug_emitente, processo, CASE WHEN {pago} THEN 1 ELSE 0 END, valor FROM "
                           "ob_orcamentaria_siafe WHERE ug_emitente='133100' AND credor=?", (MGS,)).fetchall()
    fora = [i for i, (ug, proc, _p, _v) in enumerate(linhas)
            if not L.casa(lente, {str(ug)}, PI.chave_processo(proc or ""), {MGS})]
    pagas = [v for (_u, _pr, p, v) in linhas if p]
    return {"lente": lente.nome, "antigo": {"obs_iterj_mgs": len(linhas)},
            "novo": {"na_lente": len(linhas) - len(fora), "pagas": len(pagas), "valor_pago": round(sum(pagas), 2)},
            "contido": not fora, "diferencas": {"n_fora": len(fora), "nao_pagas_pela_regua": len(linhas) - len(pagas)}}


# ── fserj: tools/fserj_socio_agente.py (contratos do TCE-RJ com unidade FSERJ) ─────────────────────────────────
def fserj(lente: L.Lente, fonte: sqlite3.Connection, indice: Path | None = None) -> dict:
    from compliance_agent.dominio import processo_id as PI
    sig = _siglas(indice)
    n = 0
    procs, fora, sem_proc = set(), set(), 0
    for proc, uni in fonte.execute("SELECT processo, unidade FROM contratos_tcerj WHERE unidade LIKE 'FSERJ%'"):
        n += 1
        k = PI.chave_processo(proc or "")
        if not k:
            sem_proc += 1
            continue
        procs.add(k)
        if not L.casa(lente, _ugs_da_unidade(uni, sig), k):
            fora.add(k)
    return {"lente": lente.nome, "antigo": {"contratos": n, "processos_legiveis": len(procs)},
            "novo": {"na_lente": len(procs) - len(fora)}, "contido": not fora,
            "diferencas": {"n_fora": len(fora), "fora": sorted(fora)[:50], "contrato_sem_processo_legivel": sem_proc,
                           "tac_doerj": "o script antigo somava doerj_tac_sinal SEM filtro de órgão — fora por desenho"}}


# ── obras: tools/pericia_obras.py ───────────────────────────────────────────────────────────────────────────────
def obras(lente: L.Lente, fonte: sqlite3.Connection) -> dict:
    from compliance_agent.dominio import processo_id as PI
    from tools.pericia_obras import OBRA
    antigos = {PI.chave_processo(p or "") for (p,) in fonte.execute(
        f"SELECT processo FROM contratos_tcerj WHERE {OBRA} AND COALESCE(valor_contrato,0) > 0")} - {None}
    procs, med = L.derivar_contratos_obra(fonte)
    return {"lente": lente.nome, "antigo": {"contratos": med["contratos_criterio_antigo"], "processos": len(antigos)},
            "novo": {"contratos": med["contratos_obra"], "processos": len(procs)},
            "contido": procs <= antigos,       # a lente é SUBCONJUNTO do antigo: só tira falso positivo
            "diferencas": {"fora_do_criterio_novo": med["fora_do_criterio_novo"],
                           "entrou_novo": sorted(procs - antigos)[:20]}}


# ── beneficios: compliance_agent/pcrj/pericia_socios_beneficio.analisar ────────────────────────────────────────
def beneficios(lente: L.Lente) -> dict:
    from compliance_agent.pcrj.pericia_socios_beneficio import analisar
    d = analisar()
    antigos = {r["cnpj_raw"] for r in d["registros"] if len(r.get("cnpj_raw") or "") == 14}
    novos = lente.credores or frozenset()
    return {"lente": lente.nome, "antigo": {"registros": len(d["registros"]), "cnpjs": len(antigos),
                                            "empresas": d["n_empresas"]},
            "novo": {"cnpjs": len(novos)}, "contido": antigos <= novos,
            "diferencas": {"so_no_antigo": sorted(antigos - novos)[:20], "so_na_lente": sorted(novos - antigos)[:20],
                           "registro_sem_cnpj_14": len(d["registros"]) - sum(
                               1 for r in d["registros"] if len(r.get("cnpj_raw") or "") == 14)}}


# ── emendas: compliance_agent/emendas/pericia.py (tabela inteira) ───────────────────────────────────────────────
def emendas(lente: L.Lente, fonte: sqlite3.Connection) -> dict:
    por = {r: n for r, n in fonte.execute("SELECT COALESCE(recorte,'(nulo)'), COUNT(*) FROM emendas GROUP BY 1")}
    fora = {r: n for r, n in por.items() if r not in lente.emendas_recortes}
    uf = {u or "(sem UF)": n for u, n in fonte.execute(
        f"SELECT uf_destino, COUNT(*) FROM emendas WHERE COALESCE(recorte,'') NOT IN "
        f"({','.join('?' * len(lente.emendas_recortes))}) GROUP BY 1", lente.emendas_recortes)}
    return {"lente": lente.nome, "antigo": {"emendas": sum(por.values())},
            "novo": {"emendas": sum(n for r, n in por.items() if r in lente.emendas_recortes)},
            "contido": False,
            "diferencas": {"fora_por_recorte": fora, "fora_por_uf_destino": uf,
                           "causa": "autor do RJ sem destino no RJ: dinheiro federal fora do Estado (escopo só RJ, "
                                    "decisão do dono de 19/11/2026)"}}


# ── pcrj_saude: tools/pericia_ppp_souza_aguiar.py (caso único) ─────────────────────────────────────────────────
SOUZA_AGUIAR_UG = "180061"


def pcrj_saude(lente: L.Lente, fonte_pcrj: sqlite3.Connection) -> dict:
    cods = set(lente.orgaos_pcrj)
    n = fora = 0
    for orgao, _ug in fonte_pcrj.execute("SELECT orgao, ug FROM contasrio_contrato WHERE ug LIKE ?",
                                         (SOUZA_AGUIAR_UG + " %",)):
        n += 1
        fora += str(orgao or "").partition(" - ")[0].strip() not in cods
    ppp = fonte_pcrj.execute("SELECT orgao_gestor FROM pcrj_ppp WHERE slug='complexo-hospitalar-souza-aguiar'"
                             ).fetchone() if fonte_pcrj.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pcrj_ppp'").fetchone() else None
    return {"lente": lente.nome, "antigo": {"contratos_hospital_souza_aguiar": n},
            "novo": {"na_lente": n - fora}, "contido": fora == 0 and n > 0,
            "diferencas": {"n_fora": fora, "ppp_orgao_gestor": ppp[0] if ppp else None,
                           "causa": "a PPP é conduzida pela CCPAR (não é órgão de saúde no cadastro): entra pelo "
                                    "dossiê do caso (E16), não pela lente"}}


def _abrir(p: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(p).expanduser()}?mode=ro&immutable=1", uri=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="paridade das lentes (O7.2)")
    ap.add_argument("--lente", action="append")
    ap.add_argument("--fonte", default=str(Path.home() / "snapshot-20261124" / "compliance.db"))
    ap.add_argument("--pcrj", default=str(RAIZ / "data" / "pcrj.db"))
    ap.add_argument("--fila-bombeiros", default=str(RAIZ / "data" / "bombeiros_sei_fila.json"))
    a = ap.parse_args(argv)
    fonte, pcrj = _abrir(a.fonte), _abrir(a.pcrj)
    nomes = a.lente or ["bombeiros", "couto", "mgs_iterj", "fserj", "obras", "emendas", "pcrj_saude", "beneficios"]
    cfg = L.carregar()
    res, _ = L.resolver({n: cfg[n] for n in nomes}, fonte, externas="beneficios" in nomes, fonte_pcrj=pcrj)
    out = []
    for n in nomes:
        if n == "bombeiros":
            r = bombeiros(res[n], json.loads(Path(a.fila_bombeiros).read_text(encoding="utf-8")), fonte)
        elif n in ("couto", "mgs_iterj", "fserj", "obras", "emendas"):
            r = globals()[n](res[n], fonte)
        elif n == "pcrj_saude":
            r = pcrj_saude(res[n], pcrj)
        else:
            r = beneficios(res[n])
        out.append(r)
        print(json.dumps(r, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
