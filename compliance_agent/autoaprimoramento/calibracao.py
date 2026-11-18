# -*- coding: utf-8 -*-
"""calibracao — quanto vale o "risco alto" de cada motor, medido contra a conferência.

P(o laudo continua risco alto depois de conferido | motor, faixa de nota), com intervalo de Jeffreys (Brown, Cai e
DasGupta 2001: Wilson/Jeffreys para n pequeno, nunca Wald), Brier e BSS contra a taxa-base (como o juiz do Massare) e
ECE só como figura auxiliar (com n≈100 é ruidoso — Kumar, Liang e Ma 2019). Sem isotônica (sobreajusta com poucos
dados — Niculescu-Mizil e Caruana 2005): três faixas com posterior Beta.

A nota 0–10 que o modelo escreve NÃO é probabilidade (confiança verbalizada é superconfiante — Xiong et al. 2024).
O que se publica é a taxa medida; célula sem amostra mínima devolve INDISPONÍVEL (None), nunca um palpite.

DUAS FASES. O rótulo de fonte primária (nível 2) é raro e foi escolhido a dedo entre os que o Opus manteve altos; o
rótulo do Opus sobre o resumo (nível 1) é farto e imperfeito. `duas_fases` combina os dois sem misturar:
  P(alto real | fraco alto) = P(Opus alto | fraco alto)·P(real | Opus alto) + P(Opus baixo | fraco alto)·P(real | Opus baixo)
— a mesma lógica de corrigir a predição farta pelo erro medido no ouro (Prediction-Powered Inference, Angelopoulos
et al. 2023) e de ponderar pelo estrato de onde o rótulo saiu (Kossen et al. 2021)."""
from __future__ import annotations

import json
import random
import time

from . import config, ledger

FAIXAS = (("baixa", 0, 3), ("media", 4, 6), ("alta", config.ALTO, 10))
N_MINIMO = 8                 # abaixo disso a célula não fala por si (cai no conjunto dos motores, ou INDISPONÍVEL)
TODOS = "todos"


def faixa_de(nota: int) -> str:
    return next(nome for nome, a, b in FAIXAS if a <= nota <= b)


def jeffreys(k: int, n: int, draws: int = 20000, semente: int = 7) -> tuple[float, float, float]:
    """(média, limite inferior, limite superior a 95%) da posterior Beta(k+½, n−k+½). Monte Carlo com semente fixa
    (determinístico; a biblioteca padrão não traz o quantil da Beta)."""
    a, b = k + 0.5, n - k + 0.5
    rnd = random.Random(semente * 1000003 + k * 1009 + n)
    xs = sorted(rnd.betavariate(a, b) for _ in range(draws))
    return a / (a + b), xs[int(0.025 * draws)], xs[int(0.975 * draws) - 1]


def tabela(rotulos: list[dict]) -> dict:
    """{motor: {faixa: {n, k, p, lo, hi}}} — k = quantos seguiram risco alto no rótulo. Inclui o motor 'todos'."""
    cont: dict[tuple[str, str], list[int]] = {}
    for r in rotulos:
        for motor in (r["motor"], TODOS):
            c = cont.setdefault((motor, faixa_de(r["nota"])), [0, 0])
            c[0] += 1
            c[1] += int(bool(r["alto_verificado"]))
    out: dict = {}
    for (motor, fx), (n, k) in sorted(cont.items()):
        p, lo, hi = jeffreys(k, n)
        out.setdefault(motor, {})[fx] = {"n": n, "k": k, "p": round(p, 4), "lo": round(lo, 4), "hi": round(hi, 4)}
    return out


def prob(tab: dict, motor: str, nota: int | None) -> dict | None:
    """Célula que responde por (motor, nota): a do motor se tiver amostra, senão a de todos os motores; sem amostra
    mínima em nenhuma ⇒ None (INDISPONÍVEL)."""
    if nota is None:
        return None
    fx = faixa_de(nota)
    for m in (motor, TODOS):
        c = (tab.get(m) or {}).get(fx)
        if c and c["n"] >= N_MINIMO:
            return {**c, "motor": m, "faixa": fx}
    return None


def brier(pares: list[tuple[float, int]]) -> float | None:
    return sum((p - y) ** 2 for p, y in pares) / len(pares) if pares else None


