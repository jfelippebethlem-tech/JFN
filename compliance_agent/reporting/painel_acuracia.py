# -*- coding: utf-8 -*-
"""Painel de acurácia (A.3.5) — o número da qualidade fica visível junto do produto.

POR QUE ISTO EXISTE. A casa mede a hermenêutica (`tools/eval_hermeneutica`) e agora TRAVA
regressão (`comparar_com_baseline`). Faltava a terceira perna: **mostrar**. Métrica que só existe
em log de job não disciplina ninguém — quem lê o relatório não sabe quanto vale o juízo que está
lendo, e quem mexe no prompt não vê o efeito. `PRODUCT.md` já exige honestidade visual; este
módulo é ela aplicada à própria qualidade do motor.

O QUE O PAINEL NÃO PODE FAZER, e é a decisão de desenho principal: **não pode inventar número
quando não há medição**. Um card em branco é informação; um card com "—" tratado como 0% é
mentira, e um card com o último valor sem dizer de quando é pior ainda, porque parece atual.
Por isso todo estado é explícito: `sem_medicao`, `sem_baseline`, `medido`.

TRÊS NÚMEROS, e nenhum deles sozinho: **F1 macro** (a qualidade), **contra o baseline burro** (se
o motor bate o papagaio que responde sempre a classe majoritária), e **alucinação de citação** —
que é a única métrica com tolerância ZERO, porque inventar trecho é o defeito que a casa não
aceita a nenhum preço.
"""
from __future__ import annotations

import json
import os
from typing import Any

CAMINHO_BASELINE = "data/hermeneutica_baseline.json"
CAMINHO_ULTIMA = "data/hermeneutica_ultima.json"

# Faixas de leitura do F1 macro. Não são notas: são o que se pode AFIRMAR com o número.
FAIXAS = (
    (0.80, "alta", "o veredito sustenta triagem com pouca revisão"),
    (0.65, "media", "o veredito orienta a fila; toda peça exige revisão humana"),
    (0.45, "baixa", "serve para ordenar prioridade, não para decidir"),
    (0.00, "insuficiente", "não use o veredito isolado para decidir nada"),
)


