# -*- coding: utf-8 -*-
"""KPI que não leva ao dado — 198 métricas no painel e ZERO caminhos para as linhas por trás.

Medido em 2026-08-06: `kpi()` sempre teve um 5º parâmetro `dest`, e **nenhuma** das 198 chamadas o
passava. Quem lia "68 comissionados" não tinha como chegar aos 68. O dono descreveu assim: *"tá
tudo sambando, solto quando puxa"*.

E a primeira tentativa provou que o defeito é pior do que parecia: filtrando no NAVEGADOR, o clique
contradizia o próprio número — 68 comissionados viravam 55, 201 de terceiro setor viravam 22, e o
único par novo virava 0, porque só os 60 primeiros itens tinham chegado à página. **Métrica que não
bate com o que o clique mostra é pior do que métrica sem clique.** A fatia passou a ser aplicada na
fila inteira, no servidor.

Esta catraca não exige que todos os KPIs sejam clicáveis de uma vez — exige que a dívida NÃO CRESÇA
e que cada rodada a diminua. É o mesmo mecanismo dos tetos de rotas órfãs.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_painel_kpi_clicavel.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ABAS = RAIZ / "static" / "js" / "src" / "abas"

# Teto da dívida: quantas chamadas de kpi() ainda NÃO levam a lugar nenhum.
# 2026-08-06: 198 → 193 (os 5 do cartão de agente público). SÓ PODE DESCER.
TETO_KPI_SEM_CAMINHO = 193

_RX_KPI = re.compile(r"\bkpi\(")


def _chamadas() -> list[tuple[str, str]]:
    """(arquivo, trecho da chamada) para cada `kpi(` — recorte por parênteses balanceados."""
    out = []
    for f in sorted(ABAS.glob("*.js")):
        texto = f.read_text(encoding="utf-8")
        for m in _RX_KPI.finditer(texto):
            i = m.end() - 1
            nivel, j = 0, i
            while j < len(texto):
                if texto[j] == "(":
                    nivel += 1
                elif texto[j] == ")":
                    nivel -= 1
                    if nivel == 0:
                        break
                j += 1
            out.append((f.name, texto[m.start():j + 1]))
    return out


def _sem_caminho(chamadas) -> list[tuple[str, str]]:
    return [(a, c) for a, c in chamadas if "drill:" not in c and "kpi-go" not in c]


def test_divida_de_kpi_sem_caminho_nao_cresce():
    chamadas = _chamadas()
    assert len(chamadas) > 100, "o recorte das chamadas quebrou — reveja o parser antes do teto"
    mudos = _sem_caminho(chamadas)
    assert len(mudos) <= TETO_KPI_SEM_CAMINHO, (
        f"KPIs sem caminho para o dado subiram para {len(mudos)} (teto {TETO_KPI_SEM_CAMINHO}). "
        "Toda métrica nova nasce clicável: passe `{drill:'nomeDaFatia'}` no 5º argumento de kpi() "
        "e registre a fatia NO SERVIDOR, nunca filtrando só a página carregada.")


def test_teto_esta_apertado():
    """Teto folgado deixa a dívida voltar a crescer em silêncio — já aconteceu nesta casa."""
    mudos = _sem_caminho(_chamadas())
    assert TETO_KPI_SEM_CAMINHO - len(mudos) <= 3, (
        f"teto {TETO_KPI_SEM_CAMINHO} está folgado: hoje são {len(mudos)}. Baixe o teto.")


def test_fatia_e_aplicada_na_fila_inteira_no_servidor():
    """A regressão que este teste impede é a que já aconteceu: filtrar no navegador.

    Com o filtro no cliente, o clique mostrava um subconjunto da PÁGINA e o número do KPI vinha da
    FILA — dois universos diferentes na mesma tela.
    """
    rota = (RAIZ / "rotas" / "vinculos.py").read_text(encoding="utf-8")
    assert "_FATIAS" in rota and "total_fatia" in rota, (
        "a rota deixou de aplicar a fatia na fila inteira")
    js = (ABAS / "vinculos.js").read_text(encoding="utf-8")
    assert "filtro=" in js, "o painel voltou a não pedir a fatia ao servidor"
    assert "total_fatia" in js, "a nota de rodapé precisa citar o total DA FATIA, não o da página"
