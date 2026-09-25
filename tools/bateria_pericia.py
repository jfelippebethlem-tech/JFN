"""Cobertura da BATERIA de perícia — quais dos 24 testes REALMENTE rodam, e o que falta aos demais.

⚠️ NÃO CONFUNDIR com `compliance_agent.reporting.cobertura_pericia`, que mede coisa diferente:
**quanto do acervo já recebeu juízo** (quantos processos foram periciados). Este módulo mede
**quantos dos testes da bateria têm insumo para rodar**. Um acervo pode estar 100% periciado e
mesmo assim ter 83% dos itens sem exame — que é exatamente o caso.

Eu criei este módulo com o nome do outro e uma rota com o mesmo caminho; o gate de inventário de
rotas pegou a colisão antes do push. Nomes distintos para medidas distintas.

POR QUE ISTO EXISTE
-------------------
A perícia de contratos (`pericia_fornecedor`) aplica 24 testes a cada fornecedor e grava o
resultado. Olhando o painel, ela parece viva: 31.017 fornecedores periciados, 27.846 com indício,
graus atribuídos.

Medido em 31/08/2026: **620.108 dos 744.259 itens (83,3%) são INDISPONÍVEL**, e **20 dos 24
testes estão 95%+ indisponíveis** — ou seja, nunca rodam de verdade. E **nenhum item chega a
CONFIRMADO em todo o acervo**: `n_confirmados` é zero nas 31.017 linhas.

O sistema é **honesto** — cada indisponível traz o motivo por extenso ("Teste não roda: falta a
data-base confirmada na CCT do caso. INDISPONÍVEL ≠ ..."). O problema não é o código: é o
**insumo**. Este módulo mede isso e nomeia o que falta, porque "83% indisponível" não é
diagnóstico — é sintoma. O diagnóstico é *qual captura destrava qual teste*.

O QUE A MEDIÇÃO MOSTRA
----------------------
Os 4 testes que funcionam (T01 three-way match, T02 OB anulada computada como paga, T07
duplicidade por competência, T08 continuidade temporal) usam **dado do SIAFE** — ordem bancária,
competência, valor. Está em casa.

Os 20 que não funcionam pedem **documento do contrato**: planilha de custos, CCT, retenções de
INSS e IR, garantia contratual, conta-vinculada, saldo apurado pelo órgão. Isso mora no
**processo administrativo**, não no sistema orçamentário.

É a mesma lacuna que a leitura de processos SEI ataca. A perícia não precisa de mais regras:
precisa dos autos.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from compliance_agent.pcrj.universo import conectar

LIMIAR_MORTO = 0.95      # 95%+ indisponível = o teste não roda de verdade
LIMIAR_NAO_DISCRIMINA = 0.50   # marca metade ou mais dos apurados = não ordena fila
LIMIAR_INERTE = 0.0            # roda, mas nunca aponta nada

# Agrupa os motivos de indisponibilidade pelo INSUMO que os resolveria. "83% indisponível" não é
# diagnóstico — é sintoma. O diagnóstico é *qual captura destrava quantos testes*, e é isso que
# permite priorizar coleta em vez de escrever mais regra.
INSUMOS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("planilha de custos do contrato",
     "Módulos 1, 2 e 6 da planilha, e as versões original e repactuada",
     ("planilha", "módulo", "modulo", "submódulo", "submodulo", "grupo a")),
    ("convenção coletiva (CCT) do caso",
     "data-base, percentual de reajuste e piso da categoria",
     ("cct", "data-base", "piso")),
    ("documento fiscal digitalizado (OCR do SEI)",
     "retenções de INSS e IR, valor bruto da NF, ISS municipal",
     ("inss", "ir ", "retenç", "bruto da nf", "iss")),
    ("acervo SEI por competência",
     "comprovantes trabalhistas e cláusula/comprovante de garantia",
     ("sei", "comprovante", "garantia", "competência")),
    ("relatório derivado em texto",
     "campo `relatorio_texto` do processo",
     ("relatorio_texto", "relatório derivado")),
    ("datas de aditivo e de pleito",
     "cronologia das prorrogações e repactuações",
     ("aditivo", "prorrogação", "pleito", "salto de reajuste")),
    ("saldo apurado pelo órgão", "posição de créditos e débitos do contrato", ("saldo",)),
    ("registro de glosas", "quais glosas foram aplicadas e sobre o quê", ("glosa",)),
    ("valores do contrato", "`valor_inicial` e `valor_global`", ("valor_inicial", "valor_global")),
)


def _insumo_do_motivo(motivo: str) -> str:
    """Qual captura resolveria este motivo. Motivo que não casa nada vira 'não classificado' —
    buraco nomeado, nunca atribuído ao insumo errado por conveniência."""
    m = str(motivo or "").lower()
    for nome, _, chaves in INSUMOS:
        if any(k in m for k in chaves):
            return nome
    return "não classificado"


def _classificar(status: str) -> str:
    s = str(status or "").upper()
    if s.startswith("INDISPON"):
        return "INDISPONIVEL"
    if s.startswith("CONFIRM"):
        return "CONFIRMADO"
    if s.startswith("INDIC"):
        return "INDICIO"
    if s.startswith("AFAST"):
        return "AFASTADO"
    return s or "?"


def cobertura(db_path=None, limite: int | None = None) -> dict:
    """Mede, por teste de perícia, quantos itens rodaram e quantos ficaram sem insumo."""
    con = conectar(db_path or "data/compliance.db")
    try:
        sql = "SELECT achados_json FROM pericia_fornecedor WHERE achados_json IS NOT NULL"
        if limite:
            sql += f" LIMIT {int(limite)}"
        linhas = con.execute(sql).fetchall()
    finally:
        con.close()

    por_teste: dict[str, Counter] = defaultdict(Counter)
    titulo: dict[str, str] = {}
    motivo: dict[str, Counter] = defaultdict(Counter)
    periciados = 0
    for (aj,) in linhas:
        try:
            itens = json.loads(aj)
        except (TypeError, ValueError):
            continue
        periciados += 1
        for it in itens:
            cod = str(it.get("codigo") or "?")
            st = _classificar(it.get("status"))
            por_teste[cod][st] += 1
            titulo.setdefault(cod, str(it.get("titulo") or ""))
            if st == "INDISPONIVEL":
                m = str(it.get("motivo") or it.get("detalhe") or it.get("evidencia") or "")
                if m:
                    motivo[cod][m[:120]] += 1

    testes = []
    for cod, cnt in sorted(por_teste.items()):
        total = sum(cnt.values())
        indisp = cnt.get("INDISPONIVEL", 0)
        frac = indisp / total if total else None
        m = motivo[cod].most_common(1)
        testes.append({
            "codigo": cod, "titulo": titulo.get(cod, ""),
            "itens": total, "indisponivel": indisp,
            "fracao_indisponivel": frac,
            "roda": bool(frac is not None and frac < LIMIAR_MORTO),
            "confirmado": cnt.get("CONFIRMADO", 0),
            "indicio": cnt.get("INDICIO", 0),
            "afastado": cnt.get("AFASTADO", 0),
            "motivo_da_falta": m[0][0] if m else None,
        })
    # RODAR NÃO BASTA. Um teste que aponta 85% dos apurados não ordena fila nenhuma, e um que
    # nunca aponta nada não acrescenta. Medido nos 4 que rodam: T01 tem 0 indícios em 31.003
    # apurados (inerte) e T08 tem 85,1% (não discrimina). Úteis de verdade: T02 (17,2%) e
    # T07 (18,8%) — dois, de vinte e quatro.
    for x in testes:
        apurados = x["indicio"] + x["afastado"] + x["confirmado"]
        x["apurados"] = apurados
        taxa = (x["indicio"] + x["confirmado"]) / apurados if apurados else None
        x["taxa_de_apontamento"] = taxa
        # taxa calculada sobre punhado de itens não sustenta veredito de utilidade: T04 tem 13
        # apurados de 31.017 e "aponta 100%". Sem insumo, a utilidade não se avalia.
        x["taxa_confiavel"] = bool(apurados >= 100)
        if not x["roda"]:
            x["utilidade"] = "SEM INSUMO"
        elif taxa is None:
            x["utilidade"] = "INDISPONIVEL"
        elif taxa <= LIMIAR_INERTE:
            x["utilidade"] = "INERTE"
        elif taxa >= LIMIAR_NAO_DISCRIMINA:
            x["utilidade"] = "NAO DISCRIMINA"
        else:
            x["utilidade"] = "UTIL"
    # agrupa os testes mortos pelo insumo que os destravaria
    por_insumo: dict[str, list] = defaultdict(list)
    for t in testes:
        if not t["roda"] and t["motivo_da_falta"]:
            por_insumo[_insumo_do_motivo(t["motivo_da_falta"])].append(t["codigo"])
    detalhe = {nome: desc for nome, desc, _ in INSUMOS}
    insumos = sorted(
        ({"insumo": k, "detalhe": detalhe.get(k), "testes_que_destrava": len(v),
          "testes": sorted(v)} for k, v in por_insumo.items()),
        key=lambda x: -x["testes_que_destrava"])

    vivos = [t for t in testes if t["roda"]]
    mortos = [t for t in testes if not t["roda"]]
    uteis = [t for t in testes if t["utilidade"] == "UTIL"]
    tot_itens = sum(t["itens"] for t in testes)
    tot_ind = sum(t["indisponivel"] for t in testes)
    return {
        "periciados": periciados,
        "n_testes": len(testes),
        "testes_que_rodam": len(vivos),
        "testes_sem_insumo": len(mortos),
        # rodar não basta: o teste precisa APONTAR ALGO e não apontar quase tudo
        "testes_uteis": len(uteis),
        "uteis": [t["codigo"] for t in uteis],
        "inertes": [t["codigo"] for t in testes if t["utilidade"] == "INERTE"],
        "nao_discriminam": [t["codigo"] for t in testes if t["utilidade"] == "NAO DISCRIMINA"],
        "itens": tot_itens,
        "itens_indisponiveis": tot_ind,
        "fracao_indisponivel": tot_ind / tot_itens if tot_itens else None,
        "confirmados_no_acervo": sum(t["confirmado"] for t in testes),
        "testes": testes,
        "vivos": [t["codigo"] for t in vivos],
        "sem_insumo": [t["codigo"] for t in mortos],
        "insumos_que_destravam": insumos,
        "_nota": "INDISPONÍVEL é declarado pelo próprio teste, com motivo — o sistema é honesto. "
                 "O que falta é INSUMO, e ele mora no processo administrativo, não no SIAFE",
    }


if __name__ == "__main__":
    r = cobertura()
    print(f"periciados: {r['periciados']:,} · testes: {r['n_testes']} "
          f"({r['testes_que_rodam']} rodam, {r['testes_sem_insumo']} sem insumo, "
          f"{r['testes_uteis']} ÚTEIS)")
    print(f"   úteis: {r['uteis']} · inertes: {r['inertes']} · "
          f"não discriminam: {r['nao_discriminam']}")
    print(f"itens: {r['itens']:,} · indisponíveis: {r['itens_indisponiveis']:,} "
          f"({r['fracao_indisponivel']*100:.1f}%) · CONFIRMADOS no acervo inteiro: "
          f"{r['confirmados_no_acervo']}")
    print(f"\n{'teste':26s} {'apurados':>9s} {'indisp':>6s} {'aponta':>7s}  {'utilidade':16s} título")
    for t in r["testes"]:
        # a taxa vem SEMPRE acompanhada do denominador: T04 aponta "100%" sobre 13 itens de
        # 31.017, e ler isso como um teste que acha tudo seria o oposto da verdade
        ap = f"{t['taxa_de_apontamento']*100:5.1f}%" if t["taxa_de_apontamento"] is not None else "    —"
        print(f"  {t['codigo']:24s} {t['apurados']:9,} {t['fracao_indisponivel']*100:5.1f}% {ap:>7s}  "
              f"{t['utilidade']:16s} {t['titulo'][:34]}")
    print("\nO QUE DESTRAVA O QUÊ — ordem de retorno da captura:")
    for i in r["insumos_que_destravam"]:
        print(f"   {i['testes_que_destrava']:2d} teste(s) · {i['insumo']}")
        print(f"        {i['detalhe'] or ''}")
        print(f"        {', '.join(i['testes'])}")
