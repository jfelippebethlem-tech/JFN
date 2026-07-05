# -*- coding: utf-8 -*-
"""Detector de FUNCIONÁRIO FANTASMA (servidor) por sinais públicos — OSINT legal.

Funcionário fantasma = quem recebe salário sem efetivamente trabalhar. A PROVA
definitiva é o registro de ponto/frequência (interno → só por requisição). O que
o OSINT entrega são INDÍCIOS que PRIORIZAM de quem pedir o ponto:

  s_acumulo    — mesma pessoa em 2 folhas públicas ao mesmo tempo (Câmara∩Prefeitura),
                 casada por nome único: incompatível cumprir jornada nos dois → um pode
                 ser fantasma. (sinal mais forte)
  s_distante   — lotado em gabinete no Rio, mas DOMICÍLIO ELEITORAL em cidade distante
                 (o sinal público mais recente de base da pessoa) → não comparecimento provável.
  s_candidato  — candidato em OUTRA cidade (base política/campanha longe) enquanto na folha.

Honesto: indício ≠ prova. Nada aqui é "fantasma confirmado" — é "peça o ponto deste".
Nunca usa base vazada. Sem CPF nas bases → casamento por nome é indício (homônimo marcado).
"""
from __future__ import annotations

from datetime import datetime

from compliance_agent.pcrj import db as _db

RIO = "RIO DE JANEIRO"