def _ler(caminho: str) -> dict | None:
    try:
        with open(caminho, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def faixa_de(f1: float) -> tuple[str, str]:
    for piso, nome, leitura in FAIXAS:
        if f1 >= piso:
            return nome, leitura
    return FAIXAS[-1][1], FAIXAS[-1][2]


def montar(*, caminho_ultima: str = CAMINHO_ULTIMA,
           caminho_baseline: str = CAMINHO_BASELINE) -> dict[str, Any]:
    """Estado da qualidade do motor não-determinístico, pronto para o card.

    Nunca devolve número inventado: sem medição, `estado='sem_medicao'` e os campos ficam `None`.
    """
    ultima = _ler(caminho_ultima)
    baseline = _ler(caminho_baseline)

    if not ultima or ultima.get("f1_macro") is None:
        return {"estado": "sem_medicao", "f1_macro": None, "faixa": None,
                "mensagem": ("a hermenêutica ainda não foi medida neste ambiente — rode "
                             "`python -m tools.eval_hermeneutica --holdout --aceitar`"),
                "tem_baseline": bool(baseline), "ressalva": _RESSALVA}

    f1 = float(ultima["f1_macro"])
    faixa, leitura = faixa_de(f1)
    alucinacao = ultima.get("alucinacao_citacao")
    bate = ultima.get("bate_o_baseline")

    cartao: dict[str, Any] = {
        "estado": "medido",
        "f1_macro": round(f1, 4),
        "faixa": faixa,
        "leitura": leitura,
        "bate_o_papagaio": bate,
        "alucinacao_citacao": alucinacao,
        "abstencao": ultima.get("abstencao"),
        "n": ultima.get("n"),
        "prompt_versao": ultima.get("prompt_versao"),
        "prompt_hash": ultima.get("prompt_hash"),
        "medido_em": ultima.get("medido_em"),
        "f1_por_classe": ultima.get("f1_por_classe") or {},
        "ressalva": _RESSALVA,
    }

    # Alertas: cada um corresponde a uma coisa que NÃO se deve deixar passar em silêncio.
    alertas: list[str] = []
    if bate is False:
        alertas.append("o motor NÃO bate o baseline de classe majoritária — o número alto de "
                       "acurácia, se houver, é de papagaio")
    if alucinacao:
        alertas.append(f"alucinação de citação em {alucinacao:.1%} — tolerância desta casa é ZERO")
    if faixa in ("baixa", "insuficiente"):
        alertas.append(f"F1 macro {f1:.3f} na faixa '{faixa}': {leitura}")
    piores = sorted((cartao["f1_por_classe"] or {}).items(), key=lambda kv: kv[1])[:1]
    if piores and piores[0][1] < 0.20:
        alertas.append(f"a classe '{piores[0][0]}' está em F1 {piores[0][1]:.2f} — a média "
                       "esconde uma classe que o motor deixou de entender")
    cartao["alertas"] = alertas

    if not baseline:
        cartao["comparacao"] = {"estado": "sem_baseline",
                                "nota": "primeira medição — não há com o que comparar"}
        return cartao

    d_f1 = f1 - float(baseline.get("f1_macro") or 0.0)
    d_alu = float(alucinacao or 0.0) - float(baseline.get("alucinacao_citacao") or 0.0)
    cartao["comparacao"] = {
        "estado": "comparado",
        "baseline_f1": baseline.get("f1_macro"),
        "delta_f1": round(d_f1, 4),
        "delta_alucinacao": round(d_alu, 4),
        "prompt_versao_baseline": baseline.get("prompt_versao"),
        "mesmo_prompt": (baseline.get("prompt_hash") == ultima.get("prompt_hash")
                         if baseline.get("prompt_hash") and ultima.get("prompt_hash") else None),
    }
    # Comparar medições de PROMPTS diferentes sem dizer não é comparar a mesma coisa.
    if cartao["comparacao"]["mesmo_prompt"] is False:
        cartao["comparacao"]["nota"] = ("o prompt mudou entre as duas medições — a diferença "
                                        "inclui o efeito da alteração, não só do modelo")
    return cartao


def render_html(cartao: dict[str, Any]) -> str:
    """Card do painel. Sem medição, o card DIZ isso — não desenha zero."""
    if cartao.get("estado") != "medido":
        return ('<div class="card acuracia"><h3>Acurácia do juízo jurídico</h3>'
                f'<p class="vazio">{cartao.get("mensagem", "sem medição")}</p></div>')
    c = cartao
    alertas = "".join(f'<li class="alerta">{a}</li>' for a in c.get("alertas") or [])
    cmp_ = c.get("comparacao") or {}
    delta = ""
    if cmp_.get("estado") == "comparado":
        sinal = "+" if (cmp_["delta_f1"] or 0) >= 0 else ""
        delta = (f'<p class="delta">contra o aceito: {sinal}{cmp_["delta_f1"]:.3f}'
                 + (f' · <em>{cmp_["nota"]}</em>' if cmp_.get("nota") else "") + "</p>")
    return (
        '<div class="card acuracia">'
        "<h3>Acurácia do juízo jurídico</h3>"
        f'<p class="numero">F1 macro <strong>{c["f1_macro"]:.3f}</strong> '
        f'<span class="faixa">({c["faixa"]})</span></p>'
        f'<p class="leitura">{c["leitura"]}</p>'
        f'<p class="detalhe">alucinação de citação: {(c.get("alucinacao_citacao") or 0):.1%} · '
        f'abstenção: {(c.get("abstencao") or 0):.1%} · n={c.get("n") or "?"} · '
        f'prompt {c.get("prompt_versao") or "?"}</p>'
        f"{delta}"
        + (f'<ul class="alertas">{alertas}</ul>' if alertas else "")
        + f'<p class="ressalva">{c["ressalva"]}</p>'
        "</div>"
    )


def gravar_ultima(resultado: dict, *, caminho: str = CAMINHO_ULTIMA,
                  medido_em: str | None = None) -> str:
    """Persiste a medição para o painel. NUNCA grava os `detalhes` — carregam o holdout."""
    from tools.eval_hermeneutica import resumo_para_baseline

    d = resumo_para_baseline(resultado)
    if medido_em:
        d["medido_em"] = medido_em
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=2)
    return caminho


_RESSALVA = (
    "F1 medido sobre holdout selado de decisões reais do TCU. O número descreve o juízo da camada "
    "não-determinística, que tem teto de grau C na régua da casa: nenhum veredito de IA fundamenta "
    "peça sozinho, qualquer que seja a acurácia."
)
