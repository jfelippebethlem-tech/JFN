#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quem, entre os agentes públicos que conhecemos, aparece no quadro societário do país.

A PERGUNTA DO DONO, em 2026-08-06: *relações de políticos, comissionados e familiares com empresas,
ONGs e associações — de forma ampla*. O insumo já existia e estava sendo usado ao contrário:
`socios_reverso` é semeado pelos sócios dos NOSSOS FORNECEDORES, ou seja, parte da empresa e chega
à pessoa. Aqui a semente é a PESSOA COM PODER — folha do Estado, ALERJ, comissionados — e a
travessia é dela para todas as sociedades dela no Brasil.

A FONTE É O CADASTRO INTEIRO. `data/receita_dump/socios_full.csv.zst`, 27.650.926 linhas, o QSA de
todo o Brasil, atualizado mensalmente. Não é amostra: `socios_receita` (59.506 linhas) é a fatia
curada dos nossos fornecedores e responderia 0,7% desta pergunta.

O QUE ISTO **NÃO** FAZ, e precisa estar escrito antes do primeiro número:

  · **Não prova identidade.** A folha não traz CPF utilizável e o dump traz o CPF MASCARADO
    (`***NNNNNN**`). O casamento é por NOME NORMALIZADO — indício, nunca prova. Medido nesta base:
    dos nomes de servidor que casam no QSA, **4,7%** casam com MAIS DE UM CPF mascarado distinto,
    isto é, são homônimos comprovados; os outros podem sê-lo sem que a base o mostre. Nome com
    menos de três termos não entra.
  · **Não estabelece parentesco.** Sobrenome compartilhado NÃO é sinal: 16,9% das empresas com dois
    ou mais sócios PF têm sobrenome de família em comum — empresa familiar é a norma no Brasil.
    O eixo de parentesco vive em `osint/parentesco`, com prevalência medida, e só corrobora.
  · **Não afirma irregularidade.** Servidor pode ser sócio; o que a lei restringe é o exercício de
    comércio por certas carreiras, o conflito de interesses e a contratação pelo próprio órgão. O
    achado aqui é *há o que conferir*, e o campo `diligencia` diz o quê.

O QUE ELE PESA. Três marcadores objetivos, todos verificáveis na base, e nenhum deles opinativo:
`comissionado` (cargo em comissão / livre nomeação — quem entra sem concurso), `terceiro_setor` (a
entidade é associação, fundação ou organização religiosa — natureza 3xx, a modalidade do caso das
ONGs) e `recebeu_do_estado` (a entidade tem Ordem Bancária contabilizada no SIAFE — dinheiro que
saiu de fato, nunca empenho).

    python -m tools.agente_publico_reverso            # constrói e resume
    python -m tools.agente_publico_reverso --so-resumo
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import time
import unicodedata
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_ZST = _REPO / "data" / "receita_dump" / "socios_full.csv.zst"
_MIN_TERMOS = 3           # "JOSE SILVA" casa com meio estado; três termos é o mínimo defensável

_SQL = """
CREATE TABLE IF NOT EXISTS agente_publico_societario (
    nome_norm       TEXT NOT NULL,
    nome_socio      TEXT NOT NULL,
    doc_socio       TEXT,
    cnpj_basico     TEXT NOT NULL,
    qualif_cod      TEXT,
    origem          TEXT NOT NULL,   -- folha_estado | alerj
    cargo           TEXT,
    vinculo         TEXT,
    orgao           TEXT,
    comissionado    INTEGER NOT NULL DEFAULT 0,
    construido_em   TEXT NOT NULL,
    PRIMARY KEY (nome_norm, cnpj_basico, doc_socio)
)"""
_INDICES = (
    "CREATE INDEX IF NOT EXISTS ix_aps_cnpj ON agente_publico_societario(cnpj_basico)",
    "CREATE INDEX IF NOT EXISTS ix_aps_comis ON agente_publico_societario(comissionado)",
)

# Livre nomeação e exoneração é o que interessa: quem entra sem concurso e sai por vontade de quem
# nomeou. Os rótulos vêm da própria base (`vinculo` e `cargo` de `registros_folha`).
_RX_COMISSAO = re.compile(r"COMISS|LIVRE\s+NOMEA|EM\s+COMISSAO|ASSESSOR|GABINETE|SECRETARI", re.I)


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z ]", " ", s)).strip().upper()


