# -*- coding: utf-8 -*-
"""requisicao — minuta de requisição de informação, por órgão, pronta para o gabinete assinar.

POR QUE ESTE MÓDULO EXISTE. A varredura produziu duas listas que não viram nada sozinhas:
processos sob **restrição de acesso** (o marcador de cadeado, validado por correlação — 22,42%
dos caches sem documentos contra 0,02% dos caches com documentos, mil vezes de diferença) e
processos **conhecidos e nunca capturados**. Lista em banco não abre processo; ofício abre.

O QUE A MINUTA É, E O QUE ELA NÃO É:

  · É um PEDIDO. Requisição de informação não acusa, não qualifica conduta e não antecipa
    juízo — vigora a presunção de legitimidade dos atos administrativos. Há teste travando a
    ausência de qualquer palavra de juízo no texto gerado.
  · Pede DUAS coisas por órgão: a íntegra dos processos restritos **com o fundamento legal da
    restrição** (porque restringir acesso é ato administrativo e ato administrativo se
    motiva), e a íntegra dos processos que não foram localizados.
  · Valor pago só aparece quando existe. `total_pago` está preenchido em pouquíssimos casos —
    nos demais a minuta escreve "não informado", NUNCA R$ 0,00. Zero afirmaria que não houve
    pagamento, o que é coisa diferente de não termos o dado.

FUNDAMENTO: art. 5º, XXXIII da Constituição (direito de acesso), Lei 12.527/2011 (LAI) art. 7º
e art. 24 §1º (prazo), Lei 14.133/2021 art. 169 §3º II (dever de prestar informação ao controle)
e a competência fiscalizatória do art. 70 e 71 c/c art. 75 da Constituição.
"""
from __future__ import annotations

import sqlite3
from datetime import date

# Nenhuma palavra de juízo entra no texto. A lista existe para o teste poder travá-la.
PALAVRAS_VEDADAS = ("irregular", "ilegal", "fraude", "improbidade", "desvio", "superfatur",
                    "dolo", "má-fé", "crime", "culpado", "responsabiliza")

_FUNDAMENTO = (
    "art. 5º, XXXIII, da Constituição da República; art. 7º e art. 24, § 1º, da Lei "
    "12.527/2011; art. 169, § 3º, II, da Lei 14.133/2021; e art. 70 e 71, c/c art. 75, da "
    "Constituição da República"
)

# Órgão = os 6 primeiros dígitos do número SEI. É a granularidade em que o ofício é endereçado.
_NOMES_ORGAO = {
    "030001": "Secretaria de Estado de Educação",
    "040009": "Secretaria de Estado de Fazenda",
    "070002": "Secretaria de Estado de Saúde",
    "080001": "Secretaria de Estado de Infraestrutura e Obras",
    "080002": "Secretaria de Estado de Infraestrutura e Obras",
    "210001": "Secretaria de Estado de Polícia Militar",
    "260006": "Secretaria de Estado de Administração Penitenciária",
    "260007": "Secretaria de Estado de Administração Penitenciária",
    "270006": "Secretaria de Estado de Ciência e Tecnologia",
    "420001": "Secretaria de Estado de Governo",
    "490001": "Secretaria de Estado de Desenvolvimento Social",
}


def _orgao(numero_sei: str) -> str:
    d = "".join(c for c in str(numero_sei or "") if c.isdigit())
    return d[:6] if len(d) >= 6 else ""


def nome_orgao(codigo: str) -> str:
    """Nome quando conhecido; o código quando não. Nunca inventa denominação de órgão."""
    return _NOMES_ORGAO.get(codigo, f"Unidade {codigo}")


