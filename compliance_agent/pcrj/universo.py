"""O universo CONTRATUAL da despesa da Prefeitura do Rio — o denominador honesto.

POR QUE ISTO EXISTE
-------------------
`pcrj_despesa` soma **R$ 89,62 bilhões** pagos (2019–2023, 146 órgãos). Ranquear credor por
esse total ranqueia **folha e dívida**, não risco contratual: o maior credor do acervo é o Fundo
Especial de Previdência do Município (R$ 20,49 bi) e o segundo é o Banco do Brasil (R$ 12,49 bi).
Medido: **R$ 27,83 bi (31,1%) são modalidade 91** (intra-orçamentária) e **R$ 21,18 bi (23,6%)
são grupo 1** (Pessoal). É a doutrina já catalogada na casa: separar repasse ANTES de somar.

O CORTE, por extenso
--------------------
Código de natureza `NNNNNN`: 1=categoria · 2=**grupo** · 3-4=**modalidade de aplicação** ·
5-6=**elemento**.

Entra no universo contratual quem satisfaz TODAS as condições:

1. **grupo 3 (Outras Despesas Correntes) ou 4 (Investimentos)** — fora ficam pessoal (1), juros
   (2), inversões (5) e amortização (6);
2. **modalidade 90 (aplicação direta)** — fora ficam a intra-orçamentária (91, que é a Prefeitura
   pagando a si mesma) e as transferências a terceiros (50, 30, 20…), que são repasse, não compra;
3. **elemento fora da lista de não-contratação** — sentença judicial, indenização, tributo e
   benefício assistencial não nascem de licitação nem de contrato.

Resultado medido em 30/08/2026: **R$ 34.999.952.816,81** em 58.918 linhas e 8.930 credores antes
do filtro de elemento; ver `resumo()` para o número após o filtro.

O QUE ESTE CORTE **NÃO** FAZ
----------------------------
Não afirma que o excluído é legítimo. Sentença judicial paga a mais é achado — de outra lente.
Este módulo apenas impede que **folha, dívida e precatório disputem o topo de um ranking de risco
contratual**, onde sempre venceriam por tamanho.
"""
from __future__ import annotations

import sqlite3

DB = "data/compliance.db"

GRUPOS_CONTRATUAIS = ("3", "4")
MODALIDADE_DIRETA = "90"

# elemento → por que NÃO é contratação
ELEMENTOS_FORA: dict[str, str] = {
    "91": "sentenças judiciais — nasce de condenação, não de contrato",
    "93": "indenizações e restituições — reparação, não aquisição",
    "94": "indenização por demissão/incentivo à demissão",
    "95": "indenização pela execução de trabalhos de campo",
    "41": "contribuições — transferência corrente, não contraprestação",
    "43": "subvenções sociais",
    "45": "subvenções econômicas",
    "47": "obrigações tributárias e contributivas — tributo, não compra",
    "08": "outros benefícios assistenciais",
    "18": "auxílio financeiro a estudantes",
    "20": "auxílio financeiro a pesquisadores",
    "46": "auxílio-alimentação (benefício de pessoal)",
    "48": "outros auxílios financeiros a pessoa física",
    "49": "auxílio-transporte (benefício de pessoal)",
}

# elemento → rótulo, para leitura humana do que ficou DENTRO
ELEMENTOS_DENTRO: dict[str, str] = {
    "30": "material de consumo", "31": "premiações e material distribuído",
    "32": "material de distribuição gratuita", "33": "passagens e locomoção",
    "34": "outras despesas de pessoal (contratos de terceirização)",
    "35": "serviços de consultoria", "36": "serviços de terceiros — pessoa física",
    "37": "locação de mão de obra", "39": "serviços de terceiros — pessoa jurídica",
    "40": "serviços de tecnologia da informação", "51": "obras e instalações",
    "52": "equipamentos e material permanente", "61": "aquisição de imóveis",
    "63": "obras em andamento",
    "92": "despesas de exercícios anteriores (contratual, mas de outro exercício — ler com nota)",
}

_FILTRO_SQL = (
    "substr(natureza,2,1) IN ('3','4') AND substr(natureza,3,2)='90' "
    "AND substr(natureza,5,2) NOT IN (" + ",".join(f"'{e}'" for e in sorted(ELEMENTOS_FORA)) + ") "
    "AND pago > 0"
)


def filtro_sql(prefixo: str = "") -> str:
    """Cláusula WHERE do universo contratual. `prefixo` qualifica a tabela ('d.' etc.)."""
    return _FILTRO_SQL.replace("natureza", f"{prefixo}natureza").replace("pago", f"{prefixo}pago")


def conectar(db_path: str = DB) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def resumo(db_path: str = DB) -> dict:
    """Quanto sobra do bruto depois do corte — e quanto cada exclusão retirou."""
    con = conectar(db_path)
    try:
        bruto = con.execute("SELECT count(*), sum(pago), count(DISTINCT credor_documento) "
                            "FROM pcrj_despesa WHERE pago > 0").fetchone()
        contr = con.execute(f"SELECT count(*), sum(pago), count(DISTINCT credor_documento) "
                            f"FROM pcrj_despesa WHERE {filtro_sql()}").fetchone()
        fora_grupo = con.execute("SELECT sum(pago) FROM pcrj_despesa WHERE pago>0 "
                                 "AND substr(natureza,2,1) NOT IN ('3','4')").fetchone()[0] or 0
        fora_mod = con.execute("SELECT sum(pago) FROM pcrj_despesa WHERE pago>0 "
                               "AND substr(natureza,2,1) IN ('3','4') "
                               "AND substr(natureza,3,2)<>'90'").fetchone()[0] or 0
        marks = ",".join("?" for _ in ELEMENTOS_FORA)
        fora_elem = con.execute(
            f"SELECT sum(pago) FROM pcrj_despesa WHERE pago>0 "
            f"AND substr(natureza,2,1) IN ('3','4') AND substr(natureza,3,2)='90' "
            f"AND substr(natureza,5,2) IN ({marks})", tuple(sorted(ELEMENTOS_FORA))).fetchone()[0] or 0
    finally:
        con.close()
    return {
        "bruto": {"linhas": bruto[0], "pago": bruto[1] or 0.0, "credores": bruto[2]},
        "contratual": {"linhas": contr[0], "pago": contr[1] or 0.0, "credores": contr[2]},
        "excluido_por_grupo": fora_grupo,
        "excluido_por_modalidade": fora_mod,
        "excluido_por_elemento": fora_elem,
        "fracao_do_bruto": (contr[1] or 0) / (bruto[1] or 1),
    }


if __name__ == "__main__":
    from compliance_agent.reporting.intel_base import moeda
    r = resumo()
    print(f"bruto:      {r['bruto']['linhas']:>7,} linhas  R$ {moeda(r['bruto']['pago']):>20s}  "
          f"{r['bruto']['credores']:,} credores")
    print(f"contratual: {r['contratual']['linhas']:>7,} linhas  R$ {moeda(r['contratual']['pago']):>20s}  "
          f"{r['contratual']['credores']:,} credores   ({r['fracao_do_bruto']*100:.1f}% do bruto)")
    print(f"\nfora por grupo (pessoal/juros/dívida):  R$ {moeda(r['excluido_por_grupo'])}")
    print(f"fora por modalidade (intra/transferências): R$ {moeda(r['excluido_por_modalidade'])}")
    print(f"fora por elemento (sentença/tributo/benefício): R$ {moeda(r['excluido_por_elemento'])}")
