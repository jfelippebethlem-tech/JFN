# -*- coding: utf-8 -*-
"""Remuneração acima do TETO CONSTITUCIONAL (CF art. 37, XI) — com o PORQUÊ e classificação HONESTA.

Pedido do dono: quem recebeu acima do teto, **por quê**, e relatórios. O teto = subsídio dos Ministros do STF.
⚠ **Bruto > teto ≠ ilegal.** NÃO entram no teto (CF 37 §11 e jurisprudência STF/CNJ): **verbas indenizatórias**
(diárias, ajuda de custo, férias/licença-prêmio indenizadas, auxílios), **abono de permanência**, e os **rendimentos
recebidos acumuladamente (RRA / retroativos)** — pagamentos de exercícios anteriores num mês só (inflam o bruto mas
não são remuneração mensal). Acúmulo LÍCITO (art. 37 XVI) tem teto por vínculo. Por isso classificamos:

- **RRA/RETROATIVO_PROVAVEL** — bruto >> teto (≥ ~2,5×): provável pagamento acumulado, não supersalário mensal.
- **VERIFICAR** — bruto > teto mas sem detalhe de verbas: indenizatórias/abono podem explicar (não dá p/ concluir).
- **INDICIO_SUPERSALARIO** — com a composição, a **base do teto** (bruto − indenizatórias − abono − RRA) ainda > teto.

Honestidade: é **indício**, não acusação; cita a composição e a competência. `relatorio()` gera o porquê por servidor.
"""
from __future__ import annotations

# Subsídio Ministro do STF (CF 37 XI). ⚠ atualizado por lei — verificar o valor do exercício analisado.
TETO_CF_37_XI = 46366.19  # vigente em ref. 2025/2026 (confirmar reajuste anual)

# chaves de verba que NÃO contam para o teto (parciais, casefold)
_INDENIZATORIAS = ("indeniz", "diaria", "ajuda de custo", "auxilio", "ferias", "licenca premio",
                   "abono de permanencia", "abono permanencia", "terco de ferias", "1/3", "rra",
                   "retroativ", "exercicios anteriores", "verba indeniz")


def _cf(s: str) -> str:
    return (s or "").strip().casefold()


def _base_teto(bruto: float, componentes: dict | None) -> tuple[float, float]:
    """Retorna (base_para_teto, total_excluido). Sem componentes → base=bruto (não dá p/ excluir)."""
    if not componentes:
        return bruto, 0.0
    excl = 0.0
    for nome, val in componentes.items():
        if any(k in _cf(nome) for k in _INDENIZATORIAS):
            excl += float(val or 0)
    return max(0.0, bruto - excl), excl


def classificar(bruto: float, componentes: dict | None = None, teto: float = TETO_CF_37_XI) -> dict:
    """Classifica um registro de remuneração quanto ao teto. Honesto."""
    if bruto is None or bruto <= teto:
        return {"acima": False}
    base, excl = _base_teto(bruto, componentes)
    excesso = round(base - teto, 2)
    if bruto >= 2.5 * teto and not componentes:
        status, motivo = "RRA_RETROATIVO_PROVAVEL", ("bruto muito acima do teto (≥2,5×) — provável pagamento "
            "acumulado/retroativo (RRA) ou rescisório, NÃO remuneração mensal; não caracteriza supersalário")
    elif componentes is None:
        status, motivo = "VERIFICAR", ("acima do teto no BRUTO, mas sem detalhe de verbas — indenizatórias/abono "
            "de permanência podem explicar (não contam para o teto). Puxar a composição do contracheque")
    elif base > teto:
        status, motivo = "INDICIO_SUPERSALARIO", (f"mesmo excluindo verbas indenizatórias/abono (R$ {excl:,.2f}), "
            f"a base do teto (R$ {base:,.2f}) supera o teto em R$ {excesso:,.2f} — indício de supersalário a apurar")
    else:
        status, motivo = "DENTRO_APOS_EXCLUSAO", ("acima no bruto, mas dentro do teto após excluir verbas "
            "indenizatórias/abono — provavelmente regular")
    return {"acima": True, "status": status, "motivo": motivo, "teto": teto,
            "bruto": round(bruto, 2), "base_teto": round(base, 2), "excluido_indenizatorio": round(excl, 2),
            "excesso_sobre_teto": excesso}


