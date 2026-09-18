# -*- coding: utf-8 -*-
"""Quem foi CANDIDATO e está na FOLHA DA PREFEITURA do Rio — cruzamento por eleição.

Pedido do dono (2026-08-05): "de um jeito de saber quem foi candidato em 2020, 2022 e 2024 pra
bater com as folhas de pagamento da prefeitura… e das eleições anteriores se possível, batendo com
a folha de 2021 em diante (período de governo do Eduardo Paes / Eduardo Cavaliere)". E, logo
depois: **"apenas a folha da prefeitura"** — a Câmara fica fora deste produto.

FONTES
  · candidaturas — `tse_candidatura` (dados abertos do TSE, `consulta_cand_{ano}.zip`, arquivo do
    RJ). Coletadas por `tse_candidatos.coletar`, que a partir de 2026-08-05 usa como universo os
    **263.989 nomes da folha da Prefeitura** (antes só a Câmara, o que explicava 142 candidaturas
    no acervo inteiro). Série: 2012, 2014, 2016, 2018, 2020, 2022, 2024.
  · folha — `pcrj_folha_pref` (ArquivoTC), 12,1 mi de linhas, competências 2020-12 a 2026-05.

O QUE O CRUZAMENTO É, E O QUE NÃO É
  O CPF vem mascarado no TSE e a folha da Prefeitura **não traz CPF nenhum**: o casamento é por
  NOME normalizado, e portanto é INDÍCIO, nunca prova. A trava de prevalência usada aqui é a
  mesma da perícia de benefícios: só entra quem tem **uma única matrícula** com aquele nome na
  folha. Isso reduz o homônimo dentro da folha; não elimina o homônimo na população.

AS TRÊS SEPARAÇÕES QUE MUDAM O SENTIDO DO NÚMERO
  1. **Janela do mandato.** Eleito em 2012 exerce de 2013 a 2016 — folha de 2021 em diante não
     diz nada sobre aquele mandato. Contar "presença na folha ≥2021" como sobreposição inflou o
     resultado de 8 para 23 chefes de executivo na primeira medição desta análise; a janela certa
     é jan/(ano+1) a dez/(ano+4).
  2. **Aposentado não acumula.** FUNPREVI e `tipo_folha` PREV* são inativos e pensionistas: o
     art. 38 da CF trata do servidor em ATIVIDADE. São 18 dos 131 casos brutos.
  3. **Prefeito ≠ vereador.** Art. 38, II: investido no mandato de Prefeito, o servidor é
     **afastado do cargo**, facultada a opção pela remuneração. Art. 38, III: vereador, **havendo
     compatibilidade de horários**, percebe as vantagens do cargo e o subsídio; não havendo,
     afasta-se. Estar na folha não prova irregularidade em nenhum dos dois — prova que há o que
     conferir: houve afastamento formal? qual remuneração foi optada? houve acúmulo de subsídio?

O QUE JÁ FOI CONFERIDO NOS TRÊS COM MANDATO VIGENTE (2025-2028), em 2026-08-05
  A remuneração NÃO cai quando o mandato começa — os três seguem em folha `NORMAL`, com valor
  igual ou maior:
      Prefeito de São Pedro da Aldeia (Guarda Municipal)  2024: R$ 4.314,91  →  2025-26: R$ 4.647,21
      Vice-prefeita de Barra Mansa (Guarda Municipal)     2024: R$ 4.571,19  →  2025-26: R$ 4.658,75
      Prefeito de Quissamã (Comlurb)                      2024: R$ 2.848,60  →  2025-26: R$ 3.033,56
  Isso não fecha o caso em nenhum sentido: o art. 38, II FACULTA ao afastado optar pela
  remuneração do cargo efetivo, então receber não é, por si, irregular. O que a folha não diz é se
  houve **afastamento** — ela registra pagamento, não frequência.

  A busca nominal no Diário Oficial do Município (`doweb.coletar_termo`, 2024+) **não** trouxe ato
  de afastamento/licença/cessão para nenhum dos três. **Isso não é prova de que não houve**: a
  coleta pega 2 páginas por termo e o texto vem em nível de página, cheio de listas — é a mesma
  disciplina da família 22 do catálogo (o gate mede o que se capturou, não o que existe).

  Próximo passo, e é documental: ficha funcional, ato de afastamento e folha de frequência dos
  três — por requisição, não por OSINT.
"""
from __future__ import annotations

