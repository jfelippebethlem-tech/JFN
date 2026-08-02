# -*- coding: utf-8 -*-
"""Capacidade PRONTA sem porta de entrada — a dívida que se acumulava em silêncio.

O PADRÃO QUE ESTA CATRACA QUEBRA. As catracas de rota (`test_rotas_sem_orfa`, teto 0, e
`test_rotas_sem_superficie`) medem a dívida DEPOIS de ela existir: alguém constrói, o número sobe, e
só então se descobre. Aqui o vetor se inverte — a capacidade nasce declarando se tem porta de entrada
ou por que não tem. É a diferença entre um alarme e um portão.

E o problema é real e medido: das **77 capacidades com status PRONTO** em `capabilities.yaml`,
**49 não têm bloco `menu:`**. Nem todas deveriam ter — plano de controle (status, reload de skills,
gatilho de coleta) existe para máquina, não para tela. Mas "não deveria" precisa estar ESCRITO, e não
estava em lugar nenhum.

O teto só pode CAIR. Ao criar `menu:` para uma capacidade, abaixe o número no mesmo commit — é a
única forma de o progresso aparecer.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_RAIZ = Path(__file__).resolve().parents[1]
_YAML = _RAIZ / "capabilities.yaml"

# Medido em 2026-07-30. SÓ PODE CAIR.
TETO_PRONTO_SEM_MENU = 48

# Capacidades que NÃO devem ter botão, uma a uma e com o motivo — nunca um padrão que engole o que
# não deveria (a lição de `_SEM_UI_POR_DESENHO` na catraca de rotas órfãs).
_SEM_MENU_POR_DESENHO = {
    # plano de controle: existe para o Yoda/Hermes e para operação, não para a tela
    "skills", "skill_detalhe", "skills_reload", "skills_sync", "skills_validate",
    "status_jfn", "agenda_jobs", "memoria", "radar_status", "sweeps_status", "siafe_status",
    "missao_autonoma", "missao_estado", "missao_trabalhar", "missao_parar",
    # gatilhos de COLETA: pesados, com janela de horário, e disparo acidental custa caro
    "siafe_atualizar", "siafe_coletar_ug", "emendas_coletar", "pcrj_gastos_coletar",
    "editais_corpus", "enriquecer_socios", "cruzador", "vigiar",
}


def _capacidades() -> list[dict]:
    return yaml.safe_load(_YAML.read_text(encoding="utf-8")).get("capacidades") or []


def _prontas_sem_menu() -> list[str]:
    return sorted(c["id"] for c in _capacidades()
                  if str(c.get("status", "")).upper() == "PRONTO" and not c.get("menu"))


def test_divida_de_capacidade_sem_porta_nao_cresce():
    faltando = _prontas_sem_menu()
    assert len(faltando) <= TETO_PRONTO_SEM_MENU, (
        f"capacidades PRONTAS sem `menu:` subiram de {TETO_PRONTO_SEM_MENU} para {len(faltando)}. "
        "Capacidade construída que ninguém alcança é trabalho que não vira decisão de fiscalização. "
        "Dê um `menu:` a ela, ou declare o motivo em _SEM_MENU_POR_DESENHO.\n  "
        + "\n  ".join(faltando))


def test_teto_esta_apertado():
    """Teto folgado deixa a dívida voltar em silêncio — foi assim que o de sem-superfície ficou em 23
    com a dívida real em 0, por não ter este teste."""
    faltando = _prontas_sem_menu()
    assert len(faltando) >= TETO_PRONTO_SEM_MENU, (
        f"só {len(faltando)} capacidades sem `menu:` contra teto {TETO_PRONTO_SEM_MENU} — "
        f"abaixe o teto para {len(faltando)} e trave o ganho")


def test_o_que_gera_PEÇA_tem_de_ter_porta_de_entrada():
    """Estas produzem PDF/.docx que alguém assina. Sem botão, o trabalho fica invisível para quem decide.

    É a mesma família de achado que originou a catraca de rotas órfãs: `/api/dossie/completo`,
    `/api/mandato/minuta` e companhia estavam implementadas, testadas e inalcançáveis pelo painel.
    """
    caps = {c["id"]: c for c in _capacidades()}
    entregaveis = ("relatorio_inteligencia", "relatorio_orgao", "dossie", "instrumento_mandato")
    sem = [i for i in entregaveis if i in caps and not caps[i].get("menu")]
    assert not sem, f"capacidade que gera PEÇA sem porta de entrada: {sem}"


def test_exceção_nomeada_existe_de_verdade():
    """Exceção para id que sumiu vira licença que ninguém revisa."""
    ids = {c["id"] for c in _capacidades()}
    fantasmas = sorted(_SEM_MENU_POR_DESENHO - ids)
    assert not fantasmas, f"_SEM_MENU_POR_DESENHO cita id inexistente: {fantasmas}"


def test_o_arquivo_gerado_de_botoes_esta_em_dia():
    """`static/js/caps.js` é DERIVADO. Divergir dele é criar a quinta cópia da mesma lista."""
    from tools.gerar_superficie_caps import _SAIDA, mestras, render

    assert _SAIDA.exists(), "static/js/caps.js não existe — rode tools/gerar_superficie_caps.py"
    assert _SAIDA.read_text(encoding="utf-8") == render(mestras()), (
        "static/js/caps.js está desatualizado em relação a capabilities.yaml — "
        "rode `PYTHONPATH=. .venv/bin/python -m tools.gerar_superficie_caps`")


def test_toda_funcao_mestra_chega_ao_painel():
    """O arquivo gerado só vale se o painel o CARREGA — senão é arquivo bonito e botão nenhum."""
    from tools.gerar_superficie_caps import mestras

    html = (_RAIZ / "static" / "jfn-painel.html").read_text(encoding="utf-8")
    assert "/static/js/caps.js" in html, "o painel não carrega o arquivo de funções mestras"
    # v58 (2026-08-02): `painel.js` virou `painel.bundle.js` + `js/src/`. A garantia é a mesma —
    # alguém no front tem de CONSUMIR `CAPS_MESTRAS`; onde esse alguém mora é decisão do dono do
    # painel. Procura no que existir, na ordem em que o painel realmente carrega.
    _js_dir = _RAIZ / "static" / "js"
    fontes = [p for p in (_js_dir / "painel.bundle.js", _js_dir / "painel.js") if p.exists()]
    fontes += sorted((_js_dir / "src").rglob("*.js")) if (_js_dir / "src").is_dir() else []
    assert fontes, "não há JS do painel em static/js (nem bundle, nem painel.js, nem src/)"
    assert any("CAPS_MESTRAS" in p.read_text(encoding="utf-8") for p in fontes), \
        "nenhum JS do painel consome CAPS_MESTRAS"
    assert mestras(), "nenhuma função mestra gerada — o bloco `menu:` sumiu do YAML?"
