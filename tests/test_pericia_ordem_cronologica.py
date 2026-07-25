"""As OB da pericia saem em ordem CRONOLOGICA de verdade.

`ob_orcamentaria_siafe.data_emissao` e TEXTO no formato DD/MM/AAAA. Um `ORDER BY
data_emissao` cru ordena por **dia do mes**: 01/10/2024 vem antes de 16/12/2022. A ordem
errada nao para nada — ela sai calada no parecer, e `_obs_de` alimenta
`periciar` -> `lex._analise` -> `lex_render.parecer_md`/`render_pdf`, ou seja, chega no PDF
que vai para fora.

O resto do projeto ja resolvia isso com a expressao ISO (`_OB_ISO` em `retro_auditoria.py`
e `cruzamentos_intel.py`); a pericia era o sitio que tinha ficado de fora.
"""
import sqlite3

from compliance_agent.pericia_sweep import _obs_de

CNPJ, UG = "11111111000199", "296100"

# de proposito fora de ordem, e escolhidas para que ordenar por texto DE ERRADO:
# por dia do mes, 01/10/2024 viria primeiro e 16/12/2022 por ultimo.
LINHAS = [
    ("2024OB01", "01/10/2024"),
    ("2022OB01", "16/12/2022"),
    ("2023OB01", "27/11/2023"),
    ("2025OB01", "03/07/2025"),
    ("2023OB02", "07/12/2023"),
]


def _banco() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE ob_orcamentaria_siafe(
        numero_ob TEXT, status TEXT, nl TEXT, re TEXT, pd TEXT, valor REAL,
        competencia TEXT, data_emissao TEXT, processo TEXT, nome_credor TEXT,
        credor TEXT, ug_emitente TEXT)""")
    c.executemany(
        "INSERT INTO ob_orcamentaria_siafe VALUES (?,'PAGO','','','',1000.0,'',?,'','ACME',?,?)",
        [(ob, dt, CNPJ, UG) for ob, dt in LINHAS],
    )
    return c


def _iso(br: str) -> str:
    d, m, a = br.split("/")
    return f"{a}-{m}-{d}"


def test_obs_saem_em_ordem_cronologica():
    obs = _obs_de(_banco(), CNPJ, UG)
    datas = [o["data_emissao"] for o in obs]
    assert datas == sorted(datas, key=_iso), (
        "as OB nao sairam em ordem cronologica — ORDER BY em DD/MM/AAAA ordena por dia do "
        f"mes. Saiu: {datas}"
    )
    assert datas[0] == "16/12/2022", f"a mais antiga deveria vir primeiro, veio {datas[0]}"
    assert datas[-1] == "03/07/2025", f"a mais recente deveria vir por ultimo, veio {datas[-1]}"


def test_desempate_por_numero_da_ob_na_mesma_data():
    """Duas OB no MESMO dia continuam desempatando pelo numero, como antes."""
    c = _banco()
    c.executemany(
        "INSERT INTO ob_orcamentaria_siafe VALUES (?,'PAGO','','','',1.0,'','16/12/2022','','ACME',?,?)",
        [("2022OB09", CNPJ, UG), ("2022OB00", CNPJ, UG)],
    )
    obs = [o for o in _obs_de(c, CNPJ, UG) if o["data_emissao"] == "16/12/2022"]
    assert [o["numero_ob"] for o in obs] == ["2022OB00", "2022OB01", "2022OB09"]