# Região Metropolitana do RJ — domicílio aqui = COMMUTE normal p/ trabalhar no Rio (não é indício).
# Só domicílio FORA desta cinta conta como "mora longe" (e ainda assim indício fraco: domicílio
# eleitoral ≠ residência — a pessoa pode votar na cidade natal e morar no Rio).
_METRO_RJ = {
    "RIO DE JANEIRO", "NITERÓI", "SÃO GONÇALO", "DUQUE DE CAXIAS", "NOVA IGUAÇU",
    "SÃO JOÃO DE MERITI", "BELFORD ROXO", "NILÓPOLIS", "MESQUITA", "QUEIMADOS",
    "JAPERI", "MAGÉ", "ITABORAÍ", "MARICÁ", "TANGUÁ", "GUAPIMIRIM", "SEROPÉDICA",
    "ITAGUAÍ", "PARACAMBI", "CACHOEIRAS DE MACACU", "RIO BONITO",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pcrj_fantasma_servidor (
    nome_norm     TEXT PRIMARY KEY,
    nome          TEXT,
    gabinetes     TEXT,
    cargos_camara TEXT,
    sinais        TEXT,          -- lista legível de indícios
    score         INTEGER,
    faixa         TEXT,          -- forte | verificar | fraco
    homonimo      INTEGER,       -- nome em ≥3 municípios distintos (ambiguidade)
    gerado_em     TEXT
);
CREATE INDEX IF NOT EXISTS ix_fantasma_faixa ON pcrj_fantasma_servidor(faixa);
"""


def _coletar(con) -> dict[str, dict]:
    """Reúne, por pessoa, SINAIS BOOLEANOS (uma vez cada) + evidência — sem somar por linha
    (somar por linha premiava homônimo: nome em N cidades virava score alto falso)."""
    pessoas: dict[str, dict] = {}

    def _p(nn, nome=""):
        p = pessoas.get(nn)
        if not p:
            p = {"nome": nome, "gabinetes": "", "cargos": "",
                 "acumulo": False, "acumulo_evid": [], "distante": False,
                 "candidato": False, "evid": [], "municipios": set(),
                 "benef_n": 0, "benef_rio": False, "benef_tipos": set(),
                 "eleito_fora": "", "origem_fora": "", "filiado_fora": ""}
            pessoas[nn] = p
        if nome and not p["nome"]:
            p["nome"] = nome
        return p

    # s_acumulo — Câmara∩Prefeitura por nome único (o mais forte); booleano + lista de postos
    for r in con.execute(
        "SELECT nome_norm, nome_camara, gabinetes, cargos_camara, orgao_pcrj, cargo_pcrj "
        "FROM pcrj_vinculo_cruzado WHERE confianca='indicio_nome_unico'"):
        p = _p(r["nome_norm"], r["nome_camara"])
        p["gabinetes"] = r["gabinetes"] or ""
        p["cargos"] = r["cargos_camara"] or ""
        p["acumulo"] = True
        p["acumulo_evid"].append(f"{r['orgao_pcrj']} / {r['cargo_pcrj']}")

    # s_distante — domicílio eleitoral em cidade ≠ Rio (booleano; guarda todas p/ detectar homônimo)
    for r in con.execute(
        "SELECT nome_norm, nome, municipio, uf, forca FROM pcrj_municipio_vinculo "
        "WHERE outra_cidade=1"):
        p = _p(r["nome_norm"], r["nome"])
        p["municipios"].add(r["municipio"])
        if (r["forca"] or 0) >= 3:
            p["distante"] = True

    # s_candidato — candidato em outra cidade (booleano)
    for r in con.execute(
        "SELECT DISTINCT nome_norm, municipio FROM tse_candidatura WHERE outra_cidade=1"):
        if r["nome_norm"] in pessoas:
            p = pessoas[r["nome_norm"]]
            p["municipios"].add((r["municipio"] or "").upper())
            p["candidato"] = True

    # s_eleito_fora — ELEITO (não suplente) em outra cidade = mandato fora do Rio (forte)
    for r in con.execute(
        "SELECT nome_norm, nome_tse, municipio, cargo, ano FROM tse_candidatura "
        "WHERE outra_cidade=1 AND eleito=1"):
        p = _p(r["nome_norm"], r["nome_tse"])
        p["municipios"].add((r["municipio"] or "").upper())
        p["eleito_fora"] = f"{r['cargo']} em {r['municipio']} ({r['ano']})"

    # s_filiado_fora — FILIAÇÃO partidária (Wayback TSE) com domicílio eleitoral fora do Rio.
    # Cobre MUITO mais gente que candidatura (não precisa ter sido candidato). Domicílio = onde vota.
    for r in con.execute(
        "SELECT nome_norm, nome, municipio, partido FROM pcrj_filiado "
        "WHERE municipio<>'' AND municipio<>'RIO DE JANEIRO'"):
        # todo filiado na tabela já foi casado com servidor/candidato no ingest → é alvo legítimo
        p = _p(r["nome_norm"], r["nome"])
        p["municipios"].add((r["municipio"] or "").upper())
        p["filiado_fora"] = f"{r['municipio']} ({r['partido']})"

    # s_origem_fora — origem eleitoral fora do RJ pelo TÍTULO (dígitos 9-10) ou naturalidade.
    # Corroboração de "base longe do Rio"; conservador (só afirma quando EXCLUI RJ).
    for r in con.execute(
        "SELECT nome_norm, nome_tse, uf_alistamento, uf_nascimento FROM tse_candidatura"):
        if r["nome_norm"] not in pessoas:
            continue
        p = pessoas[r["nome_norm"]]
        alist = (r["uf_alistamento"] or "").strip().upper()
        nasc = (r["uf_nascimento"] or "").strip().upper()
        if alist and alist != "RJ":
            p["origem_fora"] = f"título alistado em {alist}"
        elif nasc and nasc not in ("RJ", "") and not p.get("origem_fora"):
            p["origem_fora"] = f"naturalidade {nasc}"

    # s_beneficio — Bolsa Família/BPC (banco dedicado pcrj_benef.db). Só conta se o nome bate
    # com 1 PESSOA ÚNICA (por fragmento de CPF); homônimo (≥3 pessoas) é ruído, descartado.
    import sqlite3
    benef_db = _db.DB_PATH.parent / "pcrj_benef.db"
    if benef_db.exists():
        bc = sqlite3.connect(str(benef_db)); bc.row_factory = sqlite3.Row
        try:
            agg: dict[str, dict] = {}
            for r in bc.execute(
                "SELECT nome_norm, nome, beneficio, municipio, cpf_frag FROM pcrj_beneficio"):
                a = agg.setdefault(r["nome_norm"],
                                   {"nome": r["nome"], "frags": set(), "rio": False, "tipos": set()})
                a["frags"].add(r["cpf_frag"] or "?")
                a["tipos"].add(r["beneficio"])
                if (r["municipio"] or "") == RIO:
                    a["rio"] = True
            for nn, a in agg.items():
                p = _p(nn, a["nome"])
                p["benef_n"] = len(a["frags"])
                p["benef_rio"] = a["rio"]
                p["benef_tipos"] = a["tipos"]
        finally:
            bc.close()
    return pessoas


def _score(p: dict) -> tuple[int, list[str], bool]:
    """Score honesto: sinais booleanos, homônimo (nome em ≥3 cidades) NÃO pontua distância/
    candidatura (provável pessoa diferente) e nunca deixa passar de 'verificar'."""
    homonimo = len(p["municipios"]) >= 3
    sinais, score = [], 0
    if p["acumulo"]:
        score += 3
        postos = "; ".join(sorted(set(p["acumulo_evid"]))[:3])
        sinais.append(f"acúmulo Câmara∩Prefeitura ({postos})")
    if p["distante"] and not homonimo:
        score += 2
        sinais.append("domicílio eleitoral em cidade distante do Rio")
    if p["candidato"] and not homonimo:
        score += 2
        sinais.append("candidato em outra cidade enquanto vinculado")
    # eleito (mandato) em outra cidade — mais forte que só candidatar-se
    if p.get("eleito_fora") and not homonimo:
        score += 3
        sinais.append(f"🔴 ELEITO em outra cidade ({p['eleito_fora']}) — mandato fora do Rio")
    # origem eleitoral/naturalidade fora do RJ (título dígitos 9-10 / naturalidade) — corroboração
    if p.get("origem_fora") and not homonimo:
        score += 1
        sinais.append(f"origem fora do RJ ({p['origem_fora']})")
    # domicílio eleitoral (filiação) fora da Região Metropolitana = mora longe (não é commute).
    # Cidade metropolitana (Baixada/Niterói/SG) é deslocamento normal → NÃO pontua, só contexto.
    ff = p.get("filiado_fora") or ""
    ff_mun = ff.split(" (")[0].strip().upper()
    if ff and ff_mun and ff_mun not in _METRO_RJ and not homonimo:
        score += 2
        sinais.append(f"domicílio eleitoral em {ff} (fora da região metropolitana)")
    elif ff:
        sinais.append(f"filiado em {ff}")   # contexto (metropolitana = commute normal)
    # benefício assistencial — só o subconjunto DEFENSÁVEL (1 pessoa única); homônimo não pontua
    bn = p.get("benef_n", 0)
    tipos = "/".join(sorted(p.get("benef_tipos") or []))
    if bn == 1 and p.get("benef_rio"):
        score += 5
        sinais.append(f"🔴 recebe {tipos} no Rio (1 pessoa única) — renda assistencial incompatível com a folha")
    elif bn == 1:
        score += 2
        sinais.append(f"recebe {tipos} (1 pessoa única, fora do Rio)")
    elif bn >= 3:
        sinais.append(f"benefício {tipos}: nome em {bn} pessoas — homônimo, descartado")
    if homonimo:
        sinais.append(f"⚠ homônimo provável (nome em {len(p['municipios'])} cidades) — desambiguar por CPF")
    return score, sinais, homonimo


def _faixa(score: int, homonimo: bool) -> str:
    if homonimo:
        return "verificar" if score >= 3 else "fraco"   # homônimo nunca é 'forte'
    return "forte" if score >= 5 else "verificar" if score >= 3 else "fraco"


def detectar(db_path=None) -> dict:
    con = _db.conectar(db_path)
    con.executescript(_SCHEMA)
    pessoas = _coletar(con)

    agora = datetime.now().isoformat(timespec="seconds")
    con.execute("DELETE FROM pcrj_fantasma_servidor")
    faixas = {"forte": 0, "verificar": 0, "fraco": 0}
    aval = 0
    for nn, p in pessoas.items():
        score, sinais, homonimo = _score(p)
        if not sinais or score == 0:
            continue
        aval += 1
        faixa = _faixa(score, homonimo)
        faixas[faixa] += 1
        con.execute(
            "INSERT OR REPLACE INTO pcrj_fantasma_servidor "
            "(nome_norm, nome, gabinetes, cargos_camara, sinais, score, faixa, homonimo, gerado_em) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (nn, p["nome"], p["gabinetes"], p["cargos"], " · ".join(sinais),
             score, faixa, 1 if homonimo else 0, agora))
    con.commit()
    con.close()
    return {"avaliados": aval, "forte": faixas["forte"],
            "verificar": faixas["verificar"], "fraco": faixas["fraco"]}


if __name__ == "__main__":
    import json
    print(json.dumps(detectar(), ensure_ascii=False, indent=1))
