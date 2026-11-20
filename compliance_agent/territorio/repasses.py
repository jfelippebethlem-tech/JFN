# -*- coding: utf-8 -*-
"""(A2) REPASSES E TRANSFERÊNCIAS do Estado a entes MUNICIPAIS do RJ = investimento NA CIDADE.

Regra do dono (20/11/2026): "qualquer repasse ou transferência do governo do estado pra uma cidade, por exemplo
saúde, a gente considera investimento na cidade". Componente SEPARADO dos contratos: não é valor contratado, é
dinheiro que SAIU (OB paga).

  · O QUE ENTRA: OB do SIAFE PAGA — régua única `cruzamentos_intel._ob_paga` (Contabilizada, sem a devolvida pelo
    banco, sem a complementar, sem a reemitida, com número) — de `ob_orcamentaria_siafe` cujo CREDOR é ente
    municipal do RJ pela NATUREZA JURÍDICA da Receita (`receita_estab.db.empresas.natureza_cod`; tabela oficial em
    `esfera_orgao.NATUREZA_PUBLICA`, conferida no arquivo Naturezas.zip): órgão do Executivo municipal (1031),
    autarquia (1120), fundação pública (1155/1279), órgão autônomo (1180), município (1244) e fundo público municipal
    (1309/1333 — Fundo Municipal de Saúde, de Assistência Social…).
  · O MUNICÍPIO: o do CADASTRO do estabelecimento credor na Receita (`estabelecimentos.uf/municipio`, código da
    Receita → IBGE por `dados/municipios_receita_rj.csv`). Grau `explicito`: o credor É o município.
    A Prefeitura do Rio recebe os repasses do Estado para o município do Rio como qualquer outra.
  · FICAM FORA, CONTADOS (`territorio_meta.repasses_fora_json`): ente municipal de outra UF; Poder Legislativo
    municipal (câmara não é a cidade recebendo repasse); regime próprio de previdência municipal (contribuição/
    compensação de servidor, não investimento) e serviço autônomo de água e esgoto (conta de consumo: é fornecedor).
    Credor que não é CNPJ ou não está na Receita não entra (não se adivinha a esfera).
  · INDISPONÍVEL ≠ 0: sem `receita_estab.db` ou sem a tabela de OBs, o componente fica INDISPONÍVEL (meta
    `repasses_status`), nunca zero.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path

from compliance_agent.esfera_orgao import NATUREZA_PUBLICA
from compliance_agent.reporting.intel_base import reais as _reais
from compliance_agent.territorio import base
from compliance_agent.territorio.geo import norm

FONTE = ("SIAFE-Rio (ob_orcamentaria_siafe, OB paga pela régua da casa) × Receita Federal (natureza jurídica e "
         "município do estabelecimento credor)")
NOTA = ("repasses e transferências = OB PAGA do SIAFE a ente municipal do RJ (prefeitura, fundo municipal, autarquia ou "
        "fundação municipal), identificado pela natureza jurídica na Receita; o município é o do cadastro do credor. "
        "É dinheiro pago, não valor contratado; fica à parte dos contratos e não se soma a eles no valor contratado")
# Executivo municipal (inclui órgão autônomo); o Legislativo municipal (1066) fica fora — contado
NATUREZAS = {k: v for k, v in NATUREZA_PUBLICA.items() if v[0] == "M" and v[1] != "Legislativo"}
ROTULO_NATUREZA = {"1031": "órgão do Executivo municipal", "1120": "autarquia municipal",
                   "1155": "fundação pública municipal", "1180": "órgão autônomo municipal", "1244": "município (prefeitura)",
                   "1279": "fundação pública municipal (direito privado)", "1309": "fundo público municipal (adm. indireta)",
                   "1333": "fundo público municipal (adm. direta)"}
_RE_PREVIDENCIA = re.compile(r"PREVID|\bPREV\b|PREV$|\bIPREV|\bRPPS\b|FUNDO DE APOSENT|INSTITUTO DE BENEFICIOS|ASSIST\w* AOS SERVIDORES")
_RE_SANEAMENTO = re.compile(r"\bSAAE\b|SERVICO AUTONOMO DE AGUA")
_DADOS = Path(__file__).resolve().parent / "dados"


def municipios_receita() -> dict[str, str]:
    """código de município da Receita → código IBGE (os 92 do RJ)."""
    with open(_DADOS / "municipios_receita_rj.csv", encoding="utf-8") as f:
        return {r["municipio_receita"]: r["cod_ibge"] for r in csv.DictReader(f)}


def classificar_credor(natureza: str | None, uf: str | None, municipio_receita: str | None, nome: str | None,
                       tabela: dict[str, str]) -> tuple[str | None, str | None]:
    """(cod_ibge, None) se o credor é ente municipal do RJ que conta como repasse; (None, motivo) se fica fora; (None, None)
    se nem é ente municipal (não é assunto deste módulo). Função PURA."""
    nat = (natureza or "").strip()
    if nat not in NATUREZA_PUBLICA or NATUREZA_PUBLICA[nat][0] != "M":
        return None, None
    if (uf or "").strip().upper() != "RJ":
        return None, "ente municipal de outra UF"
    if nat not in NATUREZAS:
        return None, "Poder Legislativo municipal (câmara)"
    n = norm(nome)
    if _RE_PREVIDENCIA.search(n):
        return None, "regime próprio de previdência municipal (não é investimento na cidade)"
    if _RE_SANEAMENTO.search(n):
        return None, "serviço autônomo de água e esgoto (conta de consumo: é fornecedor)"
    cod = tabela.get((municipio_receita or "").strip())
    if not cod:
        return None, "município do cadastro da Receita fora da tabela dos 92 do RJ"
    return cod, None


def _credores(rec: sqlite3.Connection) -> dict[str, tuple]:
    """CNPJ (14) → (natureza, uf, municipio_receita, razão social) de todo estabelecimento de ente MUNICIPAL (qualquer UF:
    os de fora entram para serem contados como fora)."""
    muni = [k for k, v in NATUREZA_PUBLICA.items() if v[0] == "M"]
    emp = {r[0]: (r[1], r[2]) for r in rec.execute(
        f"SELECT cnpj_basico, natureza_cod, razao_social FROM empresas WHERE natureza_cod IN ({','.join('?' * len(muni))})", muni)}
    out, chaves = {}, list(emp)
    for i in range(0, len(chaves), 500):
        lote = chaves[i:i + 500]
        for cnpj, cb, uf, mun in rec.execute(
                f"SELECT cnpj, cnpj_basico, uf, municipio FROM estabelecimentos WHERE cnpj_basico IN ({','.join('?' * len(lote))})", lote):
            out[cnpj] = (emp[cb][0], uf, mun, emp[cb][1])
    return out


def _ano_mes(data: str | None, exercicio) -> str | None:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", data or "")
    if m:
        return f"{m.group(3)}-{m.group(2)}"
    m = re.match(r"(\d{4})-(\d{2})", data or "")
    return f"{m.group(1)}-{m.group(2)}" if m else (f"{int(exercicio)}-00" if exercicio else None)


def apurar(con: sqlite3.Connection, rec: sqlite3.Connection) -> dict:
    """Lê as OBs pagas e devolve {linhas: [(cod_ibge, cnpj, nome, natureza, ano_mes, n, valor)], fora: {motivo: {n, valor}},
    ini, fim}. Só leitura."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    tabela, cred = municipios_receita(), _credores(rec)
    agg: dict[tuple, list] = {}
    fora: dict[str, dict] = {}
    datas: list[str] = []
    for credor, valor, data, exe in con.execute(
            f"SELECT credor, valor, data_emissao, exercicio FROM ob_orcamentaria_siafe WHERE {_ob_paga(con)}"):
        d = re.sub(r"\D", "", credor or "")
        if len(d) != 14 or d not in cred:
            continue
        nat, uf, mun, nome = cred[d]
        cod, motivo = classificar_credor(nat, uf, mun, nome, tabela)
        v = float(valor or 0)
        if not cod:
            if motivo:
                f = fora.setdefault(motivo, {"n": 0, "valor": 0.0})
                f["n"] += 1
                f["valor"] += v
            continue
        am = _ano_mes(data, exe)
        a = agg.setdefault((cod, d, nome, nat, am), [0, 0.0])
        a[0] += 1
        a[1] += v
        if am and not am.endswith("-00"):
            datas.append(am)
    linhas = [(k[0], k[1], k[2], k[3], k[4], a[0], round(a[1], 2)) for k, a in agg.items()]
    for f in fora.values():
        f["valor"] = round(f["valor"], 2)
    return {"linhas": linhas, "fora": fora, "ini": min(datas) if datas else None, "fim": max(datas) if datas else None}


