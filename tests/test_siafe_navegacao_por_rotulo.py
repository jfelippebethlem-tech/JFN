# -*- coding: utf-8 -*-
"""A navegação do menu do SIAFE tem de casar pelo RÓTULO, nunca pelo índice do item.

Medido em 2026-08-09, com print da tela. O segundo passo de `_navegar` preferia o id
`pt1:pt_np3:1:pt_cni4::disclosureAnchor` — que é a POSIÇÃO do item no menu do SIAFE 2. No SIAFE 1
(www5/SiafeRio, onde vivem 2016–2023) o mesmo id existe e aponta para outro item: "Execução" ali é
o índice 3. O clique cego levava a sessão para fora do sistema e caía numa página de bloqueio da
SEFAZ — que PARECE bloqueio de IP e não é: `curl` no login do www5 devolve a página normal (26 KB)
e o print pós-login mostra o SIAFE-Rio aberto, exercício 2023, menu completo. Foi o método, como a
regra da casa avisa ([[sei-siafe-nunca-culpar-acesso-nem-waf]]).

Efeito prático: sem esse passo não há segunda linha de filtro, sem ela não há subdivisão por
prefixo, e sem subdivisão o teto de 1.000 registros por consulta nunca é furado — a origem dos 23
pares (UG, ano) parados em contagem redonda.
"""
from __future__ import annotations

import inspect
import re

import compliance_agent.siafe_ob_orcamentaria as M


def _passo_execucao_financeira() -> str:
    """O trecho de CÓDIGO do segundo passo — a docstring da função também cita o rótulo, e
    procurar a primeira ocorrência casaria com ela, não com o clique."""
    fonte = inspect.getsource(M._navegar)
    corpo = fonte[fonte.find('"""', fonte.find('"""') + 3):]   # tira a docstring
    i = corpo.lower().find("execução financeira")
    assert i > 0, "o passo de 'Execução Financeira' sumiu de _navegar"
    return corpo[max(0, i - 900):i + 400]


def test_rotulo_tem_precedencia_sobre_o_id_de_posicao():
    trecho = _passo_execucao_financeira()
    pos_rotulo = trecho.lower().find("execução financeira")
    pos_id = trecho.find("pt1:pt_np3:1:pt_cni4")
    assert pos_rotulo > 0, "o casamento por rótulo (minúsculas, normalizado) não está no passo"
    assert pos_id > 0, "o id continua como fallback — é útil, só não pode vir primeiro"
    assert pos_rotulo < pos_id, (
        "o id de POSIÇÃO voltou a ter precedência sobre o rótulo: no SIAFE 1 esse índice é "
        "outro item e a sessão sai do sistema")


def test_casamento_ignora_acento_e_caixa():
    """O rótulo aparece com e sem acento conforme o sistema; o cotejo normaliza os dois."""
    trecho = _passo_execucao_financeira()
    assert "execucao financeira" in trecho, "sem a variante sem acento, o SIAFE 1 não casa"
    assert "toLowerCase" in trecho


def test_primeiro_passo_ja_era_por_rotulo():
    """Regressão ao contrário: o passo 'Execução' nunca dependeu de índice — mantém assim."""
    fonte = inspect.getsource(M._navegar)
    corpo = fonte[fonte.find('"""', fonte.find('"""') + 3):]
    trecho = corpo[:corpo.lower().find("execução financeira")]
    assert re.search(r"===\s*'Execução'", trecho), "o primeiro passo deixou de casar por rótulo"


def test_todo_caminho_de_menu_prefere_rotulo():
    """Varredura: nenhum módulo pode clicar no id de POSIÇÃO antes de tentar o rótulo.

    O defeito foi achado em `siafe_ob_orcamentaria._navegar` e existia IGUAL em
    `coletar_obs_sessao._ir_obs` — copiar-e-colar espalha a armadilha. Esta catraca varre o pacote
    inteiro: onde o id `pt1:pt_np3:<n>:` aparecer, o casamento por texto tem de vir antes.
    """
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parent.parent
    faltando = []
    for arq in (raiz / "compliance_agent").rglob("*.py"):
        txt = arq.read_text(encoding="utf-8", errors="replace")
        if "pt_np3:" not in txt:
            continue
        for bloco in txt.split("await pg.evaluate")[1:]:
            trecho = bloco[:900]
            if "pt_np3:" not in trecho:
                continue
            pos_id = trecho.find("pt_np3:")
            pos_txt = min([p for p in (trecho.find("innerText"), trecho.find("norm(")) if p >= 0]
                          or [10**6])
            if pos_txt > pos_id:
                faltando.append(f"{arq.relative_to(raiz)} (id antes do rótulo)")
    assert not faltando, "clique por índice de menu sem rótulo antes: " + "; ".join(faltando)
