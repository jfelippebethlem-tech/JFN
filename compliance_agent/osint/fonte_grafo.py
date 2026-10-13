# -*- coding: utf-8 -*-
"""Alimenta o `GrafoVinculos` com o acervo REAL — o caller que faltava (item G.3 do roadmap).

POR QUE ESTE MÓDULO EXISTE. `osint/vinculos.py` tem 353 linhas de motor calibrado — força por tipo
de aresta, caminho mais FORTE em vez de mais curto, detecção de ciclo na subida societária — e
nunca rodou sobre dado real: o pacote `osint/` inteiro estava sem um único caller em produção. Ao
mesmo tempo, o grafo que o painel de fato serve (`grafo_poder`) liga sócios **por nome
normalizado**, que é justamente o que `vinculos.py` classifica como aresta de força 0,10 ("existe
para APARECER, não para pesar"). A régua honesta existia e não estava onde o usuário olhava.

O QUE ELE FAZ, e o que se recusa a fazer:

  · Monta o grafo a partir de `socios_receita` (QSA oficial da RFB), subindo a cadeia PJ→PJ. Há
    2.449 elos societários em que o sócio-empresa também consta da base — é sobre eles que o
    `beneficiario_final` finalmente tem o que percorrer.
  · **Não finge que o CPF está resolvido.** A RFB entrega o CPF do sócio MASCARADO (`***261845**`).
    Uma pessoa física entra no grafo como nó `pf_nome:` — não documentado —, com os seis dígitos
    centrais compondo a chave para que dois homônimos com máscaras diferentes não se fundam. Isso é
    deliberado: a colisão medida de CPF mascarado nesta base é de ~4%, e o `beneficiario_final`
    devolve `documentado=False` para que a peça diga o que sabe.
  · **Não afirma vínculo à época.** A base é um snapshot único (`fonte_mes`) e traz `data_entrada`
    sem `data_saida`. A aresta carrega a data de entrada e a competência do snapshot; a pergunta
    "era sócio no dia do certame?" sai como INDISPONÍVEL, nunca como afastada. Ver
    `osint/historico_societario.py`.
"""
from __future__ import annotations

import re
import logging
import sqlite3
from typing import Any

from compliance_agent.osint.vinculos import GrafoVinculos, no_pf, no_pj

logger = logging.getLogger(__name__)

__all__ = ["montar_grafo_societario", "beneficiario_final_do_cnpj", "cobertura_qsa"]

_RE_DIG = re.compile(r"\D")


def _raiz(cnpj: Any) -> str:
    """Raiz de 8 dígitos — é por ela que `socios_receita` indexa (`cnpj_basico`)."""
    return _RE_DIG.sub("", str(cnpj or ""))[:8]


def _no_socio(linha: sqlite3.Row) -> tuple[str, str, bool]:
    """`(chave_do_no, rótulo, é_pj)` para uma linha de QSA.

    Sócio PJ (`ident='1'`) traz o CNPJ íntegro — é o degrau que permite subir a cadeia. A CHAVE,
    porém, É A RAIZ, e isso não é detalhe: o alvo de cada nível entra como `no_pj(raiz)`, de modo
    que o sócio PJ chaveado pelos 14 dígitos virava um SEGUNDO nó da mesma empresa e a cadeia se
    partia exatamente no degrau que este código existe para subir. Medido em 2026-08-06 sobre os
    400 maiores credores do SIAFE: dos 17 com cadeia de duas ou mais empresas, **17** tinham o nó
    partido — o beneficiário final parava no primeiro salto em todos eles. Filial não é outra
    empresa, e a régua de contato compartilhado já seguia essa mesma identidade.

    Sócio PF (`ident='2'`) traz só a máscara; a chave leva os seis dígitos centrais para não
    fundir homônimos, e o rótulo fica limpo para a peça.
    """
    nome = (linha["nome_socio"] or "").strip()
    doc = (linha["doc_socio"] or "").strip()
    if str(linha["ident"]) == "1":
        return no_pj(_raiz(doc) or doc, nome), nome, True
    meio = _RE_DIG.sub("", doc)[:6]
    return no_pf("", f"{nome}|{meio}"), nome, False


