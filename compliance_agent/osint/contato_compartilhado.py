# -*- coding: utf-8 -*-
"""Telefone e e-mail compartilhados — duas arestas fortes que o grafo nunca teve (item I.1.2).

O QUE ESTAVA PARADO. A régua de vínculos declara `mesmo_telefone` (força 0,70) e `mesmo_email`
(0,80) desde que existe — bem acima de `mesmo_predio` (0,05) e na faixa de `mesma_sala` (0,75). Nunca
foram usadas, porque a base não tinha o campo. E tinha: `data/receita_estab.db` guarda **6.171.766
estabelecimentos** com `telefone1`, `telefone2` e `correio_eletronico` — 83,9% com telefone e 69,0%
com e-mail —, e os índices `idx_estab_telefone1` e `idx_estab_correio_eletronico` já existiam.
Dado ingerido, indexado, e sem um único consumidor.

OS GUARDAS, TODOS MEDIDOS ANTES DE ESCRITOS. Sem eles esta aresta seria pior que a de prédio:

  · **Telefone-lixo.** Os cinco telefones mais compartilhados do país são `00` (129.152 empresas),
    `210` (28.628), `2122222222` (21.238), `2199999999` (13.234) e um 0800. São preenchimentos, não
    vínculos.
  · **Fan-out.** 43 telefones ligam mais de mil empresas cada; 1.565 ligam de 101 a 1.000. A faixa
    em que o compartilhamento significa algo é a de poucas empresas: 345.782 telefones ligam
    exatamente duas, e 100.242 ligam de três a cinco.
  · **E-mail de prestador de serviço.** Os cinco e-mails mais compartilhados são todos de
    contabilidade e abertura de empresa: `abertura@maismei.com.br` (17.665),
    `meucnpj@contabilizei.com.br` (16.846), `ol-documentacao-societario@btgpactual.com` (7.663),
    `rsbcontabilidadeeacessoria@gmail.com` (3.630), `controladoria@xpi.com.br` (3.452). É
    exatamente a explicação inocente que a régua já registra em `mesmo_contador` (0,30) — e por isso
    e-mail acima do teto de fan-out NÃO vira `mesmo_email`: vira `mesmo_contador`, com força menor,
    ou é descartado.

A DIFERENÇA ENTRE ESTE MÓDULO E UM `GROUP BY`. O `GROUP BY` cru daria centenas de milhares de
"vínculos" e afogaria o fiscal — o mesmo defeito do co-endereço por prédio, que sobrepesava 76% das
arestas em 15×. Aqui o corte é por medição, e o que fica fora sai declarado.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from compliance_agent.osint.vinculos import TIPOS_ARESTA

__all__ = [
    "TETO_FANOUT", "TETO_FANOUT_EMAIL", "telefone_valido", "normalizar_telefone",
    "dominio_de", "vinculos_por_contato", "cobertura",
]

_ESTAB = Path(__file__).resolve().parent.parent.parent / "data" / "receita_estab.db"

# Acima disto o contato é de PRESTADOR DE SERVIÇO, não elo entre as empresas. Medido: 345.782
# telefones ligam exatamente 2 empresas e 100.242 ligam de 3 a 5 — é essa a faixa com sentido.
TETO_FANOUT = 5
# E-mail tolera um pouco mais (grupo econômico real usa um domínio só), mas menos que o contador
# médio: os campeões de compartilhamento são escritórios de contabilidade com milhares de clientes.
TETO_FANOUT_EMAIL = 8

# Telefones de preenchimento — os cinco campeões nacionais e o padrão que os gera.
_TEL_LIXO_EXATO = {"00", "0", "210", "2100", "000000000", "0000000000", "00000000000"}
_RE_TEL_REPETIDO = re.compile(r"^(\d)\1+$")           # 2222222222, 9999999999
_RE_TEL_SEQUENCIA = re.compile(r"^(?:2[12])?(\d)\1{7,}$")
_RE_DIG = re.compile(r"\D")

# Domínios de serviço: e-mail neste domínio nunca é elo entre as empresas que o usam.
DOMINIOS_DE_SERVICO = (
    "maismei.com.br", "contabilizei.com.br", "btgpactual.com", "xpi.com.br",
    "contabilidade", "contabil", "escritorio", "assessoria", "abrirempresa",
)


def normalizar_telefone(v: Any) -> str:
    return _RE_DIG.sub("", str(v or ""))


def telefone_valido(v: Any) -> bool:
    """Descarta preenchimento. `00`, `210` e `2199999999` ligam dezenas de milhares de empresas."""
    d = normalizar_telefone(v)
    if len(d) < 8 or d in _TEL_LIXO_EXATO:
        return False
    if _RE_TEL_REPETIDO.match(d) or _RE_TEL_SEQUENCIA.match(d):
        return False
    # 2122222222 / 2199999999: DDD válido seguido de um dígito repetido
    if len(d) >= 10 and _RE_TEL_REPETIDO.match(d[2:]):
        return False
    return True


def dominio_de(email: Any) -> str:
    e = str(email or "").strip().lower()
    return e.rsplit("@", 1)[-1] if "@" in e else ""


def _de_servico(email: Any) -> bool:
    dom = dominio_de(email)
    return bool(dom) and any(s in dom for s in DOMINIOS_DE_SERVICO)


def _tipo_email(n_empresas: int, email: str) -> tuple[str, str] | None:
    """`(tipo_de_aresta, observação)` para um e-mail compartilhado, ou `None` para descartar."""
    if _de_servico(email):
        return ("mesmo_contador",
                f"domínio de prestador de serviço ({dominio_de(email)}) — não liga as empresas "
                "entre si; a própria régua registra isso como explicação inocente")
    if n_empresas > TETO_FANOUT_EMAIL:
        return ("mesmo_contador",
                f"e-mail compartilhado por {n_empresas} empresas — acima de {TETO_FANOUT_EMAIL} o "
                "padrão é escritório de contabilidade, não grupo")
    return ("mesmo_email", "")


def _por_raiz(cnpjs: list[str]) -> list[str]:
    """Um representante por RAIZ, matriz primeiro. Filial não é outra empresa.

    O filtro `substr(cnpj,1,8)<>?` já tirava as filiais do PRÓPRIO alvo, mas as do DESTINO
    contavam uma a uma — e isso errava dos dois lados. Medido em 2026-08-06 sobre os 120 CNPJs
    vencedores do acervo: das 252 arestas, **65 eram 21 pares de raiz repetidos por filial** — a
    APPA SERVIÇOS TEMPORÁRIOS e a OBJETIVA SERVIÇOS TERCEIRIZADOS dividem o telefone 1147593220 e
    apareciam 3× porque a OBJETIVA tem 3 filiais com o mesmo número. A aresta é UMA.

    E o erro simétrico é pior: um telefone compartilhado com 6 filiais de UMA empresa media
    fan-out 7 e era **descartado** como contato de prestador, quando é exatamente o vínculo que
    se procura. Contar por raiz corrige a inflação e recupera o falso negativo.
    """
    vistas: dict[str, str] = {}
    for c in cnpjs:
        raiz = c[:8]
        atual = vistas.get(raiz)
        if atual is None or (c[8:12] == "0001" and atual[8:12] != "0001"):
            vistas[raiz] = c
    return list(vistas.values())


def vinculos_por_contato(cnpjs: list[str] | tuple[str, ...], *, db_estab: str = "") -> dict:
    """Arestas de telefone e e-mail entre os CNPJs pedidos e QUALQUER empresa do país.

    Devolve `{arestas, descartados, cobertura}`. `descartados` é contado por motivo — contato
    descartado em silêncio é a diferença entre "não há vínculo" e "não olhamos".
    """
    caminho = db_estab or str(_ESTAB)
    out: dict[str, Any] = {
        "arestas": [], "descartados": {"telefone_invalido": 0, "fanout_telefone": 0,
                                       "email_de_servico": 0, "fanout_email": 0},
        "cobertura": {"pedidos": len(cnpjs), "com_registro": 0, "com_telefone": 0,
                      "com_email": 0, "sem_registro": 0},
    }
    if not cnpjs or not Path(caminho).exists():
        out["erro"] = f"base de estabelecimentos ausente ({caminho})"
        return out

    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        limpos = [_RE_DIG.sub("", str(c or "")) for c in cnpjs]
        limpos = [c for c in limpos if len(c) == 14]
        ph = ",".join("?" * len(limpos))
        linhas = con.execute(
            f"SELECT cnpj, telefone1, telefone2, correio_eletronico FROM estabelecimentos "
            f"WHERE cnpj IN ({ph})", limpos).fetchall()
        out["cobertura"]["com_registro"] = len(linhas)
        out["cobertura"]["sem_registro"] = len(limpos) - len(linhas)

        for ln in linhas:
            alvo = ln["cnpj"]
            # MESMO NÚMERO NOS DOIS CAMPOS. Empresa que cadastra o telefone em `telefone1` e
            # `telefone2` gerava a aresta DUAS vezes — foi o único par ainda repetido depois da
            # agregação por raiz (11389387 × 11412771, telefone 2227851280).
            ja_vistos: set[str] = set()
            for campo in ("telefone1", "telefone2"):
                tel = normalizar_telefone(ln[campo])
                if not tel or tel in ja_vistos:
                    continue
                ja_vistos.add(tel)
                if not telefone_valido(tel):
                    out["descartados"]["telefone_invalido"] += 1
                    continue
                if campo == "telefone1":
                    out["cobertura"]["com_telefone"] += 1
                # `cnpj<>?` não basta: matriz e filial da MESMA empresa dividem telefone por
                # definição, e isso não é vínculo entre empresas — é a mesma empresa. Filtrar pela
                # raiz de 8 dígitos. (Apareceu na primeira amostra real: 00028682000140 ×
                # 00028682000655, e duas agências do Banco do Brasil pelo e-mail do webmaster.)
                pares = [r[0] for r in con.execute(
                    "SELECT cnpj FROM estabelecimentos WHERE telefone1=? AND substr(cnpj,1,8)<>?",
                    (ln[campo], alvo[:8])).fetchall()]
                pares = _por_raiz(pares)
                if not pares:
                    continue
                if len(pares) + 1 > TETO_FANOUT:
                    out["descartados"]["fanout_telefone"] += 1
                    continue
                t = TIPOS_ARESTA["mesmo_telefone"]
                for p in pares:
                    out["arestas"].append({
                        "de": alvo, "para": p, "tipo": t.id, "forca": t.forca,
                        "detalhe": f"telefone {tel}", "n_no_grupo": len(pares) + 1,
                        "explicacao_inocente": t.exculpatoria,
                        "fonte": "Receita Federal — dados abertos CNPJ (Estabelecimentos)",
                    })

            email = (ln["correio_eletronico"] or "").strip().lower()
            if not email or "@" not in email:
                continue
            out["cobertura"]["com_email"] += 1
            pares = [r[0] for r in con.execute(
                "SELECT cnpj FROM estabelecimentos WHERE lower(correio_eletronico)=? "
                "AND substr(cnpj,1,8)<>?", (email, alvo[:8])).fetchall()]
            pares = _por_raiz(pares)
            if not pares:
                continue
            classificado = _tipo_email(len(pares) + 1, email)
            if classificado is None:
                continue
            tipo, obs = classificado
            if tipo == "mesmo_contador":
                out["descartados"]["email_de_servico" if _de_servico(email) else "fanout_email"] += 1
                if len(pares) + 1 > TETO_FANOUT_EMAIL * 4:
                    continue     # milhares de clientes: não é elo, é cadastro de contador
            t = TIPOS_ARESTA[tipo]
            for p in pares[:TETO_FANOUT_EMAIL * 4]:
                out["arestas"].append({
                    "de": alvo, "para": p, "tipo": t.id, "forca": t.forca,
                    "detalhe": f"e-mail {email}", "n_no_grupo": len(pares) + 1,
                    "explicacao_inocente": obs or t.exculpatoria,
                    "fonte": "Receita Federal — dados abertos CNPJ (Estabelecimentos)",
                })
    finally:
        con.close()

    c = out["cobertura"]
    c["nota"] = (
        f"{c['com_registro']} de {c['pedidos']} CNPJ com registro no dump de estabelecimentos; "
        f"{c['sem_registro']} sem. Empresa sem contato publicado NÃO é empresa sem telefone — a "
        "Receita traz o campo em 83,9% dos estabelecimentos, e a ausência é lacuna de fonte."
    )
    out["regua"] = {
        "mesmo_telefone": TIPOS_ARESTA["mesmo_telefone"].forca,
        "mesmo_email": TIPOS_ARESTA["mesmo_email"].forca,
        "mesmo_contador": TIPOS_ARESTA["mesmo_contador"].forca,
        "teto_fanout_telefone": TETO_FANOUT,
        "teto_fanout_email": TETO_FANOUT_EMAIL,
        "por_que": ("43 telefones do país ligam mais de mil empresas cada e os cinco e-mails mais "
                    "compartilhados são de contabilidade. Sem teto de fan-out esta aresta afogaria "
                    "o fiscal, como o co-endereço por prédio já fez."),
    }
    return out


def cobertura(db_estab: str = "") -> dict:
    """Quanto do dump traz contato — o denominador que impede ler silêncio como ausência."""
    caminho = db_estab or str(_ESTAB)
    if not Path(caminho).exists():
        return {"ok": False, "erro": f"base ausente ({caminho})"}
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM estabelecimentos").fetchone()[0] or 1
        tel = con.execute("SELECT COUNT(*) FROM estabelecimentos "
                          "WHERE COALESCE(telefone1,'')<>''").fetchone()[0]
        email = con.execute("SELECT COUNT(*) FROM estabelecimentos "
                            "WHERE COALESCE(correio_eletronico,'')<>''").fetchone()[0]
    finally:
        con.close()
    return {"ok": True, "estabelecimentos": n,
            "com_telefone": tel, "pct_telefone": round(100.0 * tel / n, 1),
            "com_email": email, "pct_email": round(100.0 * email / n, 1)}
