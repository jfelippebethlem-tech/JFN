# -*- coding: utf-8 -*-
"""Score de convergência — JFN 2.0, Onda 3. Soma ponderada e DECOMPONÍVEL de indícios.

Agrega sinais heterogêneos sobre uma entidade (fornecedor/UG/contrato) — Benford, sobrepreço,
conflito doador↔contrato, red flags R1–R12 do edital, concentração, empresa recém-aberta — num
score 0–100 com a CONTRIBUIÇÃO de cada flag (auditável). Pesos curados (calibráveis depois com
`lex_base_empirica`).

Invariante: este é o **risco de ACHADO** (atenção/triagem) — NÃO é risco de punição nem prova.
A convergência de indícios aumenta a prioridade de apuração, jamais afirma irregularidade.
"""
from __future__ import annotations

# Peso de cada sinal (0..1 de intensidade × peso → contribuição). Curados; somam > 1 de
# propósito (a normalização final é por teto), refletindo gravidade relativa.
PESOS: dict[str, float] = {
    "benford_nao_conforme": 18.0,   # distribuição de dígitos fora de Nigrini (fracionamento/fabricação)
    "sobrepreco": 22.0,             # preço pago acima da mediana de referência (R4)
    "conflito_doador": 25.0,        # doador de campanha ↔ contrato (direto ou via sócio)
    "red_flag_edital": 8.0,         # cada red flag R1–R12 do edital/TR (× nº, com teto)
    "concentracao_orgao": 12.0,     # >60% do faturamento num único órgão
    "empresa_recente": 10.0,        # aberta < N meses antes do 1º contrato/OB
    "socio_comum": 10.0,            # sócio/endereço/contador comum com "concorrente" (cartel)
    "sancao_ceis_cnep": 20.0,       # inscrição em CEIS/CNEP (sanção vigente)
}

_FAIXAS = [(10, "BAIXO"), (40, "MÉDIO"), (70, "ALTO"), (101, "EXTREMO")]


def _faixa(score: float) -> str:
    for limite, rotulo in _FAIXAS:
        if score < limite:
            return rotulo
    return "EXTREMO"


def convergencia(sinais: dict) -> dict:
    """Calcula o score de convergência a partir de um dict de sinais detectados.

    `sinais[k]` pode ser:
      - bool: presente/ausente (intensidade 1.0/0.0);
      - float/int: intensidade já normalizada em [0,1] (ex.: sobrepreço 0.5);
      - int >1 para `red_flag_edital`: nº de red flags (cada uma soma, com teto de 3).
    Sinais fora de PESOS são ignorados (com aviso). Retorna {score, faixa, contribuicoes, _nota}.
    """
    contribuicoes = []
    ignorados = []
    total = 0.0
    for k, v in (sinais or {}).items():
        if k not in PESOS:
            ignorados.append(k)
            continue
        if k == "red_flag_edital":
            intensidade = min(int(v), 3) / 3.0 if v else 0.0  # teto de 3 red flags = intensidade 1
        elif isinstance(v, bool):
            intensidade = 1.0 if v else 0.0
        else:
            try:
                intensidade = max(0.0, min(float(v), 1.0))
            except (TypeError, ValueError):
                intensidade = 0.0
        contrib = PESOS[k] * intensidade
        if contrib > 0:
            contribuicoes.append({"flag": k, "peso": PESOS[k],
                                  "intensidade": round(intensidade, 3), "contribuicao": round(contrib, 2)})
        total += contrib

    score = round(min(total, 100.0), 1)
    contribuicoes.sort(key=lambda c: -c["contribuicao"])
    nota = ("Risco de ACHADO (prioridade de apuração), NÃO risco de punição nem prova. "
            "Convergência de indícios; presunção de legitimidade dos atos administrativos.")
    if ignorados:
        nota += f" Sinais ignorados (sem peso): {ignorados}."
    return {"score": score, "faixa": _faixa(score), "contribuicoes": contribuicoes, "_nota": nota}