def _fonte(linha: sqlite3.Row) -> str:
    # `fonte_mes` só existe nas linhas que vieram do dump; consulta antiga pode não trazer a coluna.
    # Sem ela a procedência sai com 'n/d' — declarada como desconhecida, nunca omitida: aresta sem
    # data de referência é aresta que o leitor precisa saber que não tem data.
    mes = ""
    try:
        mes = (linha["fonte_mes"] or "").strip()
    except (IndexError, KeyError):
        logger.debug("linha de QSA sem coluna fonte_mes; procedência sai como n/d")
    return f"QSA/Receita Federal (dados abertos CNPJ, snapshot {mes or 'n/d'})"


def montar_grafo_societario(con: sqlite3.Connection, cnpj: str, *, profundidade: int = 4
                            ) -> tuple[GrafoVinculos, dict]:
    """Grafo de `socio_de` a partir do CNPJ, subindo enquanto o sócio for PJ conhecida.

    Devolve `(grafo, diagnostico)`. O diagnóstico não é enfeite: ele é o que separa "esta empresa
    não tem sócio PJ" de "não capturamos o QSA desta empresa" — a distinção que a casa já errou
    antes ao ler ausência de registro como ausência de fato.
    """
    con.row_factory = sqlite3.Row
    g = GrafoVinculos()
    raiz0 = _raiz(cnpj)
    diag = {"raiz": raiz0, "visitadas": [], "sem_qsa": [], "n_arestas": 0, "profundidade": profundidade}
    if not raiz0:
        diag["erro"] = "CNPJ vazio ou inválido"
        return g, diag

    vistos: set[str] = set()
    fila: list[tuple[str, int]] = [(raiz0, 0)]
    while fila:
        raiz, nivel = fila.pop(0)
        if raiz in vistos or nivel >= profundidade:
            continue
        vistos.add(raiz)
        linhas = con.execute(
            "SELECT cnpj_basico, ident, nome_socio, doc_socio, qualificacao_txt, data_entrada, "
            "faixa_etaria, fonte_mes FROM socios_receita WHERE cnpj_basico=?", (raiz,)).fetchall()
        if not linhas:
            diag["sem_qsa"].append(raiz)
            continue
        diag["visitadas"].append(raiz)
        alvo = no_pj(raiz)
        g.rotular(alvo, _razao_social(con, raiz) or raiz)
        for ln in linhas:
            chave, rotulo, eh_pj = _no_socio(ln)
            g.rotular(chave, rotulo)
            a = g.ligar(
                chave, alvo, "socio_de",
                fonte=_fonte(ln),
                data=_data_iso(ln["data_entrada"]),
                detalhe=(ln["qualificacao_txt"] or "").strip(),
            )
            if a is not None:
                diag["n_arestas"] += 1
            if eh_pj:
                prox = _raiz(ln["doc_socio"])
                if prox and prox not in vistos:
                    fila.append((prox, nivel + 1))
    return g, diag


def _razao_social(con: sqlite3.Connection, raiz: str) -> str:
    for tabela, col in (("empresas_cadastro", "razao_social"), ("empresas_min", "razao_social")):
        try:
            r = con.execute(f"SELECT {col} FROM {tabela} WHERE cnpj_basico=? LIMIT 1", (raiz,)).fetchone()
        except sqlite3.Error:
            continue
        if r and r[0]:
            return str(r[0]).strip()
    return ""


def _data_iso(aaaammdd: Any) -> str:
    """`'20220217'` → `'2022-02-17'`. Data ilegível vira vazio — melhor lacuna que data inventada."""
    d = _RE_DIG.sub("", str(aaaammdd or ""))
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d[:4] != "0000" else ""