def bss(pares: list[tuple[float, int]]) -> float | None:
    """Brier Skill Score contra a taxa-base da própria amostra; > 0 = melhor que dizer sempre a taxa-base."""
    if not pares:
        return None
    base = sum(y for _, y in pares) / len(pares)
    ref = base * (1 - base)
    return None if ref == 0 else 1 - brier(pares) / ref


def ece(pares: list[tuple[float, int]], bins: int = 5) -> float | None:
    if not pares:
        return None
    tot = 0.0
    for b in range(bins):
        cel = [(p, y) for p, y in pares if b / bins <= p < (b + 1) / bins or (b == bins - 1 and p == 1.0)]
        if cel:
            tot += len(cel) / len(pares) * abs(sum(p for p, _ in cel) / len(cel) - sum(y for _, y in cel) / len(cel))
    return tot


def avaliar(tab: dict, rotulos: list[dict], base_treino: float) -> dict:
    """Mede, num conjunto que NÃO ajustou a tabela: Brier da nota verbalizada (nota/10), da taxa-base e da calibrada."""
    verb, cal, base, sem = [], [], [], 0
    for r in rotulos:
        y = int(bool(r["alto_verificado"]))
        c = prob(tab, r["motor"], r["nota"])
        if c is None:
            sem += 1
            continue
        verb.append((r["nota"] / 10, y))
        cal.append((c["p"], y))
        base.append((base_treino, y))
    return {"n": len(cal), "sem_celula": sem, "altos_verdadeiros": sum(y for _, y in cal),
            "brier_verbalizada": brier(verb), "brier_taxa_base": brier(base), "brier_calibrada": brier(cal),
            "ece_verbalizada": ece(verb), "ece_calibrada": ece(cal)}


def duas_fases(con, conjuntos: tuple[str, ...] = ("treino", "validacao"), draws: int = 20000) -> dict | None:
    """P(risco alto confirmado na FONTE | motor fraco disse alto), pelos dois estratos do Opus. None sem amostra."""
    def conta(nivel_a, nivel_d, alto_antes):
        ps = [p for p in pares_unicos(con, nivel_a, nivel_d, conjuntos) if p[0] == alto_antes]
        return len(ps), sum(p[1] for p in ps)

    n01, k01 = conta(0, 1, 1)                              # fraco alto → Opus manteve alto?
    n_oa, k_oa = conta(1, 2, 1)                            # Opus alto → fonte confirmou?
    n_ob, k_ob = conta(1, 2, 0)                            # Opus baixo → fonte achou alto?
    if n01 < N_MINIMO or n_oa < N_MINIMO or n_ob < N_MINIMO:
        return {"indisponivel": f"amostra insuficiente (fraco→Opus {n01}, Opus alto→fonte {n_oa}, Opus baixo→fonte {n_ob}; "
                                f"mínimo {N_MINIMO} em cada)"}
    rnd = random.Random(11)
    xs = sorted((lambda q, a, b: q * a + (1 - q) * b)(rnd.betavariate(k01 + .5, n01 - k01 + .5),
                                                      rnd.betavariate(k_oa + .5, n_oa - k_oa + .5),
                                                      rnd.betavariate(k_ob + .5, n_ob - k_ob + .5)) for _ in range(draws))
    return {"p": round(sum(xs) / draws, 4), "lo": round(xs[int(.025 * draws)], 4), "hi": round(xs[int(.975 * draws) - 1], 4),
            "fraco_alto_opus_manteve": [k01, n01], "opus_alto_fonte_confirmou": [k_oa, n_oa],
            "opus_baixo_fonte_achou_alto": [k_ob, n_ob]}