def rodar(log=print) -> dict:
    """Regrava `territorio_repasse`. Fonte ausente → status INDISPONÍVEL (a tabela é esvaziada: não sobra número velho)."""
    db = base.abrir(escrita=True)
    rec_p, con_p = base.DATA / "receita_estab.db", base.DATA / "compliance.db"
    try:
        if not rec_p.exists():
            raise sqlite3.OperationalError(f"{rec_p.name} ausente")
        con, rec = base.fonte_ro("compliance.db"), base.fonte_ro("receita_estab.db")
        try:
            r = apurar(con, rec)
        finally:
            con.close()
            rec.close()
    except sqlite3.Error as e:
        db.execute("DELETE FROM territorio_repasse")
        base.por_meta(db, "repasses_status", f"INDISPONÍVEL — {e}")
        db.commit()
        db.close()
        log(f"[repasses] INDISPONÍVEL ({con_p.name} / {rec_p.name}): {e}")
        return {"status": "indisponivel"}
    db.execute("DELETE FROM territorio_repasse")
    db.executemany("INSERT INTO territorio_repasse(cod_ibge,credor_cnpj,credor_nome,natureza_cod,ano_mes,n_obs,valor) VALUES(?,?,?,?,?,?,?)",
                   r["linhas"])
    for chave, v in (("repasses_status", "ok"), ("repasses_em", base.agora()), ("repasses_ini", r["ini"] or ""),
                     ("repasses_fim", r["fim"] or ""), ("repasses_fora_json", json.dumps(r["fora"], ensure_ascii=False))):
        base.por_meta(db, chave, v)
    db.commit()
    db.close()
    tot = sum(x[6] for x in r["linhas"])
    log(f"[repasses] {sum(x[5] for x in r['linhas'])} OBs pagas a entes municipais do RJ, {_reais(tot)} em "
        f"{len({x[0] for x in r['linhas']})} municípios ({r['ini']}…{r['fim']}); fora: {r['fora']}")
    return {"status": "ok", "valor": tot, "fora": r["fora"]}