def semente(con: sqlite3.Connection) -> dict[str, dict]:
    """Agentes públicos conhecidos, por nome normalizado. Cargo mais 'forte' vence o empate."""
    alvo: dict[str, dict] = {}
    for nome, cargo, vinc, org in con.execute(
            "SELECT DISTINCT nome, cargo, vinculo, orgao_nome FROM registros_folha"):
        n = norm(nome)
        if len(n.split()) < _MIN_TERMOS:
            continue
        com = bool(_RX_COMISSAO.search(f"{cargo} {vinc}"))
        atual = alvo.get(n)
        if atual is None or (com and not atual["comissionado"]):
            alvo[n] = {"nome": nome, "cargo": cargo, "vinculo": vinc, "orgao": org,
                       "origem": "folha_estado", "comissionado": int(com)}
    for nome, cargo in con.execute("SELECT DISTINCT nome, cargo FROM alerj_folha"):
        n = norm(nome)
        if len(n.split()) < _MIN_TERMOS:
            continue
        # A ALERJ prevalece sobre a folha do Estado: mandato e gabinete são o poder que interessa.
        alvo[n] = {"nome": nome, "cargo": cargo, "vinculo": "ALERJ", "orgao": "ALERJ",
                   "origem": "alerj", "comissionado": 1}
    return alvo


def varrer(alvo: dict[str, dict], zst: Path = _ZST):
    """Uma passada de streaming pelo cadastro nacional. Nada é carregado em memória."""
    if not zst.exists():
        raise SystemExit(f"cadastro nacional ausente: {zst} — rode tools/socios_dump_refresh.sh")
    proc = subprocess.Popen(["zstd", "-dcq", str(zst)], stdout=subprocess.PIPE,
                            preexec_fn=lambda: os.nice(10))
    lidas = 0
    try:
        for bruto in proc.stdout:
            lidas += 1
            p = bruto.decode("utf-8", "replace").rstrip("\n").split(";")
            if len(p) < 5 or p[1].strip('"') != "2":     # só pessoa física
                continue
            nome = p[2].strip('"')
            n = norm(nome)
            meta = alvo.get(n)
            if meta is None:
                continue
            yield n, nome, p[3].strip('"'), p[0].strip('"'), p[4].strip('"'), meta
    finally:
        proc.stdout.close()
        proc.wait()
    varrer.lidas = lidas


def construir(db: str = "") -> dict:
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(db or _DB, timeout=120)
    con.execute(_SQL)
    for ix in _INDICES:
        con.execute(ix)
    alvo = semente(con)
    t0 = time.time()
    con.execute("DELETE FROM agente_publico_societario")
    n = 0
    for nome_norm, nome, doc, raiz, qualif, meta in varrer(alvo):
        con.execute(
            "INSERT OR REPLACE INTO agente_publico_societario (nome_norm, nome_socio, doc_socio, "
            "cnpj_basico, qualif_cod, origem, cargo, vinculo, orgao, comissionado, construido_em) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,date('now'))",
            (nome_norm, nome, doc, raiz, qualif, meta["origem"], meta["cargo"], meta["vinculo"],
             meta["orgao"], meta["comissionado"]))
        n += 1
        if n % 500 == 0:
            con.commit()
    con.commit()
    out = {"agentes_semeados": len(alvo), "linhas_gravadas": n,
           "linhas_lidas": getattr(varrer, "lidas", 0), "segundos": round(time.time() - t0, 1)}
    con.close()
    return out


# AS EXPLICAÇÕES QUE SÃO O DESENHO DO PROGRAMA, NÃO O ACHADO. Medidas em 2026-08-06 sobre os 296
# pares defensáveis: `apoio_a_escola` sozinha responde por **35,1%** deles. Associação de Apoio à
# Escola é a entidade que a própria rede estadual usa para descentralizar recurso à unidade, e o
# dirigente é, por desenho, um professor daquela escola. Idem fundação de apoio universitária
# (Lei 8.958/1994), associação de classe (a Mútua dos Magistrados tem magistrado na direção por
# definição) e cooperativa. Vetar isso não é benevolência: é a diferença entre uma fila de trabalho
# e uma lista que acusa um terço do magistério de improbidade.
_INSTITUCIONAL = {
    "apoio_a_escola": re.compile(r"APOIO\s+[AÀ]\s+ESCOLA|APOIO\s+ESCOLA|CIEP|CAIC", re.I),
    "fundacao_de_apoio_universitaria": re.compile(
        r"FUNDA[CÇ][AÃ]O.*(APOIO|PESQUISA|ENSINO|DESENVOLVIMENTO|UNIVERSIT)", re.I),
    "associacao_de_classe": re.compile(
        r"M[UÚ]TUA|SINDICATO|ASSOCIA[CÇ][AÃ]O\s+DOS?\s+(MAGISTR|SERVIDOR|PROFESSOR|M[EÉ]DICO"
        r"|DELEGADO|OFICIA)", re.I),
    "cooperativa": re.compile(r"COOPERATIVA|UNIMED", re.I),
}


def explicacao_institucional(razao_social: str) -> str:
    """Nome da explicação inocente conhecida, ou vazio. Vazio NÃO significa que não haja uma."""
    for nome, rx in _INSTITUCIONAL.items():
        if rx.search(str(razao_social or "")):
            return nome
    return ""


