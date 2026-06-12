# -*- coding: utf-8 -*-
"""Acúmulo de cargos — servidor da folha da ALERJ que TAMBÉM está na folha do Estado (e vice-versa).

Pedido do dono: cruzar os funcionários de gabinete dos deputados (folha ALERJ, `alerj_folha`) com os nomeados no
governo do Estado (`registros_folha`, 257k) — nos dois sentidos (quem foi do Estado→ALERJ ou ALERJ→Estado; a
`competencia` indica direção/simultaneidade). Pessoa nas DUAS folhas = **indício de acúmulo de cargos** (CF art.
37, XVI/XVII — vedação salvo exceções; acúmulo remunerado simultâneo é o alvo).

Cruzamento por NOME normalizado (a folha ALERJ não traz CPF; `registros_folha` traz CPF mascarado + nome). Honesto:
homônimo é possível → é **indício** (corroborar por CPF/data), nunca prova. Disponível a QUALQUER MOMENTO (consulta).
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

_DB = Path("data") / "compliance.db"


def _norm(s: str) -> str:
    s = (s or "").upper().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def _con(db_path, ro=True):
    p = Path(db_path or _DB)
    if ro:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c = sqlite3.connect(str(p), timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    return c


_DDL = """CREATE TABLE IF NOT EXISTS alerj_folha (
    nome TEXT, nome_norm TEXT, cargo TEXT, mes_ano TEXT, ingerido_em TEXT,
    PRIMARY KEY (nome_norm, mes_ano))"""


def ingerir_folha(itens: list[dict], mes_ano: str, db_path=None) -> int:
    """Grava os servidores da folha ALERJ (idempotente por nome_norm+mes_ano)."""
    from datetime import datetime
    con = _con(db_path, ro=False)
    try:
        con.execute(_DDL)
        con.execute("CREATE INDEX IF NOT EXISTS ix_alerj_folha_norm ON alerj_folha(nome_norm)")
        ts = datetime.now().isoformat(timespec="seconds")
        n = 0
        for it in itens:
            nn = _norm(it.get("nome", ""))
            if len(nn.split()) < 2:
                continue
            con.execute("INSERT OR REPLACE INTO alerj_folha (nome,nome_norm,cargo,mes_ano,ingerido_em) VALUES (?,?,?,?,?)",
                        (it.get("nome"), nn, it.get("cargo"), mes_ano, ts))
            n += 1
        con.commit()
        return n
    finally:
        con.close()


def classificar_legalidade(ac: dict) -> dict:
    """Classifica a legalidade do acúmulo (CF art. 37, XVI/XVII). Nem todo acúmulo é ilícito — pode ser legal por
    cargo comissionado c/ afastamento, aposentadoria, cessão, ou por ser período distinto (não simultâneo)."""
    vinc = _norm(ac.get("vinculo_estado") or "")
    cargo_e = _norm(ac.get("cargo_estado") or "")
    rem = ac.get("remuneracao_estado") or 0
    comp = (ac.get("competencia_estado") or "")[:7]          # AAAA-MM (apenas o snapshot disponível, NÃO o fim do vínculo)

    # Provável LEGAL: aposentadoria acumula (CF 37 §10); sem remuneração = sem ônus (afastado/licenciado).
    if "INATIV" in vinc or "APOSENT" in vinc:
        return {"status": "PROVAVEL LEGAL", "motivo": "vínculo estadual INATIVO/aposentado — aposentadoria acumula com comissão/cargo eletivo (CF 37 §10)"}
    if rem == 0:
        return {"status": "PROVAVEL LEGAL", "motivo": "sem remuneração no Estado (provável afastado/licenciado sem ônus = sem acúmulo remunerado)"}
    # Cessão/licença (no vínculo OU no cargo, ex.: cargo 'CEDIDO') — PODE ser legal; depende do ato (com/sem ônus).
    if any(k in vinc or k in cargo_e for k in ("CEDID", "DISPOSIC", "LICENC", "AFAST", "A DISPOSICAO")):
        return {"status": "VERIFICAR", "motivo": "cessão/licença (cedido/à disposição) — pode ser legal; conferir o ato (com/sem ônus) e se há afastamento do efetivo"}
    # Ativo e remunerado no Estado: NÃO concluímos ilegalidade (o snapshot não prova simultaneidade nem afastamento).
    excecao = "comissão" if "COMISS" in cargo_e else "efetivo"
    return {"status": "VERIFICAR",
            "motivo": (f"Estado ATIVO/remunerado (cargo {excecao}, comp. {comp}) — **possível** acúmulo, NÃO confirmado: a "
                       "competência é só o snapshot disponível (não prova fim do vínculo). Confirmar simultaneidade + "
                       "afastamento/licença + se é exceção do art. 37 XVI (2 magistério, magistério+técnico, 2 saúde)")}


def cruzar(db_path=None, limite: int = 200) -> dict:
    """Pessoas na folha da ALERJ **e** na do Estado — com classificação de LEGALIDADE (CF 37 XVI/XVII). Por nome."""
    try:
        con = _con(db_path)
        try:
            estado = {}
            for nome, orgao, cargo, comp, rem, vinc in con.execute(
                    "SELECT nome, orgao_nome, cargo, competencia, remuneracao_bruta, vinculo FROM registros_folha "
                    "WHERE nome IS NOT NULL AND nome<>''"):
                nn = _norm(nome)
                if nn not in estado or (rem or 0) > (estado[nn].get("rem") or 0):
                    estado[nn] = {"orgao": orgao, "cargo": cargo, "competencia": comp, "rem": rem or 0, "vinculo": vinc}
            achados = []
            for nome, nome_norm, cargo_alerj, mes in con.execute(
                    "SELECT nome, nome_norm, cargo, mes_ano FROM alerj_folha"):
                e = estado.get(nome_norm)
                if not e:
                    continue
                ac = {"nome": nome, "cargo_alerj": cargo_alerj, "mes_alerj": mes,
                      "orgao_estado": e["orgao"], "cargo_estado": e["cargo"], "vinculo_estado": e["vinculo"],
                      "competencia_estado": e["competencia"], "remuneracao_estado": e["rem"]}
                ac["legalidade"] = classificar_legalidade(ac)
                achados.append(ac)
            # ordena: INDÍCIO primeiro, depois VERIFICAR, depois por remuneração
            ordem = {"INDICIO": 0, "VERIFICAR": 1, "PROVAVEL LEGAL": 2}
            achados.sort(key=lambda a: (ordem.get(a["legalidade"]["status"], 3), -(a["remuneracao_estado"] or 0)))
            n_alerj = con.execute("SELECT COUNT(DISTINCT nome_norm) FROM alerj_folha").fetchone()[0]
            n_ind = sum(1 for a in achados if a["legalidade"]["status"] == "INDICIO")
            n_ver = sum(1 for a in achados if a["legalidade"]["status"] == "VERIFICAR")
            return {"ok": True, "n_alerj": n_alerj, "n_acumulo": len(achados), "n_indicio": n_ind, "n_verificar": n_ver,
                    "achados": achados[:limite], "leitura": _leitura(achados, n_alerj, n_ind, n_ver)}
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "_nota": f"INDISPONÍVEL: {str(exc)[:160]}"}


def _leitura(achados: list, n_alerj: int, n_ind: int = 0, n_ver: int = 0) -> str:
    if not n_alerj:
        return "Folha da ALERJ ainda não ingerida (INDISPONÍVEL — rodar o coletor `alerj_transparencia`)."
    if not achados:
        return (f"Dos **{n_alerj}** servidores da ALERJ, **nenhum** consta também na folha do Estado "
                "(`registros_folha`) — acúmulo **AFASTADO** para os cobertos (a base do Estado pode estar parcial).")
    legais = len(achados) - n_ind - n_ver
    return (f"**{len(achados)}** servidor(es) da ALERJ constam **também** na folha do Estado (de {n_alerj} verificados). "
            f"Legalidade (CF art. 37, XVI/XVII) — **acúmulo NÃO é automaticamente ilícito**: **{n_ver} a VERIFICAR** "
            f"(ativo/remunerado ou cessão — possível acúmulo, exige confirmar simultaneidade + afastamento), "
            f"**{legais} provável legal** (inativo/aposentado ou sem remuneração no Estado). Exceções legais: aposentadoria "
            "(CF 37 §10), comissionado com afastamento do efetivo, cessão sem ônus, e os pares do art. 37 XVI (2 magistério; "
            "magistério+técnico/científico; 2 saúde). ⚠ A competência da folha do Estado é só o **snapshot** disponível — "
            "não prova fim nem simultaneidade do vínculo. Corroborar por **CPF, atos de nomeação/afastamento e período**. "
            "Homônimo possível; nome é público, CPF do Estado mascarado (LGPD).")


if __name__ == "__main__":  # pragma: no cover
    r = cruzar()
    print(r.get("leitura"))
    for a in (r.get("achados") or [])[:20]:
        lg = a["legalidade"]
        print(f"  [{lg['status']:13}] {a['nome'][:28]:28} | ALERJ {a['cargo_alerj'][:16]:16} | Estado {(a['cargo_estado'] or '')[:16]:16} "
              f"({a.get('vinculo_estado') or '?'}, R$ {a['remuneracao_estado']:,.0f}, {a['competencia_estado']}) — {lg['motivo'][:60]}")
