# -*- coding: utf-8 -*-
"""As esferas sao ESTANQUES, e ha UM classificador — nao quatro.

Pedido do dono: separar direito o que e do Governo do Estado do RJ, o que e da
Prefeitura do Rio e o que e de outros orgaos federais OU MUNICIPAIS. O ultimo
balde nao existia: uma prefeitura que nao fosse a do Rio caia em "indefinido" ou
escorregava para "federal" pelo nome.

E ha o risco estrutural, que ja custou caro nesta casa: `limites_dispensa.py`
avisa no topo "NUNCA duplicar esta tabela em detector" e aconteceu de novo com
outra constante — duas copias do filtro "nao e ente publico" divergiram e puseram
MINISTERIO DA FAZENDA e INSS num relatorio de fracionamento. Classificador de
esfera copiado diverge do mesmo jeito, e a divergencia sai em produto publico.
Por isso o ultimo teste CONTA as copias.
"""

import re
from pathlib import Path

import pytest

from compliance_agent.pcrj.esfera import ESFERAS, classificar_esfera

RAIZ = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "nome,cnpj,esperado",
    [
        # ── Estado do RJ ────────────────────────────────────────────────────
        ("ESTADO DO RIO DE JANEIRO", "", "estadual-rj"),
        ("SECRETARIA DE ESTADO DE SAUDE", "", "estadual-rj"),
        ("", "42498600000171", "estadual-rj"),          # raiz guarda-chuva
        # o MP estadual tem "MINISTERIO" no nome e NAO pode virar federal
        ("MINISTERIO PUBLICO DO ESTADO DO RIO DE JANEIRO", "", "estadual-rj"),
        # ── Prefeitura do Rio ───────────────────────────────────────────────
        ("MUNICIPIO DO RIO DE JANEIRO", "", "municipal-rio"),
        ("PREFEITURA MUNICIPAL DO RIO DE JANEIRO", "", "municipal-rio"),
        ("", "42498733000148", "municipal-rio"),
        # ── OUTROS municipios: o balde que faltava ──────────────────────────
        ("MUNICIPIO DE NITEROI", "", "municipal-outro"),
        ("PREFEITURA MUNICIPAL DE DUQUE DE CAXIAS", "", "municipal-outro"),
        ("CAMARA MUNICIPAL DE PETROPOLIS", "", "municipal-outro"),
        ("MUNICIPIO DE SAO GONCALO", "", "municipal-outro"),
        # ── Federal ─────────────────────────────────────────────────────────
        ("MINISTERIO DA FAZENDA", "", "federal"),
        ("UNIVERSIDADE FEDERAL DO RIO DE JANEIRO", "", "federal"),
        ("CAIXA ECONOMICA FEDERAL", "", "federal"),
        # ── Indefinido: nunca chutar ────────────────────────────────────────
        ("EMPRESA QUALQUER LTDA", "", "indefinido"),
        ("", "", "indefinido"),
    ],
)
def test_classifica_cada_esfera(nome, cnpj, esperado):
    assert classificar_esfera(nome, cnpj) == esperado


def test_o_balde_de_outros_municipios_existe():
    assert "municipal-outro" in ESFERAS, (
        "sem `municipal-outro` uma prefeitura que nao seja a do Rio cai em "
        "indefinido ou escorrega para federal — foi o pedido explicito do dono"
    )


def test_municipio_do_rio_nunca_cai_em_outros():
    """A fronteira que mais importa: o Rio nao pode vazar para o balde generico."""
    for nome in (
        "MUNICIPIO DO RIO DE JANEIRO",
        "PREFEITURA MUNICIPAL DO RIO DE JANEIRO",
        "CAMARA MUNICIPAL DO RIO DE JANEIRO",
    ):
        assert classificar_esfera(nome) == "municipal-rio", nome


def test_indefinido_nunca_vira_estadual_por_omissao():
    """INDISPONIVEL != estadual. Orgao sem sinal fica indefinido, e o produto diz."""
    for nome in ("", "XPTO", "ORGAO NAO IDENTIFICADO", "---"):
        assert classificar_esfera(nome) == "indefinido", nome


def test_existe_UM_classificador_de_esfera():
    """Conta as copias. Classificador duplicado diverge, e a divergencia e publica.

    E o mesmo guarda-corpo de `test_fracionamento_ente_publico.py`, pela mesma
    razao: ali duas copias do filtro "nao e ente publico" divergiram e puseram
    MINISTERIO DA FAZENDA e INSS num relatorio de fracionamento.
    """
    canonico = RAIZ / "compliance_agent" / "pcrj" / "esfera.py"
    # ISENTO, com motivo: `collectors/pncp_resultados.py` NAO e copia. Tem outra
    # assinatura e, sobretudo, outra FONTE — usa o `esferaId` oficial do ente no
    # PNCP, que e sinal mais forte que casar nome, e ja trata "demais municipios"
    # com um bug documentado e corrigido (municipio vazio != Rio). Fundir as duas
    # destruiria a melhor. O que as une nao e o codigo: sao os BALDES, e disso
    # cuida `test_baldes_batem_entre_os_dois_classificadores`.
    isentos = {RAIZ / "compliance_agent" / "collectors" / "pncp_resultados.py"}
    padrao = re.compile(r"^\s*def\s+_?classificar_esfera\s*\(", re.M)
    copias = []
    for py in (RAIZ / "compliance_agent").rglob("*.py"):
        if py == canonico or py in isentos or "_arquivo" in py.parts:
            continue
        if padrao.search(py.read_text(encoding="utf-8", errors="ignore")):
            copias.append(str(py.relative_to(RAIZ)))
    assert not copias, (
        "classificador de esfera duplicado fora de compliance_agent/pcrj/esfera.py: "
        + ", ".join(copias)
        + " — importe o canonico em vez de recriar"
    )


def test_baldes_batem_entre_os_dois_classificadores():
    """Os dois classificadores podem ter codigo diferente; os BALDES nao.

    O do PNCP fala 'estado'/'prefeitura'/'municipios'/'federal'/'outros' porque
    nasceu da nomenclatura do PNCP. O canonico fala 'estadual-rj'/'municipal-rio'/
    'municipal-outro'/'federal'/'indefinido'. O que nao pode e um ter um conceito
    que o outro nao tem — foi assim que 'demais municipios' existia num e nao no
    outro, e uma prefeitura de fora virava 'indefinido' de um lado e 'municipios'
    do outro no mesmo acervo.
    """
    from compliance_agent.pcrj.esfera import ESFERAS as CANON

    equivalencia = {
        "estado": "estadual-rj",
        "prefeitura": "municipal-rio",
        "municipios": "municipal-outro",
        "federal": "federal",
        "outros": "indefinido",
    }
    faltando = [v for v in equivalencia.values() if v not in CANON]
    assert not faltando, (
        "conceito que existe no classificador do PNCP e nao no canonico: "
        + ", ".join(faltando)
    )