def fila(db: str = "", *, so_comissionados: bool = False) -> list[dict]:
    """Pares agente × entidade paga pelo Estado, do maior valor para o menor, já filtrados.

    Três cortes, todos objetivos: a entidade tem OB CONTABILIZADA no SIAFE (dinheiro que saiu, não
    empenho); o nome do agente tem UM único CPF mascarado no índice (homônimo comprovado sai — os
    que ficam podem ser homônimos sem que a base o mostre); e a explicação institucional conhecida
    vai marcada, nunca escondida.
    """
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True)
    pago = {r[0]: r[1] for r in con.execute(
        "SELECT substr(credor,1,8), SUM(valor) FROM ob_orcamentaria_siafe "
        "WHERE status='Contabilizado' AND length(credor)=14 GROUP BY 1")}
    razao: dict[str, tuple[str, str]] = {}
    for tab in ("empresas_min", "empresas_cadastro"):
        try:
            for r in con.execute(f"SELECT cnpj_basico, razao_social, natureza_cod FROM {tab}"):
                razao[r[0]] = (str(r[1] or ""), str(r[2] or ""))
        except sqlite3.Error:
            continue
    ndocs = dict(con.execute("SELECT nome_norm, COUNT(DISTINCT doc_socio) "
                             "FROM agente_publico_societario GROUP BY 1"))
    linhas = list(con.execute(
        "SELECT nome_norm, nome_socio, cnpj_basico, cargo, orgao, comissionado, origem "
        "FROM agente_publico_societario"))
    con.close()

    quantos = {}
    for x in linhas:
        if x[2] in pago and ndocs.get(x[0]) == 1:
            quantos[x[2]] = quantos.get(x[2], 0) + 1

    out = []
    for nome_norm, nome, raiz, cargo, orgao, com, origem in linhas:
        if raiz not in pago or ndocs.get(nome_norm) != 1:
            continue
        rz, nat = razao.get(raiz, ("", ""))
        out.append({
            "agente": nome, "cargo": cargo, "orgao": orgao, "origem": origem,
            "comissionado": bool(com), "cnpj_basico": raiz,
            "entidade": rz or f"(raiz {raiz} — razão social não capturada)",
            "terceiro_setor": nat.startswith("3"), "valor_recebido": pago[raiz],
            "explicacao_institucional": explicacao_institucional(rz),
            "servidores_no_qsa": quantos.get(raiz, 1),
            "diligencia": ("confirmar identidade por CPF na ficha funcional e no QSA integral da "
                           "JUCERJA; verificar se a sociedade é anterior ou posterior à posse, e "
                           "se o órgão do agente é o contratante"),
        })
    if so_comissionados:
        out = [x for x in out if x["comissionado"]]
    return sorted(out, key=lambda x: -x["valor_recebido"])


def resumo(db: str = "") -> dict:
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True)
    q = con.execute
    tot = q("SELECT COUNT(DISTINCT nome_norm), COUNT(*) FROM agente_publico_societario").fetchone()
    # HOMÔNIMO COMPROVADO: o mesmo nome com dois CPFs mascarados distintos. Não é estimativa.
    homon = q("SELECT COUNT(*) FROM (SELECT nome_norm FROM agente_publico_societario "
              "GROUP BY nome_norm HAVING COUNT(DISTINCT doc_socio) > 1)").fetchone()[0]
    ter = q("SELECT COUNT(*) FROM agente_publico_societario a JOIN empresas_min e "
            "ON e.cnpj_basico=a.cnpj_basico WHERE substr(e.natureza_cod,1,1)='3'").fetchone()[0]
    din = q("SELECT COUNT(DISTINCT a.nome_norm || a.cnpj_basico) FROM agente_publico_societario a "
            "JOIN ob_orcamentaria_siafe o ON substr(o.credor,1,8)=a.cnpj_basico "
            "WHERE o.status='Contabilizado'").fetchone()[0]
    con.close()
    return {"pessoas": tot[0], "vinculos_societarios": tot[1],
            "nomes_com_mais_de_um_cpf": homon, "entidades_terceiro_setor": ter,
            "pares_pessoa_entidade_que_recebeu_do_estado": din}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--so-resumo", action="store_true", help="não reconstrói, só mede")
    ap.add_argument("--fila", type=int, default=0, help="imprime os N primeiros da fila")
    ap.add_argument("--so-comissionados", action="store_true")
    a = ap.parse_args()
    if not a.so_resumo and not a.fila:
        for k, v in construir().items():
            print(f"{k:34s} {v}")
    if a.fila:
        f = fila(so_comissionados=a.so_comissionados)
        print(f"fila: {len(f)} pares (portador único, entidade com OB contabilizada)")
        for x in f[:a.fila]:
            marca = "★" if x["comissionado"] else " "
            expl = f"  ⟨{x['explicacao_institucional']}⟩" if x["explicacao_institucional"] else ""
            print(f"{marca}{x['agente'][:34]:34s} | {str(x['cargo'])[:24]:24s} | "
                  f"{str(x['orgao'])[:24]:24s} | {x['entidade'][:32]:32s} "
                  f"R$ {x['valor_recebido']:>14,.2f}{expl}")
        return
    print("── resumo ──")
    for k, v in resumo().items():
        print(f"{k:44s} {v}")


if __name__ == "__main__":
    main()
