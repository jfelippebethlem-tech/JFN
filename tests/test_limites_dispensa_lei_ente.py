# -*- coding: utf-8 -*-
"""O4.5 — teto por LEI, ENTE e DATA DO FATO em `limites_dispensa`, com PARIDADE do caminho antigo.

Valores conferidos verbatim (ver o bloco "O4.5" em `compliance_agent/limites_dispensa.py`): D9412.htm (convite
330.000/176.000; vigência "trinta dias após a data de sua publicação", DOU 19.6.2018 → 19/07/2018); L8666cons.htm
art. 24 I/II e §1º; L14133.htm art. 75 I, II, §2º, §7º; Anexos de D10922/D11317/D11871/D12343/D12807 ("Art. 75, § 7º");
D12807 art. 3º (delegação ao MGI); L13303.htm art. 29 I/II e §3º; L14065.htm art. 1º I e art. 2º; L13979.htm art. 4º.
"""
from __future__ import annotations

import ast
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from compliance_agent import limites_dispensa as ld
from compliance_agent.limites_dispensa import (LIMITES, LIMITES_8666, TetoIndeterminado, limite_dispensa,
                                               limite_par7, teto_dispensa)

RAIZ = Path(__file__).resolve().parents[1]
D = date


# ── paridade: chamadas SEM os argumentos novos devolvem exatamente o de antes ───────────────────────────────────

def _legado(ano, tipo="compras", *, duplicado=False):
    """Cópia CONGELADA do corpo de `limite_dispensa` no HEAD 1b97df55 (antes da O4.5). Não editar."""
    ano = int(ano)
    if ano < min(LIMITES) and ano in LIMITES_8666:
        info = LIMITES_8666[ano]
    else:
        info = LIMITES.get(ano) or LIMITES[max(LIMITES)]
    return info[tipo] * 2 if duplicado else info[tipo]


def test_tabelas_antigas_intocadas():
    """LIMITES e LIMITES_8666 são as do HEAD 1b97df55 (hash). Mudar valor exige ✅ do dono, não a O4.5."""
    h = hashlib.sha256(json.dumps({"L": LIMITES, "L8": LIMITES_8666}, sort_keys=True,
                                  ensure_ascii=False).encode()).hexdigest()
    assert h == "b7ebb69557305fe4cd4f8acd7a40d1c35ad701b2475d85f123f2a719e5995367"


@pytest.mark.parametrize("ano", range(1990, 2036))
def test_paridade_ano_a_ano(ano):
    for tipo in ("compras", "obras"):
        for dup in (False, True):
            assert limite_dispensa(ano, tipo, duplicado=dup) == _legado(ano, tipo, duplicado=dup)
            if not dup:
                assert limite_dispensa(ano, tipo) == _legado(ano, tipo)
    assert limite_dispensa(ano) == _legado(ano)


_ALIASES = {"limite_dispensa", "_limite_do_ano", "_limite_dispensa", "_limite_da_fonte"}


