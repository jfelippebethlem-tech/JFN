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
    contadas = _contagens_em_variavel()
    out = []
    for a, c in _sem_caminho(chamadas):
        v = _valor_exibido(c)
        if ".length" in v and "?" not in v:
            out.append((a, c))
            continue
        # CONTAGEM GUARDADA EM VARIÁVEL. `const alta = g.filter(...).length` e depois
        # `kpi(fmtN(alta), ...)` é a MESMA coisa que contar inline — e a primeira versão desta
        # catraca não via nenhuma delas, deixando quatro métricas de fora do alvo sem que ninguém
        # soubesse. Medir errado a própria dívida é o defeito que a catraca existe para impedir.
        for nome in contadas.get(a, ()):
            if re.search(rf"\b{re.escape(nome)}\b", v):
                out.append((a, c))
                break
    return out


_RX_CONTAGEM = re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=\s*[\w.]+\.filter\(.*?\)\.length")


def _contagens_em_variavel() -> dict[str, set[str]]:
    """Variáveis que guardam `algo.filter(...).length`, por arquivo."""
    fora: dict[str, set[str]] = {}
    for f in sorted(ABAS.glob("*.js")):
        texto = f.read_text(encoding="utf-8")
        nomes = set(_RX_CONTAGEM.findall(texto))
        # `const a=x.filter().length, b=y.filter().length` — a segunda não casa o prefixo
        for ln in texto.split("\n"):
            for parte in ln.split(","):
                m = re.search(r"(\w+)\s*=\s*[\w.]+\.filter\(.*\)\.length", parte)
                if m:
                    nomes.add(m.group(1))
        fora[f.name] = nomes
    return fora


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


def test_todo_nome_de_gaveta_citado_por_kpi_existe():
    """`{drill:'X'}` sem `X` registrado em lugar nenhum é KPI que finge ter caminho.

    O KPI ganha `data-drill`, cursor de botão e `role="button"` — e o clique não faz nada. É a
    mesma família das nove conversões que nasceram mortas, só que por outro caminho: ali a chamada
    virava texto, aqui ela simplesmente não existe.

    Três formas de registro contam, porque as três acabam ligando o clique a alguma coisa:
    `registrarDrill('X'`, `drillSeCompleto('X'` (que só liga quando a lista é o universo) e a
    entrada em `DRILL_ACOES`, usada quando clicar deve REFAZER a busca no servidor com um filtro —
    foi assim que os KPIs de agente público deixaram de mentir, filtrando na fonte em vez de na
    tela.
    """
    citados: dict[str, list[str]] = {}
    registrados: set[str] = set()
    for f in sorted(ABAS.glob("*.js")):
        texto = f.read_text(encoding="utf-8")
        for m in re.finditer(r"\{\s*drill\s*:\s*'([A-Za-z0-9_]+)'", texto):
            citados.setdefault(m.group(1), []).append(f.name)
        for m in re.finditer(r"(?:registrarDrill|drillSeCompleto)\(\s*'([A-Za-z0-9_]+)'", texto):
            registrados.add(m.group(1))
        # DRILL_ACOES = Object.fromEntries(['a','b',...].map(...))
        for bloco in re.findall(r"DRILL_ACOES\s*=.*?\]", texto, re.S):
            registrados.update(re.findall(r"'([A-Za-z0-9_]+)'", bloco))

    orfaos = {k: v for k, v in citados.items() if k not in registrados}
    assert not orfaos, (
        "KPI cita gaveta que ninguém registra — o clique não faz nada:\n" +
        "\n".join(f"  • {k} (em {', '.join(sorted(set(v)))})" for k, v in sorted(orfaos.items())))


def test_kpi_com_lista_cortada_usa_a_guarda_de_completude():
    """Gaveta menor que o KPI faz o leitor desconfiar do número CERTO.

    Medido em 07/08/2026 na aba de vínculos: `Assinaturas capturadas` marcava 165 e abria 150,
    porque a rota serve uma página (`?limite=`) enquanto o total conta o acervo. `Processos com
    sinal` marcava 294 e abria 120. `Matrículas identificadas` marcava 51 e abria 110 — ali nem era
    corte, era UNIDADE: o KPI conta matrículas, a lista contava assinaturas.

    Onde a tela pede uma página, o registro tem de passar por `drillSeCompleto`, que compara em
    tempo de execução e desliga a gaveta quando a lista não é o universo. Este teste vigia a
    correlação mais simples que existe entre as duas coisas: quem chama a rota com `limite=` não
    pode registrar gaveta crua para o KPI que mostra o total do servidor.
    """
    alvo = ABAS / "vinculos.js"
    texto = alvo.read_text(encoding="utf-8")
    for nome in ("apAll", "opTodos", "apIdent", "apSemPar", "cmAchados"):
        assert f"registrarDrill('{nome}'" not in texto, (
            f"{nome} voltou a registrar gaveta CRUA: o KPI correspondente mostra o total do "
            f"servidor e a tela tem só uma página. Use `drillSeCompleto`, que desliga a gaveta "
            f"quando a lista em mão não é o universo — e deixa o número continuar verdadeiro.")
        assert f"drillSeCompleto('{nome}'" in texto, (
            f"{nome} sumiu — se a métrica foi retirada, retire o nome desta lista com o motivo "
            f"escrito; se foi renomeada, atualize aqui.")