import argparse
import sqlite3

from compliance_agent.pcrj import db as _db

# jan do ano seguinte à eleição até dez do quarto ano — a janela do mandato
_SQL = """
SELECT t.nome_tse, t.ano, t.cargo, t.municipio, t.partido,
       COUNT(DISTINCT p.competencia) AS meses_no_mandato,
       MIN(p.competencia) AS c_ini, MAX(p.competencia) AS c_fim,
       MAX(p.orgao) AS orgao,
       COUNT(DISTINCT p.matricula) AS n_matriculas
FROM tse_candidatura t
JOIN pcrj_folha_pref p ON p.nome_norm = t.nome_norm
WHERE t.eleito = ?
  AND (? = 0 OR t.outra_cidade = 1)
  AND p.orgao NOT LIKE '%Funprevi%' AND p.tipo_folha NOT LIKE 'PREV%'
  AND p.competencia >= (CAST(t.ano AS INT) + 1) || '01'
  AND p.competencia <= (CAST(t.ano AS INT) + 4) || '12'
  AND p.competencia >= ?
GROUP BY t.nome_tse, t.ano, t.cargo, t.municipio, t.partido
HAVING n_matriculas = 1
ORDER BY (t.cargo LIKE 'PREFEITO%' OR t.cargo LIKE 'VICE%') DESC,
         meses_no_mandato DESC, t.ano DESC
"""

CHEFIA = ("PREFEITO", "VICE-PREFEITO")


def cruzar(*, eleitos: bool = True, so_outra_cidade: bool = True,
           desde: str = "202101", db_path=None) -> list[dict]:
    """Pessoas cuja candidatura casa com a folha ATIVA da Prefeitura DENTRO do mandato.

    `desde` recorta o início da folha — o padrão 202101 é a gestão Paes/Cavaliere, que é o que o
    dono pediu (a base tem 202012, um mês antes).
    """
    con = _db.conectar(db_path)
    con.row_factory = sqlite3.Row
    try:
        rs = con.execute(_SQL, (1 if eleitos else 0, 1 if so_outra_cidade else 0, desde)).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rs]


def resumo(linhas: list[dict]) -> dict:
    chefes = [r for r in linhas if str(r["cargo"]).upper().startswith(CHEFIA)]
    return {"pessoas": len(linhas), "chefia_executivo": len(chefes),
            "legislativo": len(linhas) - len(chefes),
            "municipios": len({r["municipio"] for r in linhas})}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--todos-candidatos", action="store_true",
                    help="não só os ELEITOS (o eleito é o sinal forte; o candidato é contexto)")
    ap.add_argument("--incluir-rio", action="store_true",
                    help="inclui candidatura no próprio Rio (o padrão é só OUTRO município)")
    ap.add_argument("--desde", default="202101", help="competência inicial da folha (AAAAMM)")
    ap.add_argument("--limite", type=int, default=40)
    a = ap.parse_args()

    linhas = cruzar(eleitos=not a.todos_candidatos, so_outra_cidade=not a.incluir_rio,
                    desde=a.desde)
    r = resumo(linhas)
    print(f"pessoas: {r['pessoas']} · chefia do executivo: {r['chefia_executivo']} "
          f"· legislativo: {r['legislativo']} · municípios: {r['municipios']}")
    print("indício por NOME (TSE mascara CPF; a folha da Prefeitura não tem CPF) — "
          "só nomes com matrícula única na folha\n")
    for x in linhas[:a.limite]:
        print(f"{x['ano']} {x['cargo'][:14]:14} {x['municipio'][:20]:20} {x['partido'][:8]:8} "
              f"{x['meses_no_mandato']:2d}m ({x['c_ini']}→{x['c_fim']}) "
              f"{str(x['orgao'])[:32]:32} {x['nome_tse'][:32]}")


if __name__ == "__main__":
    main()