def beneficiario_final_do_cnpj(cnpj: str, *, db_path: str = "", profundidade: int = 4) -> dict:
    """G.3 — quem, ao fim da cadeia societária, está por trás deste CNPJ.

    Resultado sem pessoas NÃO é "não há beneficiário": é lacuna de captura, e o campo `motivo` do
    motor diz exatamente isso. `cobertura` informa quantas empresas da cadeia tinham QSA na base,
    para que o leitor saiba o quanto da subida foi observada.
    """
    from compliance_agent.reporting.intel_base import _DB

    caminho = db_path or _DB
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        g, diag = montar_grafo_societario(con, cnpj, profundidade=profundidade)
        if diag.get("erro"):
            return {"ok": False, "motivo": diag["erro"], "cnpj": cnpj}
        alvo = no_pj(_raiz(cnpj))
        out = g.beneficiario_final(alvo)
    finally:
        con.close()

    n_vis, n_sem = len(diag["visitadas"]), len(diag["sem_qsa"])
    total = n_vis + n_sem
    out.update({
        "ok": True,
        "cnpj": cnpj,
        "cobertura": {
            "empresas_na_cadeia": total,
            "com_qsa": n_vis,
            "sem_qsa": n_sem,
            "pct": round(100.0 * n_vis / total, 1) if total else 0.0,
            "nota": ("Empresa da cadeia sem QSA na base é lacuna de CAPTURA — o degrau existe e não "
                     "foi observado. INDISPONÍVEL não é ausência de sócio."),
        },
        "n_arestas": diag["n_arestas"],
        "documentacao": {
            "cpf_mascarado": True,
            "nota": ("A Receita entrega o CPF do sócio mascarado (***NNNNNN**). Pessoa física entra "
                     "como NÃO documentada: o nome mais seis dígitos centrais identificam com "
                     "probabilidade alta, não com certeza (colisão medida ~4% nesta base)."),
        },
        "temporalidade": {
            "tem_data_saida": False,
            "nota": ("A base traz data de ENTRADA na sociedade e nenhuma data de saída, e é um "
                     "snapshot único. 'Era sócio na data do certame?' é INDISPONÍVEL — cabe "
                     "diligência à JUCERJA (ficha cadastral com histórico de alterações)."),
        },
    })
    return out


def cobertura_qsa(db_path: str = "") -> dict:
    """Quanto do acervo tem QSA — o denominador que impede ler silêncio como limpeza."""
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db_path or _DB}?mode=ro", uri=True)
    try:
        n_socios = con.execute("SELECT COUNT(*) FROM socios_receita").fetchone()[0]
        n_raizes = con.execute("SELECT COUNT(DISTINCT cnpj_basico) FROM socios_receita").fetchone()[0]
        n_pj = con.execute("SELECT COUNT(*) FROM socios_receita WHERE ident='1'").fetchone()[0]
        n_encadeaveis = con.execute(
            "SELECT COUNT(*) FROM socios_receita s JOIN socios_receita t "
            "ON substr(replace(s.doc_socio,'.',''),1,8)=t.cnpj_basico WHERE s.ident='1'").fetchone()[0]
        meses = [r[0] for r in con.execute(
            "SELECT DISTINCT fonte_mes FROM socios_receita ORDER BY 1").fetchall() if r[0]]
    finally:
        con.close()
    return {
        "socios": n_socios, "raizes_com_qsa": n_raizes,
        "arestas_pj_pj": n_pj, "arestas_pj_pj_encadeaveis": n_encadeaveis,
        "snapshots": meses,
        "serie_temporal": len(meses) > 1,
        "nota": ("Um único snapshot significa que não há como observar SAÍDA de sócio. A série "
                 "temporal começa quando houver dois meses distintos em `fonte_mes`."),
    }
