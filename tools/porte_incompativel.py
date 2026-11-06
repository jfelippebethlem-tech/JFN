#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PORTE DECLARADO × DINHEIRO RECEBIDO — a empresa cabe no contrato que assinou?

PEDIDO DO DONO (2026-08-15): "ver compatibilidade dos contratos com o número de empregados das
empresas; contrato alto e empresa sem funcionário registrado é empresa de fachada".

**NÚMERO DE EMPREGADOS POR CNPJ NÃO É DADO PÚBLICO NO BRASIL** — e isto não é limitação desta base,
é da fonte. RAIS identificada e eSocial são protegidos por sigilo; o Novo CAGED público não traz
CNPJ; os dados abertos de CNPJ da Receita trazem porte, capital, natureza e QSA — não empregados.
(`collectors/caged.py` existe, mas é sobre ACUMULAÇÃO DE CARGO PÚBLICO, não quadro de empresa.)

O que se pode medir com dado oficial, e que responde à mesma pergunta por dois eixos independentes:

  1. **PORTE** — faixa de RECEITA BRUTA com teto em lei (abaixo);
  2. **ESTRUTURA SOCIETÁRIA** — nº de sócios no QSA da Receita e natureza jurídica.

Uma empresa de UM sócio que recebe R$ 28 milhões num ano de um único órgão não é uma afirmação sobre
folha de pagamento: é o retrato do que a empresa DECLARA ser.

O que existe é MELHOR para esta pergunta, e é oficial: o **porte** da Receita, presente em
`empresas_cadastro` para 36.192 empresas (100% preenchido). Porte não é opinião — é faixa de
RECEITA BRUTA ANUAL com teto em lei (LC 123/2006, art. 3º):

    · Microempresa .................. até R$    360.000,00/ano
    · Empresa de Pequeno Porte ...... até R$  4.800.000,00/ano

Uma ME que recebe R$ 78 milhões do Estado num ano está 217× acima do teto do próprio porte. Isso é
aritmética contra a lei, não suposição sobre quadro de pessoal.

**O QUE ISTO É E O QUE NÃO É.** É indício que pede exame; NÃO é prova de fachada. A hipótese
inocente mais forte, e comum: a empresa cresceu, deixou de ser ME de fato e **não comunicou a
Receita** — o registro fica velho sem que nada nele seja falso. Por isso a saída ordena por RAZÃO
(quantas vezes o teto) e mostra concentração por unidade pagadora: é a concentração, somada ao
salto de faturamento, que separa "cadastro desatualizado" de "empresa que só existe para um órgão".

RESSALVAS QUE INTEGRAM O RESULTADO:
  · o cadastro é uma foto de **2026-05**; para pagamento de 2022 o porte pode não ser o da época;
  · soma apenas OB com `status='Contabilizado'` — Anulado (R$ 3,79 bi) e Excluído (R$ 7,50 bi)
    NÃO são pagamento, e incluí-los inflava o total em R$ 147 mi só neste recorte;
  · agrega por CNPJ BÁSICO (8 dígitos), então matriz e filiais somam — que é o certo, porque o
    porte é da empresa, não do estabelecimento.

Uso:
    .venv/bin/python tools/porte_incompativel.py               # top 25
    .venv/bin/python tools/porte_incompativel.py --min-razao 10 --limite 50
    .venv/bin/python tools/porte_incompativel.py --ug 294200   # só uma unidade
