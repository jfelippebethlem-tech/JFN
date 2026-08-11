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


def peso_por_processo(con: sqlite3.Connection) -> dict[str, tuple[float, float]]:
    """`{processo: (valor em fornecedor, valor total)}` — uma varredura só da tabela de OB.

    Devolve os dois números, e não a razão, porque quem chama precisa de ambos: a fila usa a razão
    para rebaixar, e o painel publica os valores separados. Calcular duas vezes seria a segunda
    cópia que este módulo existe para evitar.
    """
    peso: dict[str, list[float]] = {}
    try:
        cur = con.execute("SELECT processo, credor, SUM(valor) FROM ob_orcamentaria_siafe "
                          "WHERE COALESCE(processo,'') <> '' GROUP BY 1, 2")
    except sqlite3.Error:
        return {}
    for proc, cred, v in cur:
        a = peso.setdefault(str(proc), [0.0, 0.0])
        val = float(v or 0)
        a[1] += val
        if eh_fornecedor(cred):
            a[0] += val
    return {p: (f, t) for p, (f, t) in peso.items()}


def processos_de_folha(con: sqlite3.Connection) -> set[str]:
    """Processos cujo dinheiro é majoritariamente folha/previdência (credor genérico)."""
    return {p for p, (forn, tot) in peso_por_processo(con).items()
            if tot > 0 and forn / tot < LIMIAR_FORNECEDOR}
