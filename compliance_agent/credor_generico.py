# -*- coding: utf-8 -*-
"""FONTE ÚNICA de quem, no SIAFE, é FORNECEDOR — e quem é folha/previdência.

POR QUE EXISTE. O campo `credor` da OB orçamentária nem sempre traz CNPJ ou CPF. Boa parte do
dinheiro sai para credor GENÉRICO, que é rubrica e não empresa:

    CG0004700   FOLHA DE PAGAMENTOS                     R$ 49,34 bi no acervo
    CG0006026   RIOPREV/INATIVOS                        R$  7,60 bi
    123400      FUNDO ÚNICO DE PREVIDÊNCIA DO ERJ       R$  4,95 bi
    123499      FUNDO DO PLANO PREVIDENCIÁRIO DO ERJ
    294200      FUNDAÇÃO SAÚDE DO ESTADO DO RJ          (órgão, não fornecedor)

Confundir os dois estraga duas coisas ao mesmo tempo, e as duas foram medidas em 2026-08-11:

1. **PRIORIZAÇÃO.** A fila do `sei_sweep` ordena por valor. No estrato onde ele passa a vida,
   **30 das 50 primeiras vagas** iam para folha — browser, que é o recurso mais escasso da casa,
   gasto no que os detectores de licitação e contrato nem examinam.
2. **MANCHETE.** Os "R$ 9,90 bi atrás dos processos ilegíveis" eram, na verdade, R$ 3,73 bi de
   pagamento a CNPJ/CPF e R$ 6,17 bi (62%) de folha e previdência. Publicar o total como exposição
   fiscalizável é superestimar — a mesma família dos quatro números de manchete já corrigidos.

O CORTE É POR PESO DO DINHEIRO, NÃO POR PRESENÇA. Consignação ao lado do pagamento não
descaracteriza o processo do fornecedor; por isso `>50%` do valor, e não "tem algum credor
genérico". Sem OB conhecida, o processo NÃO é folha: na dúvida ele segue como fornecedor, porque
rebaixar por ausência de dado esconderia trabalho.

O QUE ESTE MÓDULO **NÃO** DIZ. Que folha não tem irregularidade — tem, e a casa já faz perícia de
benefício × vínculo. Diz apenas que ela não é pagamento a fornecedor, e portanto não pode ocupar
a fila nem a manchete de quem persegue contrato e licitação.
"""
from __future__ import annotations

import re
import sqlite3

# Peso mínimo do dinheiro em CNPJ/CPF para o processo contar como de fornecedor.
LIMIAR_FORNECEDOR = 0.5


def eh_fornecedor(credor: str | None) -> bool:
    """CNPJ (14) ou CPF (11) = fornecedor. Pessoa física contratada também é fornecedor; o que
    descaracteriza é a rubrica genérica (`CG*`, código de fundo), que não tem documento nenhum."""
    return len(re.sub(r"\D", "", str(credor or ""))) in (11, 14)


def _cnpjs_publicos(con: sqlite3.Connection) -> set[str]:
    """Raízes de CNPJ com natureza jurídica `1xx` — administração pública.

    O ÓRGÃO TAMBÉM OCUPA O CAMPO `credor`, e este é o caso que o teste de documento deixa passar,
    porque ele TEM CNPJ. Medido na fila de processos ilegíveis (2026-08-11): R$ 601 mi do que
    parecia fornecedor era FUNDO MUNICIPAL DE SAÚDE (RJ, São Gonçalo, Volta Redonda, Bom Jesus do
    Itabapoana) e MINISTÉRIO DA FAZENDA — repasse e tributo, não contratação.

    É a mesma família do vício já catalogado em que ITERJ, SEGOV e SECID figuravam como
    "vencedoras" das próprias contratações. E vale a mesma ressalva registrada lá: nem todo órgão
    está em `empresas_cadastro`. Por isso a ausência de cadastro NÃO rebaixa — é lacuna nossa, não
    prova de natureza.
    """
    try:
        return {str(r[0]) for r in con.execute(
            "SELECT cnpj_basico FROM empresas_cadastro WHERE natureza_cod LIKE '1%'")}
    except sqlite3.Error:
        return set()


def classificar_por_processo(con: sqlite3.Connection,
                             status: str | None = None) -> dict[str, dict[str, float]]:
    """`{processo: {fornecedor, publico, generico, total}}` — uma varredura só da tabela de OB.

    Três populações dividem o campo `credor`, e só a primeira é contratação:

        fornecedor   CNPJ/CPF privado — I.D.E.A.S, INSTITUTO D'OR, AGILE CORP
        publico      CNPJ de natureza 1xx — fundo municipal de saúde, Ministério da Fazenda
        generico     rubrica sem documento — FOLHA DE PAGAMENTOS, RIOPREV

    `status` filtra a OB (use `"Contabilizado"` para somar só o que foi de fato pago). Quem PUBLICA
    número tem de passá-lo: a casa já somou OB CANCELADA numa fila do fiscal. Quem só PRIORIZA pode
    deixar em branco — para ordenar, a OB cancelada não muda quem é fornecedor.
    """
    publicos = _cnpjs_publicos(con)
    fora: dict[str, dict[str, float]] = {}
    sql = ("SELECT processo, credor, SUM(valor) FROM ob_orcamentaria_siafe "
           "WHERE COALESCE(processo,'') <> ''")
    args: tuple = ()
    if status:
        sql += " AND status = ?"
        args = (status,)
    try:
        cur = con.execute(sql + " GROUP BY 1, 2", args)
    except sqlite3.Error:
        return {}
    for proc, cred, v in cur:
        d = re.sub(r"\D", "", str(cred or ""))
        val = float(v or 0)
        a = fora.setdefault(str(proc), {"fornecedor": 0.0, "publico": 0.0, "generico": 0.0,
                                        "total": 0.0})
        a["total"] += val
        if len(d) not in (11, 14):
            a["generico"] += val
        elif len(d) == 14 and d[:8] in publicos:
            a["publico"] += val
        else:
            a["fornecedor"] += val
    return fora


def peso_por_processo(con: sqlite3.Connection) -> dict[str, tuple[float, float]]:
    """`{processo: (valor em fornecedor, valor total)}` — uma varredura só da tabela de OB.

    Devolve os dois números, e não a razão, porque quem chama precisa de ambos: a fila usa a razão
    para rebaixar, e o painel publica os valores separados. Calcular duas vezes seria a segunda
    cópia que este módulo existe para evitar.
    """
    return {p: (c["fornecedor"], c["total"]) for p, c in classificar_por_processo(con).items()}


def processos_de_folha(con: sqlite3.Connection) -> set[str]:
    """Processos cujo dinheiro NÃO é majoritariamente contratação — folha, previdência ou repasse
    a ente público. O nome é histórico (a folha foi o caso que abriu a questão); o critério é
    "menos da metade do dinheiro foi para fornecedor"."""
    return {p for p, (forn, tot) in peso_por_processo(con).items()
            if tot > 0 and forn / tot < LIMIAR_FORNECEDOR}