def _chamadas_no_repo():
    """Toda chamada a `limite_dispensa` (ou alias de import) em compliance_agent/, tools/, rotas/ e server.py."""
    out = []
    arqs = list((RAIZ / "compliance_agent").rglob("*.py")) + list((RAIZ / "tools").rglob("*.py")) \
        + list((RAIZ / "rotas").rglob("*.py")) + [RAIZ / "server.py"]
    for arq in arqs:
        if not arq.exists() or arq.name == "limites_dispensa.py":
            continue
        try:
            arvore = ast.parse(arq.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for no in ast.walk(arvore):
            if isinstance(no, ast.Call):
                f = no.func
                nome = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                if nome in _ALIASES:
                    out.append((str(arq.relative_to(RAIZ)), no.lineno, [k.arg for k in no.keywords],
                                len(no.args)))
    return out


def test_todos_os_chamadores_atuais_usam_so_o_caminho_antigo():
    """Paridade 'sobre todos os chamadores': nenhum passa lei=/ente=/data_fato= (sombra) — logo, pelo teste
    ano a ano acima, todos recebem exatamente o valor de antes. Se algum passar a usar, é O4.8/O4.9 (⚖️ ✅)."""
    chamadas = _chamadas_no_repo()
    assert len(chamadas) >= 15, f"varredura achou poucas chamadas ({len(chamadas)}) — o AST parou de enxergar?"
    novos = [(a, l, k) for a, l, k, _ in chamadas if set(k) & {"lei", "ente", "data_fato"}]
    assert not novos, f"chamador já usa os argumentos em sombra: {novos}"
    estranhos = [(a, l, k) for a, l, k, n in chamadas if set(k) - {"duplicado"} or n > 2]
    assert not estranhos, f"assinatura de chamada fora do contrato antigo: {estranhos}"


# ── caminho novo: lei, ente, data do fato ───────────────────────────────────────────────────────────────────────

OURO = [
    # (kwargs de teto_dispensa, valor esperado ou None, estado, fonte)
    (dict(lei="14133", tipo="compras", ano=2026), 65492.11, "DETERMINADO", "D12807 Anexo art. 75 II"),
    (dict(lei="14133", tipo="obras", data_fato=D(2024, 5, 2)), 119812.02, "DETERMINADO", "D11871 Anexo art. 75 I"),
    (dict(lei="14133", tipo="veiculos", ano=2025), 125451.15, "DETERMINADO",
     "14.133 art. 75 I: '[...] ou de serviços de manutenção de veículos automotores' → teto de obras"),
    (dict(lei="14133", tipo="compras", ano=2026, ente="consorcio_publico"), 130984.22, "DETERMINADO",
     "14.133 art. 75 §2º: 'serão duplicados'"),
    (dict(lei="14133", tipo="compras", ano=2027), None, "INDETERMINADO", "D12807 art. 3º: atualização por ato do MGI"),
    (dict(lei="14133", tipo="compras", data_fato=D(2021, 3, 31)), None, "INDETERMINADO", "14.133 art. 194"),
    (dict(lei="14133", tipo="compras", ano=2026, ente="sociedade_economia_mista"), None, "INDETERMINADO",
     "14.133 art. 1º §1º: estatal não é regida pela 14.133"),
    (dict(lei="8666", tipo="compras", data_fato=D(2018, 7, 18)), 8000.00, "DETERMINADO",
     "D9412 vigora em 19/07/2018: antes, 10% de R$ 80.000 (red. 9.648/1998)"),
    (dict(lei="8666", tipo="compras", data_fato=D(2018, 7, 19)), 17600.00, "DETERMINADO",
     "D9412 art. 1º II a 'até R$ 176.000,00' × 10% (8.666 art. 24 II) — cálculo"),
    (dict(lei="8666", tipo="obras", data_fato=D(2022, 9, 1)), 33000.00, "DETERMINADO",
     "contrato 8.666 em 2022 (14.133 art. 191): D9412 330.000 × 10%"),
    (dict(lei="8666", tipo="compras", data_fato=D(2022, 9, 1), ente="empresa_publica"), 35200.00, "DETERMINADO",
     "8.666 art. 24 §1º: 'serão 20%'"),
    (dict(lei="8666", tipo="compras", ano=2018), None, "INDETERMINADO", "2018 partido pelo D9412 sem data do fato"),
    (dict(lei="8666", tipo="compras", data_fato=D(2024, 2, 1)), None, "INDETERMINADO",
     "14.133 art. 193 II: 8.666 revogada em 30/12/2023"),
    (dict(lei="8666", tipo="compras", data_fato=D(2020, 6, 1)), 50000.00, "DETERMINADO",
     "14.065 art. 1º I b 'R$ 50.000,00' + art. 2º (calamidade)"),
    (dict(lei="8666", tipo="obras", data_fato=D(2020, 3, 19)), 33000.00, "DETERMINADO",
     "14.065 art. 2º: DL 6 é de 20/03/2020 — antes dele, D9412"),
    (dict(lei="14065", tipo="obras", ano=2020), 100000.00, "DETERMINADO", "14.065 art. 1º I a"),
    (dict(lei="14065", tipo="obras", data_fato=D(2021, 2, 1)), None, "INDETERMINADO", "14.065 art. 2º"),
    (dict(lei="8666", tipo="compras", ano=2020), None, "INDETERMINADO", "2020 partido (calamidade) sem data do fato"),
    (dict(lei="13303", tipo="compras", ano=2025), None, "INDETERMINADO",
     "13.303 art. 29 §3º: conselho de cada estatal pode alterar"),
    (dict(lei="13979", tipo="compras", ano=2020), None, "SEM_TETO", "13.979 art. 4º não fixa valor"),
    (dict(lei=None, tipo="compras", ano=2026), None, "INDETERMINADO", "sem regime não há teto"),
]


@pytest.mark.parametrize("kw,valor,estado,fonte", OURO, ids=[f"{o[0].get('lei')}-{o[0].get('tipo')}-{i}"
                                                              for i, o in enumerate(OURO)])
def test_tabela_ouro_teto(kw, valor, estado, fonte):
    t = teto_dispensa(**kw)
    assert t.estado == estado, f"{fonte}: {t}"
    if valor is None:
        assert t.valor is None and t.motivo
    else:
        assert t.valor == pytest.approx(valor, abs=0.001), fonte
        assert t.ato


def test_13303_informa_o_valor_legal_sem_afirmar():
    t = teto_dispensa(lei="L13303", tipo="obras", ano=2024)
    assert t.valor is None and t.valor_legal_padrao == 100000.00 and t.inclusivo is True


def test_inclusivo_por_lei():
    """14.133: 'valores inferiores a'; 8.666/14.065/13.303: 'de valor até'."""
    assert teto_dispensa(lei="14133", ano=2026).inclusivo is False
    assert teto_dispensa(lei="8666", data_fato=D(2019, 1, 2)).inclusivo is True
    assert teto_dispensa(lei="14065", ano=2020).inclusivo is True


@pytest.mark.parametrize("ano,valor", [(2021, 8000.00), (2022, 8643.27), (2023, 9153.34), (2024, 9584.97),
                                       (2025, 10036.10), (2026, 10478.74), (2027, None), (2020, None)])
def test_paragrafo_7_veiculos(ano, valor):
    """14.133 art. 75 §7º ('contratações de até R$ 8.000,00 [...] manutenção de veículos') e Anexos dos decretos."""
    assert limite_par7(ano) == valor


def test_limite_dispensa_com_argumentos_novos():
    assert limite_dispensa(2026, "compras", lei="14133") == 65492.11
    assert limite_dispensa(2022, "compras", lei="8666", data_fato=D(2022, 5, 5)) == 17600.00
    assert limite_dispensa(2026, "compras", lei="14133", duplicado=True) == pytest.approx(130984.22)
    with pytest.raises(TetoIndeterminado) as e:
        limite_dispensa(2025, "compras", lei="13303")
    assert e.value.teto.valor_legal_padrao == 50000.00
    with pytest.raises(TetoIndeterminado):
        limite_dispensa(2026, "compras", data_fato=D(2026, 1, 5))     # sem lei → nunca pelo ano


def test_valores_novos_iguais_aos_da_doutrina():
    """`03-tetos-por-exercicio.md` §1 (coluna §7º) e §2/§3 — a mesma tabela, sem cópia divergente."""
    assert ld.LIMITES_13303_LEGAL == {"obras": 100000.00, "compras": 50000.00}
    assert ld.LIMITES_14065 == {"obras": 100000.00, "compras": 50000.00}
    assert ld.VIGENCIA_D9412 == D(2018, 7, 19)
