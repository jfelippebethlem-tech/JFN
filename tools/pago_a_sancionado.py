#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PAGAMENTO A EMPRESA SANCIONADA — o Estado pagou a quem estava proibido de contratar?

Nasceu de um caso concreto (2026-08-16): a **ENGE PRAT ENGENHARIA** foi SUSPENSA no CEIS em
25/03/2026 por inexecução contratual (Lei 8.666, art. 87, III), e o Estado do Rio lhe pagou
**R$ 11.981.914,19 em 47 OBs** depois disso — a primeira **no dia seguinte** à sanção. Se acontece
com uma, a pergunta é quantas.

**A CATEGORIA DA SANÇÃO É O QUE DECIDE, e misturá-las produz manchete falsa.** Somando tudo dá
R$ 582,86 mi; mas **MULTA não impede contratar** — é sanção pecuniária — e sozinha responde por
R$ 254,03 mi. "Publicação extraordinária da decisão" também não restringe. Excluídas as duas, sobram
**R$ 318.286.687,71 em 169 CNPJs**, que é o número que se sustenta.

Hierarquia do que cada sanção alcança (e por isso o `--grau`):
  · **Declaração de inidoneidade** (Lei 8.666 art. 87, IV / Lei 14.133 art. 156, IV) — toda a
    Administração Pública, qualquer ente. É a mais grave.
  · **Impedimento de licitar e contratar** (Lei 10.520 art. 7º / Lei 14.133 art. 156, III) — alcança
    o ente federativo que aplicou.
  · **Suspensão** (Lei 8.666 art. 87, III) — extensão CONTROVERTIDA: a leitura literal alcança só o
    órgão sancionador; TCU e STJ já estenderam a toda a Administração. O detector NÃO resolve a
    controvérsia — sinaliza para exame.
  · **Multa / publicação extraordinária** — não restringem o direito de contratar. Fora do corte.

RESSALVAS QUE INTEGRAM O RESULTADO:
  · sanção do CEIS/CNEP é FEDERAL; pagamento estadual a suspenso pelo órgão federal exige a análise
    jurídica acima — o achado é o FATO do pagamento na vigência, não a conclusão de ilicitude;
  · só OB `status='Contabilizado'` (anulada e excluída não são pagamento);
  · casa por CNPJ de 14 dígitos, e uma empresa pode ter várias sanções — vale a primeira vigente na
    data do pagamento.

Uso:
    .venv/bin/python tools/pago_a_sancionado.py                  # só o que restringe contratar
    .venv/bin/python tools/pago_a_sancionado.py --grau inidoneidade
    .venv/bin/python tools/pago_a_sancionado.py --tudo           # inclui multa (para conferência)