def _moeda(v) -> str:
    """R$ com separador de milhar. `None`/0 vira 'não informado' — nunca R$ 0,00."""
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        return "não informado"
    if f <= 0:
        return "não informado"
    return "R$ " + f"{f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def minutas(con: sqlite3.Connection, *, limite_por_orgao: int = 60) -> list[dict]:
    """Uma minuta por órgão, com os processos restritos e os não localizados."""
    por_orgao: dict[str, dict] = {}

    def _slot(cod: str) -> dict:
        return por_orgao.setdefault(cod, {"orgao": cod, "nome": nome_orgao(cod),
                                          "restritos": [], "fila": []})

    try:
        for r in con.execute(
            "SELECT numero_sei, n_docs_restritos, n_docs FROM sei_sigilo "
            "WHERE COALESCE(cadeado,0) = 1 ORDER BY numero_sei"
        ):
            cod = _orgao(r[0])
            if cod:
                _slot(cod)["restritos"].append(
                    {"numero": r[0], "n_docs_restritos": r[1], "n_docs": r[2]})
    except sqlite3.OperationalError:
        pass

    try:
        for r in con.execute(
            "SELECT numero_sei, motivo, total_pago FROM sei_fila_captura "
            "ORDER BY COALESCE(total_pago,0) DESC, numero_sei"
        ):
            cod = _orgao(r[0])
            if cod:
                _slot(cod)["fila"].append(
                    {"numero": r[0], "motivo": r[1], "total_pago": r[2]})
    except sqlite3.OperationalError:
        pass

    saida = []
    for m in por_orgao.values():
        m["restritos"] = m["restritos"][:limite_por_orgao]
        m["fila"] = m["fila"][:limite_por_orgao]
        m["n_restritos"] = len(m["restritos"])
        m["n_fila"] = len(m["fila"])
        if m["n_restritos"] or m["n_fila"]:
            saida.append(m)
    return sorted(saida, key=lambda x: -(x["n_restritos"] + x["n_fila"]))


def markdown(minuta: dict, *, data: str | None = None) -> str:
    """A minuta em Markdown, no padrão de entregável da casa."""
    hoje = data or date.today().strftime("%d/%m/%Y")
    L = [
        f"# Requisição de Informação — {minuta['nome']}",
        "",
        f"**Unidade:** {minuta['nome']} (código {minuta['orgao']})  ",
        f"**Data:** {hoje}  ",
        "**Assunto:** Solicitação de acesso à íntegra de processos administrativos",
        "",
        "---",
        "",
        "## 1. Fundamento",
        "",
        f"A presente solicitação tem fundamento no {_FUNDAMENTO}.",
        "",
        "## 2. Do pedido",
        "",
        "Solicita-se a essa unidade, no prazo legal:",
        "",
    ]

    n = 0
    if minuta["restritos"]:
        n += 1
        L += [
            f"**{n}.** A íntegra dos processos administrativos relacionados no **Anexo I**, que "
            "se apresentam com acesso restrito na consulta pública, **acompanhada da indicação "
            "do fundamento legal da restrição** de cada um, com menção ao dispositivo e ao ato "
            "que a determinou.",
            "",
        ]
    if minuta["fila"]:
        n += 1
        L += [
            f"**{n}.** A íntegra dos processos administrativos relacionados no **Anexo II**, "
            "não localizados na consulta pública, ou, alternativamente, a informação de que não "
            "existem sob essa numeração nessa unidade.",
            "",
        ]

    L += [
        "## 3. Observações",
        "",
        "A presente solicitação tem caráter exclusivamente informativo e instrutório. Não "
        "veicula juízo sobre os atos praticados, aos quais se aplica a presunção de "
        "legitimidade, nem antecipa conclusão de qualquer natureza.",
        "",
    ]

    if minuta["restritos"]:
        L += ["---", "", f"## Anexo I — Processos com acesso restrito "
              f"({minuta['n_restritos']})", "",
              "| # | Processo | Documentos | Documentos restritos |", "|---:|---|---:|---:|"]
        for i, p in enumerate(minuta["restritos"], 1):
            L.append(f"| {i} | {p['numero']} | {p.get('n_docs') or '—'} | "
                     f"{p.get('n_docs_restritos') or '—'} |")
        L.append("")

    if minuta["fila"]:
        L += ["---", "", f"## Anexo II — Processos não localizados ({minuta['n_fila']})", "",
              "| # | Processo | Valor pago identificado |", "|---:|---|---:|"]
        for i, p in enumerate(minuta["fila"], 1):
            L.append(f"| {i} | {p['numero']} | {_moeda(p.get('total_pago'))} |")
        L += ["",
              "> O valor indicado corresponde a pagamentos identificados em Ordens Bancárias. "
              "Onde consta *não informado*, o dado não foi localizado — o que é distinto de "
              "inexistência de pagamento.",
              ""]

    return "\n".join(L)