TETO_KPI_SEM_PROCEDENCIA = 0


def test_nenhum_kpi_fica_sem_procedencia():
    """Um número no painel tem de dizer de onde veio — em 07/08/2026 a dívida chegou a ZERO.

    A medição inicial era de 215 KPIs com 127 SEM CAMINHO NENHUM: clicar não fazia nada e o número
    pedia fé. O teto anterior desta casa cobrava só os CONVERTÍVEIS (os que contam uma lista já em
    mão), e com razão — exigir gaveta de quem mede uma relação seria pedir mentira. Mas isso deixou
    de fora a maioria, que não precisava de lista e sim de PROCEDÊNCIA: o que mede, de que fonte
    sai, o que não autoriza concluir.

    Agora que a dívida é zero, o teto fecha a porta. Métrica nova nasce com uma das três formas:
    `{drill}` quando conta um conjunto que a tela tem inteiro, `drillSeCompleto` quando a rota
    pagina, `{sobre}` quando mede uma relação. A quarta forma — nenhuma delas — deixa de existir.
    """
    mudas = []
    for arquivo, chamada in _sem_caminho(_chamadas()):
        mudas.append(f"{arquivo}: {chamada[:90]}")
    assert len(mudas) <= TETO_KPI_SEM_PROCEDENCIA, (
        f"{len(mudas)} KPI(s) voltaram a não dizer de onde vêm (teto "
        f"{TETO_KPI_SEM_PROCEDENCIA}):\n" + "\n".join(f"  • {m}" for m in mudas[:12]) +
        "\n\nEscolha a forma pelo que a métrica MEDE: conjunto → `{drill:'nome'}` com "
        "`registrarDrill`; conjunto que a rota pagina → `drillSeCompleto(nome,total,itens,cfg)`; "
        "relação (taxa, cobertura, defasagem, grau) → `{sobre:'o que mede, de que fonte, o que "
        "não autoriza concluir'}`.")


def test_drill_se_completo_sempre_tem_caminho_de_reserva():
    """A guarda de completude devolve `null` — e `null` no 5º argumento é KPI MUDO.

    Este furo não aparecia na leitura do código: `kpi(n, 'X', cor, glifo, drillSeCompleto(...))`
    tem cinco argumentos e passa em qualquer contagem estática. Só que `drillSeCompleto` devolve
    `null` quando a lista em mão não é o universo — e aí, em tempo de execução, o KPI perde o
    caminho justamente nas telas em que a rota pagina, que são as mais volumosas.

    Medido em 07/08/2026 na varredura das 60 abas: a fonte acusava zero mudos e a PÁGINA mostrava
    três — `Estouram o teto legal`, `Mercados analisados` e `Comunidades relevantes`. A lição é a
    de sempre nesta casa: medir o efeito, não a ação.

    Toda chamada tem de trazer `||{sobre:...}`: quando a gaveta não pode abrir sem mentir, o
    leitor ao menos recebe a procedência — o que a métrica mede e por que a lista não cabe.
    """
    sem_reserva = []
    for f in sorted(ABAS.glob("*.js")):
        texto = f.read_text(encoding="utf-8")
        for m in re.finditer(r"drillSeCompleto\(\s*'([A-Za-z0-9_]+)'", texto):
            j, prof, q = m.start() + len("drillSeCompleto"), 0, None
            while j < len(texto):
                c = texto[j]
                if q:
                    if c == q and texto[j - 1] != "\\":
                        q = None
                elif c in "\"'`":
                    q = c
                elif c == "(":
                    prof += 1
                elif c == ")":
                    prof -= 1
                    if prof == 0:
                        break
                j += 1
            resto = texto[j + 1:j + 40].lstrip()
            # a forma `const _d = drillSeCompleto(...)` é legítima: a reserva vem no uso do `_d`
            trecho = texto[max(0, m.start() - 40):m.start()]
            if re.search(r"(?:const|let|var)\s+\w+\s*=\s*$", trecho):
                continue
            if not resto.startswith("||"):
                sem_reserva.append(f"{f.name}: {m.group(1)}")
    assert not sem_reserva, (
        "`drillSeCompleto` sem `||{sobre:...}` — o KPI fica MUDO quando a lista vem cortada:\n" +
        "\n".join(f"  • {s}" for s in sem_reserva))


def test_gaveta_tem_teto_de_renderizacao():
    """Gaveta de 12.640 linhas NÃO ABRE — e o KPI parecia clicável.

    Medido em campo (2026-08-08) pela sondagem ressuscitada: `pessoasIdentificadas` registrava a
    gaveta completa — honesta no número — e o clique travava a página montando 12,6 mil cards; a
    sondagem via "gaveta mostra None". Gaveta é instrumento de CONFERÊNCIA, não de exportação:
    acima do teto, `drillSeCompleto` devolve null e o KPI cai para a procedência, que explica o
    universo. O número continua verdadeiro; muda o veículo.
    """
    drill = (RAIZ / "static" / "js" / "src" / "nucleo" / "drill.js").read_text(encoding="utf-8")
    assert "TETO_LINHAS_GAVETA" in drill, "o teto de renderização da gaveta sumiu"
    assert "lista.length > TETO_LINHAS_GAVETA" in drill, (
        "a guarda de completude deixou de aplicar o teto — KPI gigante volta a fingir que abre")