def calibrar(con) -> dict:
    """Ajusta no treino, mede na validação, e grava a tabela de produção (treino+validação) em `calibracao.json`.
    O conjunto de teste não é tocado aqui."""
    treino = ledger.rotulos(con, ("treino",))
    valid = ledger.rotulos(con, ("validacao",))
    base = sum(r["alto_verificado"] for r in treino) / len(treino) if treino else 0.0
    rot_opus = _rotulos_do_opus(con, ("treino", "validacao"))
    out = {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "n_treino": len(treino), "n_validacao": len(valid),
           "validacao": avaliar(tabela(treino), valid, base),
           "motores_fracos": tabela(treino + valid),
           "opus_resumo": tabela(rot_opus).get("claude-opus:resumo", {}),
           "fonte_primaria_duas_fases": duas_fases(con)}
    out["certificadas"] = certificadas(out)
    (config.dados() / "calibracao.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def pares_unicos(con, nivel_a: int, nivel_d: int, conjuntos) -> list[tuple[int, int, int]]:
    """Um par por PROCESSO — (alto antes, alto depois, nota antes) da conferência mais recente. Processo reconferido
    deixa pares antigos no ledger (nada é apagado); contar todos pesaria o mesmo processo mais de uma vez."""
    marc = ",".join("?" * len(conjuntos))
    ult: dict[str, tuple] = {}
    for ns, aa, ad, na in con.execute(
            f"SELECT numero_sei, alto_antes, alto_depois, nota_antes FROM conferencia WHERE nivel_antes=? AND "
            f"nivel_depois=? AND conjunto IN ({marc}) ORDER BY depois_id, antes_id", (nivel_a, nivel_d, *conjuntos)):
        ult[ns] = (aa, ad, na)
    return list(ult.values())


def _rotulos_do_opus(con, conjuntos) -> list[dict]:
    return [{"motor": "claude-opus:resumo", "nota": na, "alto_verificado": ad}
            for _, ad, na in pares_unicos(con, config.NIVEL_RESUMO, config.NIVEL_FONTE, conjuntos)]


def certificadas(cal: dict, alfa: float = config.ALFA_FP) -> list[dict]:
    """Faixas 'risco alto' em que o limite INFERIOR (95%) de P(confirma) fica ≥ 1−alfa: só essas poderiam sair como
    risco alto sem ir à fonte (decidir só com garantia, senão escalar — Jung et al. 2025; Angelopoulos et al. 2021)."""
    out = []
    grupos = {**cal.get("motores_fracos", {}), "claude-opus:resumo": cal.get("opus_resumo", {})}
    for motor, fxs in grupos.items():
        c = fxs.get("alta")
        if c and c["n"] >= N_MINIMO and c["lo"] >= 1 - alfa:
            out.append({"motor": motor, **c})
    return out


def carregar() -> dict | None:
    try:
        return json.loads((config.dados() / "calibracao.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def confianca(modelo: str | None, nota: int | None, cal: dict | None = None) -> dict:
    """O que a casa pode dizer de um laudo, pela proveniência e pela calibração medida. Regra: risco alto só é
    VERIFICADO com prova primária; abaixo disso é 'a conferir na fonte', com a taxa medida de confirmação."""
    motor, nivel = ledger.motor_e_nivel(modelo)
    alto = nota is not None and nota >= config.ALTO
    if nivel == config.NIVEL_FONTE:
        return {"estado": "VERIFICADO_NA_FONTE", "nivel_prova": nivel, "p_confirma": None,
                "texto": "conferido na fonte primária (íntegra do SEI + OB do SIAFE)"}
    if nivel < 0 or not alto:
        return {"estado": None, "nivel_prova": nivel, "p_confirma": None, "texto": ""}
    cal = cal if cal is not None else carregar()
    c = None
    if cal:
        c = prob({"claude-opus:resumo": cal.get("opus_resumo", {})}, motor, nota) if nivel == config.NIVEL_RESUMO \
            else prob(cal.get("motores_fracos", {}), motor, nota)
    if c is None:
        return {"estado": "A_CONFERIR_NA_FONTE", "nivel_prova": nivel, "p_confirma": None,
                "texto": "risco alto a conferir na fonte primária (taxa de confirmação INDISPONÍVEL: sem amostra)"}
    quem = "do Opus sobre o resumo" if nivel == config.NIVEL_RESUMO else \
        f"de {motor}" if c["motor"] == motor else "de modelos de volume"
    juiz = "na fonte primária" if nivel == config.NIVEL_RESUMO else "pela conferência"
    return {"estado": "A_CONFERIR_NA_FONTE", "nivel_prova": nivel, "p_confirma": c["p"], "ic95": [c["lo"], c["hi"]],
            "n": c["n"], "texto": f"risco alto a conferir na fonte primária: de {c['n']} laudos altos {quem} conferidos "
                                  f"{juiz}, {c['k']} seguiram altos ({c['p'] * 100:.0f}%, IC 95% "
                                  f"{c['lo'] * 100:.0f}–{c['hi'] * 100:.0f}%)"}