def analisar(registros: list[dict], teto: float = TETO_CF_37_XI) -> dict:
    """registros: [{nome, orgao, cargo, vinculo, remuneracao_bruta, competencia, componentes?}]. Agrega + classifica."""
    achados = []
    for r in registros or []:
        cls = classificar(r.get("remuneracao_bruta"), r.get("componentes"), teto)
        if not cls.get("acima"):
            continue
        achados.append({**{k: r.get(k) for k in ("nome", "orgao", "cargo", "vinculo", "competencia")}, **cls})
    cont = {}
    for a in achados:
        cont[a["status"]] = cont.get(a["status"], 0) + 1
    achados.sort(key=lambda a: -a["excesso_sobre_teto"])
    return {"ok": True, "n_acima_bruto": len(achados), "por_status": cont,
            "n_indicio": cont.get("INDICIO_SUPERSALARIO", 0), "achados": achados,
            "leitura": _leitura(len(achados), cont, teto)}


def relatorio(reg: dict, teto: float = TETO_CF_37_XI) -> str:
    """Relatório (o PORQUÊ) de um servidor acima do teto."""
    cls = classificar(reg.get("remuneracao_bruta"), reg.get("componentes"), teto)
    if not cls.get("acima"):
        return f"{reg.get('nome')}: dentro do teto (R$ {reg.get('remuneracao_bruta', 0):,.2f} ≤ R$ {teto:,.2f})."
    L = [f"# Acima do teto — {reg.get('nome')}",
         f"- Órgão/cargo: {reg.get('orgao')} / {reg.get('cargo')} ({reg.get('vinculo')}) · competência {reg.get('competencia')}",
         f"- Bruto: **R$ {cls['bruto']:,.2f}** · teto (CF 37 XI): R$ {teto:,.2f} · excesso sobre o teto: R$ {cls['excesso_sobre_teto']:,.2f}",
         f"- **Classificação:** {cls['status']} — {cls['motivo']}"]
    comp = reg.get("componentes")
    if comp:
        L.append("- Composição (por quê):")
        for nome, val in sorted(comp.items(), key=lambda x: -float(x[1] or 0))[:12]:
            conta = "↘ não conta p/ teto" if any(k in _cf(nome) for k in _INDENIZATORIAS) else "conta"
            L.append(f"    - {nome}: R$ {float(val or 0):,.2f} ({conta})")
    L.append("> Indício, não prova. Bruto > teto pode ser legal (indenizatórias/abono/RRA/acúmulo). CF 37 XI/§11.")
    return "\n".join(L)


def _leitura(n: int, cont: dict, teto: float) -> str:
    if not n:
        return f"Nenhum registro acima do teto (R$ {teto:,.2f}) na amostra (ou base sem remuneração)."
    ind = cont.get("INDICIO_SUPERSALARIO", 0)
    rra = cont.get("RRA_RETROATIVO_PROVAVEL", 0)
    ver = cont.get("VERIFICAR", 0)
    return (f"**{n}** registro(s) com bruto acima do teto (R$ {teto:,.2f}). **Bruto > teto NÃO é ilegal por si** "
            f"(CF 37 §11): destes, **{rra}** são provável **RRA/retroativo** (não mensal), **{ver}** precisam da "
            f"**composição** (indenizatórias/abono podem explicar) e **{ind}** têm **indício de supersalário** "
            "(acima do teto mesmo excluindo indenizatórias). Puxar o contracheque detalhado para o 'porquê'.")
