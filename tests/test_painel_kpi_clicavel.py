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

# O TETO MEDE O QUE PODE SER CONSERTADO, e essa distinção foi medida antes de ser escrita.
#
# São 198 chamadas de `kpi()`. Delas, **139 leem um ESCALAR** do payload — mediana do item, F1
# macro, percentual de concentração, "SIAFE ok/off". Número que não é contagem de linhas NÃO TEM
# gaveta possível, e exigir uma seria pedir mentira. Um teto sobre as 180 mudas nunca chegaria a
# zero e viraria ruído que ninguém lê.
#
# O teto cobre as que CONTAM UM ARRAY que o próprio painel já tem em mão — essas podem ganhar
# caminho hoje, sem tocar rota, e sem risco de o clique contradizer o número.
# 2026-08-06: 19 convertíveis de verdade (a medição por `.length` na chamada inteira contava
# falso: `kpi(a.length ? fmtN(a[0].hhi) : "—")` exibe um MÁXIMO). 19 → 11 depois de Vínculos
# (grafo, ciclos, contato), conluio e poder.
# SÓ PODE DESCER. Toda conversão passa pelo `tools/painel_drill_check`, que CLICA e confere.
TETO_KPI_CONVERTIVEL_SEM_CAMINHO = 0

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


def _tem_5o_argumento(chamada: str) -> bool:
    """`kpi(v, l, cor, glifo, DESTINO)` — o 5º argumento é o caminho, seja aba ou `{drill}`.

    A primeira versão desta catraca procurava a string `drill:` e contava como MUDO todo KPI que
    já navegava para outra aba (`kpi(..., 'e_alertas')`), porque `kpi-go` é gerado em tempo de
    execução e não aparece na chamada. Contar errado a própria dívida é o mesmo defeito que a
    catraca existe para impedir — aqui a contagem passou a ser por VÍRGULAS DE TOPO.
    """
    corpo = chamada[chamada.index("(") + 1:-1]
    nivel, virgulas = 0, 0
    for ch in corpo:
        if ch in "([{":
            nivel += 1
        elif ch in ")]}":
            nivel -= 1
        elif ch == "," and nivel == 0:
            virgulas += 1
    return virgulas >= 4


def _sem_caminho(chamadas) -> list[tuple[str, str]]:
    return [(a, c) for a, c in chamadas if not _tem_5o_argumento(c)]


def _valor_exibido(chamada: str) -> str:
    """O 1º argumento de `kpi()` — o que o usuário LÊ. É ele que decide se há gaveta possível."""
    corpo = chamada[chamada.index("(") + 1:-1]
    nivel = 0
    for i, ch in enumerate(corpo):
        if ch in "([{":
            nivel += 1
        elif ch in ")]}":
            nivel -= 1
        elif ch == "," and nivel == 0:
            return corpo[:i]
    return corpo


def _convertiveis(chamadas) -> list[tuple[str, str]]:
    """Mudas cujo NÚMERO EXIBIDO é uma contagem de linhas que o painel já tem em mão.

    A primeira versão pedia só `.length` na chamada inteira e engolia falso convertível: em
    `kpi(a.length ? fmtN(a[0].hhi) : '—', 'Maior HHI')` o que se lê é um MÁXIMO, não uma contagem —
    o `.length` está só na guarda do ternário. Gaveta ali mostraria N linhas para um número que não
    é N. É a mesma família dos dois enganos de hoje (68 vs 55, 647 vs 0), agora na medição.
    """
    out = []
    for a, c in _sem_caminho(chamadas):
        v = _valor_exibido(c)
        if ".length" in v and "?" not in v:
            out.append((a, c))
    return out


def test_divida_de_kpi_convertivel_nao_cresce():
    chamadas = _chamadas()
    assert len(chamadas) > 100, "o recorte das chamadas quebrou — reveja o parser antes do teto"
    conv = _convertiveis(chamadas)
    assert len(conv) <= TETO_KPI_CONVERTIVEL_SEM_CAMINHO, (
        f"KPIs que contam um array e não levam a ele subiram para {len(conv)} "
        f"(teto {TETO_KPI_CONVERTIVEL_SEM_CAMINHO}). Toda métrica nova que conta linhas nasce "
        "clicável: `registrarDrill(nome,{titulo,itens,render})` e `{drill:nome}` no 5º argumento — "
        "com `itens` no MESMO universo que o número, nunca a página.")


def test_teto_esta_apertado():
    """Teto folgado deixa a dívida voltar a crescer em silêncio — já aconteceu nesta casa."""
    conv = _convertiveis(_chamadas())
    assert TETO_KPI_CONVERTIVEL_SEM_CAMINHO - len(conv) <= 3, (
        f"teto {TETO_KPI_CONVERTIVEL_SEM_CAMINHO} está folgado: hoje são {len(conv)}. Baixe o teto.")


def test_escalar_nao_e_cobrado_como_divida():
    """Controle: `kpi(fmtD(he.f1_macro,3),'F1 macro')` não conta linhas e não deve entrar no teto.

    Sem esta separação o teto nunca chegaria a zero e o número viraria ruído — e catraca que
    ninguém lê é catraca que não protege.
    """
    falsos = [c for _a, c in _convertiveis(_chamadas()) if ".length" not in c]
    assert not falsos, f"escalar contado como convertível: {falsos[:2]}"


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


def test_registro_de_drill_nao_pode_estar_dentro_de_template_literal():
    """NOVE das dez conversões nasceram mortas — e nenhum teste unitário veria.

    O bloco de KPIs mora dentro de uma template string de várias linhas. Inserir
    `registrarDrill(...)` na linha anterior ao KPI parecia seguro e fez a chamada virar **texto na
    página**: o KPI ganhou `data-drill`, o clique não fazia nada, e o JavaScript continuava válido.
    Foi o `tools/painel_drill_check` — clicando de verdade — que acusou: KPI 9, gaveta None.

    Aqui a regra é literal e um contador de crases decide, sem julgamento.
    """
    for f in sorted(ABAS.glob("*.js")):
        texto = f.read_text(encoding="utf-8")
        for ln in texto.split("\n"):
            if "registrarDrill(" not in ln:
                continue
            pos = texto.index(ln)
            assert texto.count("`", 0, pos) % 2 == 0, (
                f"{f.name}: `registrarDrill` dentro de template literal — vira texto na página e "
                f"o clique não faz nada:\n  {ln.strip()[:100]}")