"""
from __future__ import annotations

import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # padrão dos `tools/` da casa

# O FORMATADOR DA CASA, não um `_brl` local: número em real se escreve 1.234,56, e o gate tem
# catraca para isso (`test_moeda_padrao_brasileiro`) — que pegou este módulo com `{:,.2f}`
# americano antes do push. Mais uma cópia local do formatador seria a cópia divergente de sempre.
from compliance_agent.reporting.intel_base import moeda

DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"

# Códigos da tabela de natureza jurídica da Receita (só os que aparecem no acervo).
NATUREZA = {
    "2062": "Soc. Ltda", "2135": "Empresário Individual", "2240": "Soc. Simples Ltda",
    "2305": "EIRELI", "2054": "S.A. Fechada", "3999": "Associação", "2143": "Cooperativa",
}

# Naturezas que NÃO são sociedade empresária: contam dirigentes, não sócios.
NAO_EMPRESARIAL = {"3999", "2143", "3069", "3255", "3131"}

# LC 123/2006, art. 3º, I e II. FONTE ÚNICA — não duplicar noutro detector.
TETO_ANUAL = {
    "Microempresa": 360_000.00,
    "Empresa de Pequeno Porte": 4_800_000.00,
}


# SINAL TESTADO E DESCARTADO (2026-08-24): "capital social acima do teto de receita do porte".
# Parecia promissor — há microempresa com capital declarado de R$ 1,45 BILHÃO (4.028x o teto), e
# 2.133 das 24.178 ME/EPP do cadastro (8,8%) têm capital maior que a receita máxima do porte.
# NÃO VIRA LENTE, por duas razões medidas:
#   1. porte é definido por RECEITA, não por capital — capital alto com faturamento baixo é
#      legal e comum (holding, empresa recém-capitalizada). Sozinho não indica nada;
#   2. cruzando com quem recebeu >= R$ 1 mi do Estado, a prevalência é de **25,0%** (195 de 780).
#      Um em cada quatro não ordena fila — e quem recebe acima do teto esta função já marca.
# O campo `capital_social` continua no retorno como CONTEXTO de leitura, não como voto.
def _ano(data_emissao: str) -> str:
    """`data_emissao` do SIAFE é TEXTO `DD/MM/AAAA` — o ano são os 4 últimos, nunca `ORDER BY` cru."""
    m = re.search(r"/(\d{4})$", str(data_emissao or ""))
    return m.group(1) if m else ""


def incompativeis(con: sqlite3.Connection, min_razao: float = 1.0,
                  ug: str = "") -> list[dict]:
    """CNPJ×ano em que o pago supera o teto legal do porte declarado, do mais gritante ao menos."""
    porte = {str(b).zfill(8): (p, cap, rs, str(nat)) for b, p, cap, rs, nat in con.execute(
        "SELECT cnpj_basico, porte_txt, capital_social, razao_social, natureza_cod "
        "FROM empresas_cadastro")}
    # QSA da Receita: quantos sócios a empresa DECLARA. Não é quadro de pessoal — é estrutura.
    socios: dict = collections.Counter()
    for (v,) in con.execute("SELECT cnpj_basico FROM socios_receita"):
        d = re.sub(r"\D", "", str(v))
        if len(d) >= 8:
            socios[d[:8]] += 1

    sql = ("SELECT credor, data_emissao, valor, ug_emitente FROM ob_orcamentaria_siafe "
           "WHERE credor IS NOT NULL AND status='Contabilizado'")
    par: tuple = ()
    if ug:
        sql += " AND ug_emitente=?"
        par = (ug,)

    pago: dict = collections.defaultdict(float)
    ugs: dict = collections.defaultdict(collections.Counter)
    for credor, data, valor, ug_emit in con.execute(sql, par):
        dig = re.sub(r"\D", "", str(credor))
        if len(dig) < 14:
            continue
        ano = _ano(data)
        if not ano:
            continue
        chave = (dig[:8], ano)
        pago[chave] += (valor or 0)
        ugs[dig[:8]][str(ug_emit)] += (valor or 0)

    saida = []
    for (basico, ano), total in pago.items():
        info = porte.get(basico)
        if not info:
            continue
        porte_txt, capital, razao, natureza = info
        teto = TETO_ANUAL.get(porte_txt)
        if not teto or total <= teto:
            continue
        razao_teto = total / teto
        if razao_teto < min_razao:
            continue
        por_ug = ugs[basico]
        principal, valor_principal = por_ug.most_common(1)[0]
        saida.append({
            "cnpj_basico": basico, "razao_social": razao, "porte": porte_txt,
            "capital_social": capital or 0.0, "ano": ano, "pago": total,
            "teto": teto, "razao_teto": razao_teto,
            "ug_principal": principal,
            "socios": socios.get(basico, 0),
            "natureza": NATUREZA.get(natureza, natureza),
            # concentração: quanto do que a empresa recebeu do Estado vem de UMA unidade
            "concentracao_ug": (valor_principal / sum(por_ug.values())) if sum(por_ug.values()) else 0.0,
        })
    saida.sort(key=lambda x: -x["razao_teto"])
    return saida


def estrutura_magra(con: sqlite3.Connection, min_pago: float = 5_000_000.0,
                    max_socios: int = 2) -> list[dict]:
    """Empresa de estrutura MÍNIMA com dinheiro MÁXIMO — independe do teto do porte.

    POR QUE ESTA SEGUNDA LENTE EXISTE. `incompativeis()` só enxerga ME e EPP, os únicos portes com
    teto legal de receita. Medido em 2026-08-15: a **AMC SOLUÇÕES E SAÚDE** — R$ 60.772.657,25 de
    UMA só unidade, aberta em 2023, UM sócio, CNAE de "consultas médicas" sem aderência ao objeto —
    tem porte "Demais" e **passava batida**. O maior caso do dossiê escapava do detector porque a
    régua dependia de um teto que o porte dela não tem.

    Aqui a pergunta é outra e não precisa de teto: quantos sócios a empresa DECLARA ter, quanto
    recebeu, e de quantos pagadores. Estrutura mínima + valor alto + pagador único é o retrato de
    quem existe para um órgão só.
    """
    porte = {str(b).zfill(8): (p, cap, rs, str(nat)) for b, p, cap, rs, nat in con.execute(
        "SELECT cnpj_basico, porte_txt, capital_social, razao_social, natureza_cod "
        "FROM empresas_cadastro")}
    socios: dict = collections.Counter()
    for (v,) in con.execute("SELECT cnpj_basico FROM socios_receita"):
        d = re.sub(r"\D", "", str(v))
        if len(d) >= 8:
            socios[d[:8]] += 1

    pago: dict = collections.defaultdict(float)
    ugs: dict = collections.defaultdict(collections.Counter)
    for credor, valor, ug_emit in con.execute(
            "SELECT credor, valor, ug_emitente FROM ob_orcamentaria_siafe "
            "WHERE credor IS NOT NULL AND status='Contabilizado'"):
        d = re.sub(r"\D", "", str(credor))
        if len(d) < 14:
            continue
        pago[d[:8]] += (valor or 0)
        ugs[d[:8]][str(ug_emit)] += (valor or 0)

    saida = []
    for basico, total in pago.items():
        if total < min_pago:
            continue
        # ASSOCIAÇÃO/OSS NÃO TEM SÓCIO, TEM DIRIGENTE — e por isso aparecia com "1 sócio" gerindo
        # bilhões. Medido: 33 associações somavam R$ 9,94 bi nesta lente, todas falso positivo
        # estrutural. Contrato de gestão com OSS é outro instituto e pede outro exame.
        if str((porte.get(basico) or ("", 0, "", ""))[3]) in NAO_EMPRESARIAL:
            continue
        n_soc = socios.get(basico, 0)
        # zero sócios = QSA não coletado, não "empresa sem dono" — ausência de dado não é achado
        if not n_soc or n_soc > max_socios:
            continue
        info = porte.get(basico)
        if not info:
            continue
        porte_txt, capital, razao, natureza = info
        por_ug = ugs[basico]
        principal, valor_principal = por_ug.most_common(1)[0]
        saida.append({
            "cnpj_basico": basico, "razao_social": razao, "porte": porte_txt,
            "capital_social": capital or 0.0, "pago": total, "socios": n_soc,
            "natureza": NATUREZA.get(natureza, natureza), "ug_principal": principal,
            "n_ugs": len(por_ug),
            "concentracao_ug": valor_principal / sum(por_ug.values()),
            "por_socio": total / n_soc,
        })
    saida.sort(key=lambda x: -x["por_socio"])
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--min-razao", type=float, default=1.0,
                    help="só quem passou do teto ao menos N vezes (padrão: 1 = qualquer estouro)")
    ap.add_argument("--limite", type=int, default=25)
    ap.add_argument("--ug", default="", help="restringe a uma unidade pagadora")
    ap.add_argument("--estrutura", action="store_true",
                    help="segunda lente: estrutura societária mínima × dinheiro alto (pega os portes "
                         "'Demais', que não têm teto legal — a AMC estava aí)")
    ap.add_argument("--min-pago", type=float, default=5_000_000.0)
    ap.add_argument("--max-socios", type=int, default=2)
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    if a.estrutura:
        linhas = estrutura_magra(con, min_pago=a.min_pago, max_socios=a.max_socios)
        print(f"empresas com no máximo {a.max_socios} sócio(s) e mais de "
              f"R$ {moeda(a.min_pago)} recebidos: {len(linhas):,}")
        print(f"soma paga: R$ {moeda(sum(x['pago'] for x in linhas))}\n")
        print(f"{'R$/sócio':>17} {'pago':>17} {'sóc':>4} {'UGs':>4} {'conc':>5} {'porte':<12} empresa")
        for x in linhas[:a.limite]:
            print(f"R$ {moeda(x['por_socio']):>15} R$ {moeda(x['pago']):>15} {x['socios']:4d} "
                  f"{x['n_ugs']:4d} {100*x['concentracao_ug']:4.0f}% {x['porte'][:12]:<12} "
                  f"{x['razao_social'][:32]}")
        return 0
    linhas = incompativeis(con, min_razao=a.min_razao, ug=a.ug)
    total = sum(x["pago"] for x in linhas)
    print(f"CNPJ×ano com pagamento acima do teto legal do porte: {len(linhas):,}")
    print(f"soma paga (apenas OB Contabilizado): R$ {moeda(total)}")
    print("\nINDÍCIO, NÃO PROVA: porte desatualizado na Receita produz o mesmo sinal. "
          "A concentração por unidade é o que separa um caso do outro.\n")
    magros = [x for x in linhas if x["socios"] <= 2]
    print(f"com DOIS SÓCIOS OU MENOS: {len(magros):,} de {len(linhas):,} "
          f"· R$ {moeda(sum(x['pago'] for x in magros))}\n")
    print(f"{'razão':>6} {'pago no ano':>17} {'sócios':>6} {'natureza':<22} {'UG':>7} {'conc':>5}  empresa (ano)")
    for x in linhas[:a.limite]:
        print(f"{x['razao_teto']:5.0f}x R$ {moeda(x['pago']):>15} {x['socios']:6d} "
              f"{x['natureza']:<22} {x['ug_principal']:>7} {100*x['concentracao_ug']:4.0f}%  "
              f"{x['razao_social'][:30]} ({x['ano']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