"""
from __future__ import annotations

import argparse
import collections
import datetime
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compliance_agent.reporting.intel_base import moeda

DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"

# O que RESTRINGE o direito de contratar. Multa e publicação extraordinária ficam de fora.
RESTRINGE = re.compile(r"impedimento|suspens|inidone|proibi", re.I)
GRAUS = {
    "inidoneidade": re.compile(r"inidone", re.I),
    "impedimento": re.compile(r"impedimento|proibi", re.I),
    "suspensao": re.compile(r"suspens", re.I),
}


def _data(s) -> datetime.date | None:
    """Aceita `AAAA-MM-DD` e `DD/MM/AAAA` — o SIAFE guarda data como TEXTO."""
    try:
        s = str(s)[:10]
        if "/" in s:
            d, m, a = s.split("/")
            return datetime.date(int(a), int(m), int(d))
        a, m, d = s.split("-")
        return datetime.date(int(a), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def pagos_durante_sancao(con: sqlite3.Connection, restringe_apenas: bool = True,
                         grau: str = "") -> list[dict]:
    """Pagamentos feitos enquanto havia sanção VIGENTE para aquele CNPJ."""
    sanc: dict = {}
    for cad, doc, nome, cat, ini, fim, orgao, fund in con.execute(
            "SELECT cadastro, cpf_cnpj, nome, categoria, data_inicio, data_fim, orgao, fundamentacao "
            "FROM sancoes_federais"):
        d = re.sub(r"\D", "", str(doc))
        if len(d) != 14:
            continue
        di = _data(ini)
        if not di:
            continue
        cat = (cat or "?").strip()
        if restringe_apenas and not RESTRINGE.search(cat):
            continue
        if grau and not GRAUS[grau].search(cat):
            continue
        sanc.setdefault(d, []).append((cad, nome, cat, di, _data(fim), orgao, fund))

    agr: dict = collections.defaultdict(lambda: {"pago": 0.0, "obs": 0, "primeira": None})
    for credor, data, valor in con.execute(
            "SELECT credor, data_emissao, valor FROM ob_orcamentaria_siafe "
            "WHERE status='Contabilizado' AND credor IS NOT NULL"):
        d = re.sub(r"\D", "", str(credor))
        if d not in sanc:
            continue
        dp = _data(data)
        if not dp:
            continue
        for cad, nome, cat, di, df, orgao, fund in sanc[d]:
            if di <= dp and (df is None or dp <= df):
                k = (d, nome, cat, di, orgao)
                a = agr[k]
                a["pago"] += (valor or 0)
                a["obs"] += 1
                if a["primeira"] is None or dp < a["primeira"]:
                    a["primeira"] = dp
                break

    saida = [{"cnpj": k[0], "nome": k[1], "categoria": k[2], "inicio": k[3], "orgao": k[4],
              **v} for k, v in agr.items()]
    saida.sort(key=lambda x: -x["pago"])
    return saida


def sucessao_societaria(con: sqlite3.Connection, so_administrador: bool = True,
                        temporal: bool = True) -> list[dict]:
    """Empresa NÃO sancionada que recebe do Estado e tem sócio vindo de empresa SANCIONADA.

    O padrão é clássico: empresa punida é substituída por outra, com a mesma gente. O que impede
    isso de virar acusação barata é a PREVALÊNCIA — sinal que marca meio acervo não discrimina nada
    (nesta casa, "um só sócio" foi descartado por atingir 54,9%).

    Medido em 2026-08-17 sobre as 9.269 empresas que recebem do Estado e têm QSA conhecido:
      · sócio comum em qualquer qualificação ....... 315 (3,4%)
      · ADMINISTRADOR na sancionada E na nova ...... 158 (1,7%)

    3,4% já discrimina; 1,7% é o corte forte, e é o padrão da função. Sócio minoritário de grande
    grupo entra no primeiro e sai no segundo — que é exatamente a diferença entre coincidência de
    participação e continuidade de comando.

    **2026-08-23 — A ORDEM DOS FATOS FALTAVA, e ela É o achado.** A prevalência acima estava certa
    e mesmo assim o detector errava: ele não checava QUANDO a punição começou. Medido: dos 178
    casos, **146 (82%)** tinham a sanção iniciando DEPOIS de o sócio já estar na empresa nova —
    não há fuga de uma punição que ainda não existia. O valor somado caiu de **R$ 1,02 bi para
    R$ 39,28 mi** (26× de inflação) e as empresas, de 178 para **32**.

    O caso que abriu isso foi a DIMPI (R$ 181,26 mi do Estado): os dois sócios entraram em
    19/01 e 19/02/2026, e a punição da origem (RC Gestão) só veio em **13/05/2026** — e é
    suspensão perante a ENTIDADE SANCIONADORA (Lei 13.303, art. 83, III), que nem alcança o RJ.

    `temporal=False` mantém o corte antigo para conferência. Sem data de entrada, o caso NÃO entra:
    ausência de dado não vira presunção de sucessão.
    """
    ADM = re.compile(r"administrador", re.I)
    sanc_b = set()
    # A ORDEM DOS FATOS É O ACHADO. Guardar o INÍCIO da sanção, não só quem foi sancionado:
    # "sócio saiu da punida e foi para a nova" só é sucessão se a punição veio ANTES da entrada.
    sanc_ini: dict = {}
    for doc, cat, inicio in con.execute(
            "SELECT cpf_cnpj, categoria, data_inicio FROM sancoes_federais"):
        d = re.sub(r"\D", "", str(doc))
        if len(d) == 14 and RESTRINGE.search(str(cat or "")):
            sanc_b.add(d[:8])
            if inicio and (d[:8] not in sanc_ini or str(inicio) < sanc_ini[d[:8]]):
                sanc_ini[d[:8]] = str(inicio)

    de_sancionada: dict = {}
    for b, doc, nome, qual in con.execute(
            "SELECT cnpj_basico, doc_socio, nome_socio, qualificacao_txt FROM socios_receita"):
        if not doc or str(b).zfill(8) not in sanc_b:
            continue
        if so_administrador and not ADM.search(str(qual or "")):
            continue
        de_sancionada.setdefault(str(doc), (nome, str(b).zfill(8)))

    alvo: dict = collections.defaultdict(list)
    for b, doc, nome, qual, entrada in con.execute(
            "SELECT cnpj_basico, doc_socio, nome_socio, qualificacao_txt, data_entrada "
            "FROM socios_receita"):
        bb = str(b).zfill(8)
        if bb in sanc_b or str(doc) not in de_sancionada:
            continue
        if so_administrador and not ADM.search(str(qual or "")):
            continue
        # FILTRO TEMPORAL. Medido em 2026-08-23: sem ele, 146 dos 178 casos (82%) tinham a sanção
        # começando DEPOIS de o sócio já estar na empresa nova — a ordem dos fatos desmentia a
        # hipótese que o detector nomeia. O caso que abriu isso foi a DIMPI: os dois sócios
        # entraram em 01-02/2026 e a punição da origem (RC Gestão) só veio em 13/05/2026. Não há
        # fuga quando a punição ainda não existia.
        origem = de_sancionada[str(doc)][1]
        inicio = sanc_ini.get(origem)
        e = str(entrada or "")
        entrada_iso = f"{e[:4]}-{e[4:6]}-{e[6:8]}" if len(e) == 8 else ""
        if temporal and (not inicio or not entrada_iso or inicio >= entrada_iso):
            continue
        alvo[bb].append((nome, str(doc), origem))
    if not alvo:
        return []

    pago: dict = collections.defaultdict(float)
    obs: dict = collections.Counter()
    for credor, valor in con.execute(
            "SELECT credor, valor FROM ob_orcamentaria_siafe WHERE status='Contabilizado'"):
        d = re.sub(r"\D", "", str(credor))
        if len(d) >= 8 and d[:8] in alvo:
            pago[d[:8]] += (valor or 0)
            obs[d[:8]] += 1
    nomes = {str(b).zfill(8): rs for b, rs in
             con.execute("SELECT cnpj_basico, razao_social FROM empresas_cadastro")}
    saida = [{"cnpj_basico": b, "razao_social": nomes.get(b, "?"), "pago": v, "obs": obs[b],
              "socios": alvo[b][:3]} for b, v in pago.items()]
    saida.sort(key=lambda x: -x["pago"])
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tudo", action="store_true",
                    help="inclui multa e publicação — que NÃO restringem contratar (conferência)")
    ap.add_argument("--grau", choices=sorted(GRAUS), default="")
    ap.add_argument("--limite", type=int, default=25)
    ap.add_argument("--sucessao", action="store_true",
                    help="lente 2: empresa NÃO sancionada com sócio vindo de sancionada")
    ap.add_argument("--amplo", action="store_true",
                    help="com --sucessao: aceita qualquer qualificação (3,4%%) em vez de só administrador (1,7%%)")
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    if a.sucessao:
        linhas = sucessao_societaria(con, so_administrador=not a.amplo)
        corte = "qualquer qualificação (prevalência 3,4%)" if a.amplo else "ADMINISTRADOR em ambas (prevalência 1,7%)"
        print(f"empresas NÃO sancionadas que recebem do Estado, com sócio vindo de SANCIONADA")
        print(f"  corte: {corte}")
        print(f"  {len(linhas)} empresas · R$ {moeda(sum(x['pago'] for x in linhas))}\n")
        print(f"{'pago':>18} {'OBs':>5}  empresa · sócio em comum")
        for x in linhas[:a.limite]:
            s0 = x["socios"][0] if x["socios"] else ("?", "", "")
            print(f"R$ {moeda(x['pago']):>15} {x['obs']:5d}  {x['razao_social'][:30]:30} · {s0[0][:26]}")
        return 0
    linhas = pagos_durante_sancao(con, restringe_apenas=not a.tudo, grau=a.grau)
    total = sum(x["pago"] for x in linhas)
    escopo = ("TODAS as sanções (inclui multa, que NÃO impede contratar)" if a.tudo
              else f"grau: {a.grau}" if a.grau else "só sanções que RESTRINGEM o direito de contratar")
    print(f"empresas que receberam durante sanção vigente — {escopo}")
    print(f"  {len(linhas)} CNPJs · R$ {moeda(total)}")
    print("\nO ACHADO É O FATO DO PAGAMENTO NA VIGÊNCIA, não a conclusão de ilicitude: sanção do "
          "CEIS/CNEP é\nfederal, e o alcance de SUSPENSÃO sobre outro ente é controvertido "
          "(TCU e STJ divergem).\n")
    print(f"{'pago':>18} {'OBs':>5} {'1º pgto':>11}  {'categoria':<22} empresa")
    for x in linhas[:a.limite]:
        pr = x["primeira"].strftime("%d/%m/%Y") if x["primeira"] else "—"
        print(f"R$ {moeda(x['pago']):>15} {x['obs']:5d} {pr:>11}  {x['categoria'][:22]:<22} "
              f"{x['nome'][:30]} (desde {x['inicio']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
