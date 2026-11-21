# -*- coding: utf-8 -*-
"""Lex — PARECER REFERÊNCIA de fornecedor, por eixos e em duas camadas (20/11/2026).

Pedido do dono: "vamos melhorar muito esse parecer referência" + "tem que ser jurídico, financeiro, contábil,
compliance, parecer de tribunal de contas, determinístico e subjetivo também" + "o que mais você puder
adicionar, não tem limite de página".

Estrutura (ordem lógica e numeração contínua):
   1. Sumário executivo             — grau e por quê, 3 fatos com valor e fonte, lacunas, diligências prioritárias
   2. Objeto, escopo e método       — as duas camadas, os eixos, a régua do grau
   3. Base de fatos                  — identificação, quadro de fatos com proveniência e estado, mapa de cobertura
   4. Eixo financeiro                — Lei 4.320/64: empenhado × liquidado × pago (OB SIAFE), série, cadência
   5. Eixo contábil                  — registro, OB não paga, retenções, forense (Benford/redondos com n mínimo)
   6. Eixo jurídico                  — Lei 14.133/2021, contratos, contratação direta, catálogo de vícios, LINDB
   7. Eixo compliance/integridade    — due diligence, cronologia societária, rede, Lei 12.846/Decreto 11.129
   8. Instrução (tribunal de contas) — achado = critério × condição × causa × efeito, responsáveis, exculpatório,
                                       encaminhamento DERIVADO dos achados (Deliberação TCE-RJ 279/2017)
   9. Camada subjetiva               — opinião do Opus pela assinatura, separada; INDISPONÍVEL declarado
  10. Conclusão                      — grau consolidado que DECORRE dos eixos
  11. Diligências, quesitos e minuta de requisição
  12. Ressalvas
  Anexos A (OBs), B (fontes), C (base normativa)

Regras que este renderizador impõe por construção:
  · um número, uma fonte: tudo o que é dinheiro vem de `analise["ctx"]["pagamentos"]` (SIAFE, `lex_fatos`);
  · nenhum sinal é citado como relevante sem ser indício no grau — o que é só descritivo diz que não pesa e por quê;
  · encaminhamento sai dos achados: sem achado, diligências — nunca lista genérica de MP/CADE/CGE.
"""
from __future__ import annotations

import logging
import re

from compliance_agent import lex_fatos as lf
from compliance_agent.lex_fatos import INDISPONIVEL, PENDENTE, VERIFICADO, brl, inteiro, pct
from compliance_agent.lex_redflags import (
    _RF, _RF_DESTINATARIO, _anatomia, _elemento_subjetivo, _fam_exculpatorio, _grau,
)
from compliance_agent.reporting.intel_base import fmt_cnpj

logger = logging.getLogger(__name__)

EIXOS = (("financeiro", "Financeiro"), ("contabil", "Contábil"), ("juridico", "Jurídico"),
         ("compliance", "Compliance / integridade"))
_COMPLIANCE_RF = {"R6", "R11", "DD/SOCIO-AGENTE", "DD/LISTA-SUJA", "DD/SANCAO-SIGA"}
_JURIDICO_DD = {"DD/TAC-RECORRENTE", "DD/RF-TAC", "DD/EMERGENCIA-SIGA", "DD/DIRETA-PCRJ"}


def eixo_do_achado(a: dict) -> str:
    """Eixo a que o achado pertence (um só — o grau por eixo não conta o mesmo achado duas vezes)."""
    if a.get("eixo"):
        return a["eixo"]
    rf = str(a.get("rf") or "")
    obs = str(a.get("obs") or "").lower()
    if rf == "R8":
        return "compliance" if any(t in obs for t in ("cartel", "rodízio", "sócio", "rating")) else "financeiro"
    if rf in ("R12", "F-ESCALADA") and "documento" not in obs and "dfd" not in obs:
        return "financeiro"
    if rf == "R10" or rf.startswith("C-"):
        return "contabil"
    if rf in _COMPLIANCE_RF or (rf.startswith("DD/") and rf not in _JURIDICO_DD):
        return "compliance"
    return "juridico"


def _pi(a: dict) -> tuple[int, int, int]:
    pp = min(5, 2 + int(a.get("grav") or 0) // 2)
    ii = int(a.get("grav") or 0)
    return pp, ii, pp * ii


def score(achados: list[dict]) -> int:
    """Índice de atenção 0-100 = soma dos P×I da matriz de risco (escala interna de priorização — indício)."""
    return min(100, sum(_pi(a)[2] for a in achados))


def _razao(r: float) -> str:
    """432 → '432×'; 0,0861 → '0,09×' (o inteiro arredondava capital maior que o pago para '0×')."""
    return f"{inteiro(round(r))}×" if r >= 10 else f"{pct(r, 2)}×"


def _faixa(sc: int) -> str:
    return "Baixo" if sc <= 4 else "Médio" if sc <= 9 else "Alto" if sc <= 14 else "Extremo"


def _nome_rf(rf: str) -> str:
    if rf.startswith("P/"):
        return f"Padrão da casa: {rf[2:].replace('_', ' ')}"
    if rf.startswith("A/"):
        return f"Auditoria de contrato contínuo: teste {rf[2:]}"
    if rf not in _RF and rf.startswith("DD/"):
        return f"Due diligence: hipótese {rf[3:]}"
    return _RF.get(rf, (rf, ""))[0]


def _limpo(t: str, n: int = 0) -> str:
    t = re.sub(r"\s+", " ", str(t or "").replace("|", "/").replace("**", "")).strip()
    return (t[:n].rstrip() + "…") if n and len(t) > n else t


def _capturar(fn, *args, titulo: str) -> str:
    """Roda uma seção antiga (que escreve '## II-X. …') e a devolve como subseção numerada do eixo."""
    linhas: list[str] = []
    try:
        fn(linhas.append, *args)
    except Exception as exc:  # noqa: BLE001 — subseção some, parecer não cai (e diz que sumiu)
        logger.warning("subseção '%s' falhou: %s", titulo, exc)
        return f"### {titulo}\n\n> Subseção indisponível nesta execução (falha do módulo: {str(exc)[:90]}).\n"
    if not linhas:
        return ""
    out, achou = [], False
    for ln in "\n".join(linhas).split("\n"):
        if not achou and ln.startswith("## "):
            out.append(f"### {titulo}")
            achou = True
        elif ln.startswith("### "):
            out.append("#" + ln)
        else:
            out.append(ln)
    return "\n".join(out)


# ─────────────────────────────── grau por eixo e consolidado ───────────────────────────────

def graus(analise: dict) -> dict:
    """Grau de cada eixo (pelos SEUS achados) e o consolidado (por todos). O consolidado decorre dos eixos:
    nunca é menor que o maior grau de eixo, e só sobe acima dele por convergência entre eixos."""
    achados = analise.get("achados") or []
    p = analise["ctx"].get("pagamentos") or {}
    base = analise.get("base") or {}
    out = {}
    for k, nome in EIXOS:
        lst = [a for a in achados if eixo_do_achado(a) == k]
        e, r, j = _grau(lst)
        if not lst and k in ("financeiro", "contabil") and base.get("estado") != VERIFICADO:
            e, r, j = "⚪", "INDISPONÍVEL", f"base SIAFE indisponível ({base.get('motivo') or 'sem leitura'})"
        elif not lst and k in ("financeiro", "contabil") and not p.get("tem_dados"):
            e, r, j = "⚪", "SEM BASE", "nenhuma OB paga do SIAFE para examinar neste eixo"
        out[k] = {"nome": nome, "emoji": e, "rotulo": r, "just": j, "achados": lst,
                  "score": score(lst)}
    out["consolidado"] = {"emoji": analise["emoji"], "rotulo": analise["rotulo"], "just": analise["just"],
                          "score": score(achados)}
    return out


# ─────────────────────────────── quadro de fatos e cobertura ───────────────────────────────

def quadro_de_fatos(analise: dict) -> list[dict]:
    ctx, cad, exe = analise["ctx"], analise.get("cadastro") or {}, analise.get("execucao") or {}
    p = ctx.get("pagamentos") or {}
    base = analise.get("base") or {}
    F = []
    if base.get("estado") != VERIFICADO:
        F.append(lf.fato("OB paga (SIAFE)", "não lida", lf.FONTE_OB, INDISPONIVEL, base.get("motivo", "")))
    elif not p.get("tem_dados"):
        F.append(lf.fato("OB paga (SIAFE)", "nenhuma OB paga localizada para a raiz do CNPJ", lf.FONTE_OB, VERIFICADO,
                         "ausência na base ≠ ausência de pagamento fora da cobertura do SIAFE"))
    else:
        F.append(lf.fato("Total pago (OB SIAFE, valor > 0)", f"R$ {brl(p['total_geral'])}", lf.FONTE_OB, VERIFICADO))
        F.append(lf.fato("Nº de OBs pagas", inteiro(p["n_geral"]), lf.FONTE_OB, VERIFICADO))
        estab: dict = {}
        for d in base.get("pagas") or []:
            e = estab.setdefault(d.get("credor") or "?", [0, 0.0])
            e[0] += 1
            e[1] += d["valor"]
        if len(estab) > 1:
            proprio = estab.get(re.sub(r"\D", "", analise.get("cnpj") or ""), [0, 0.0])
            F.append(lf.fato("Estabelecimentos consolidados pela raiz do CNPJ", f"{inteiro(len(estab))} CNPJs; o "
                             f"analisado responde por {inteiro(proprio[0])} OB e R$ {brl(proprio[1])}",
                             lf.FONTE_OB, VERIFICADO, "matriz e filiais são a mesma pessoa jurídica"))
        ln = [x for b in p["por_ano"].values() for x in b["linhas"]]
        datas = sorted(x["data"] for x in ln if x["data"] != "—")
        if datas:
            F.append(lf.fato("Janela das OBs pagas", f"{datas[0]} a {datas[-1]}", lf.FONTE_OB, VERIFICADO))
        F.append(lf.fato("Órgãos (UG) pagadores", inteiro(len(p["por_orgao_geral"])), lf.FONTE_OB, VERIFICADO))
        top_o, top_v = next(iter(p["por_orgao_geral"].items()))
        F.append(lf.fato("Maior UG pagadora", f"{top_o} — R$ {brl(top_v)} ({pct(top_v / p['total_geral'] * 100)}%)",
                         lf.FONTE_OB, VERIFICADO))
        hhi = p.get("hhi") or {}
        F.append(lf.fato("Concentração por órgão (HHI)", f"{pct(float(hhi.get('indice') or 0))} ({hhi.get('nivel')})",
                         f"derivado de {lf.FONTE_OB}", VERIFICADO))
        F.append(lf.fato("OB de valor zero (regularização)", inteiro(p.get("n_regularizacoes")), lf.FONTE_OB, VERIFICADO))
        nao = base.get("nao_pagas") or []
        F.append(lf.fato("OB registradas e NÃO pagas (fora da régua)",
                         f"{inteiro(len(nao))} — R$ {brl(sum(d['valor'] for d in nao))}", lf.FONTE_OB, VERIFICADO))
        if exe.get("tem_nl"):
            F.append(lf.fato("Pago com NL localizada na base", f"{pct(exe['cobertura_nl_valor'])}% do valor "
                             f"({pct(exe['cobertura_nl_n'])}% das OBs)", f"{lf.FONTE_OB} × {lf.FONTE_NL}",
                             VERIFICADO if exe["cobertura_nl_valor"] >= 99.99 else PENDENTE,
                             "ingestão de NL parcial" if exe["cobertura_nl_valor"] < 99.99 else ""))
            F.append(lf.fato("Liquidado (NL contabilizadas do credor) — piso", f"R$ {brl(exe['liquidado_piso'])} "
                             f"em {inteiro(exe['n_nl'])} NL", lf.FONTE_NL, PENDENTE, "piso: ingestão parcial"))
            F.append(lf.fato("Retido na liquidação (NL) — piso", f"R$ {brl(exe['retido_piso'])}", lf.FONTE_NL, PENDENTE,
                             "retenções por tipo não ingeridas"))
        else:
            F.append(lf.fato("Liquidado (NL)", "tabela nl_siafe ausente", lf.FONTE_NL, INDISPONIVEL))
        if exe.get("tem_ne"):
            F.append(lf.fato("Empenhado (NE contabilizadas do credor) — piso", f"R$ {brl(exe['empenhado_piso'])} "
                             f"em {inteiro(exe['n_ne'])} NE", lf.FONTE_NE, PENDENTE, "piso: ingestão parcial"))
        else:
            F.append(lf.fato("Empenhado (NE)", "tabela ne_siafe ausente", lf.FONTE_NE, INDISPONIVEL))
        procs = analise.get("processos") or []
        resolvidos = [x for x in procs if x.get("canon")]
        v_res = sum(x["pago"] for x in resolvidos)
        F.append(lf.fato("Processos SEI identificados (nº na OB; na falta, na NL ou NE que ela cita)", f"{inteiro(len(resolvidos))} — "
                         f"R$ {brl(v_res)} ({pct(v_res / p['total_geral'] * 100)}% do pago)",
                         f"{lf.FONTE_OB} × NL × NE", VERIFICADO if v_res >= p["total_geral"] - 0.01 else PENDENTE,
                         "o restante não traz nº de processo reconhecível" if v_res < p["total_geral"] - 0.01 else ""))
        if base.get("coletado_em"):
            F.append(lf.fato("Última coleta das OBs do alvo", str(base["coletado_em"])[:19], lf.FONTE_OB, VERIFICADO))
    # cadastro
    fc = cad.get("fonte") or "Receita Federal · cadastro CNPJ"
    if cad.get("tem"):
        F.append(lf.fato("Abertura do CNPJ", cad["abertura"] or "não informada", fc, VERIFICADO if cad["abertura"] else INDISPONIVEL))
        F.append(lf.fato("Capital social", f"R$ {brl(cad['capital'])}" if cad["capital"] is not None else "não informado",
                         fc, VERIFICADO if cad["capital"] is not None else INDISPONIVEL))
        F.append(lf.fato("Situação cadastral", cad["situacao"] or "não informada", fc,
                         VERIFICADO if cad["situacao"] else INDISPONIVEL))
        F.append(lf.fato("Atividade principal (CNAE)", cad["cnae"] or "não informada", fc,
                         VERIFICADO if cad["cnae"] else INDISPONIVEL))
        F.append(lf.fato("Sócios/administradores no QSA", inteiro(len(cad["socios"])), fc, VERIFICADO))
        if p.get("tem_dados"):
            prim = min((x["data"] for b in p["por_ano"].values() for x in b["linhas"] if x["data"] != "—"), default="")
            idade = lf.idade_na_primeira_ob(cad, prim)
            if idade is not None:
                F.append(lf.fato("Idade do CNPJ na 1ª OB paga", f"{pct(idade)} ano(s) ({cad['abertura']} → {prim})",
                                 f"{fc} × {lf.FONTE_OB}", VERIFICADO))
            if cad["capital"]:
                F.append(lf.fato("Pago ÷ capital social", _razao(p['total_geral'] / cad['capital']),
                                 f"{fc} × {lf.FONTE_OB}", VERIFICADO))
    else:
        F.append(lf.fato("Cadastro CNPJ", "não disponível no contexto", fc, INDISPONIVEL))
    return F


def _lacunas(analise: dict) -> list[str]:
    """O que NÃO foi verificado — texto curto, reaproveitado no sumário, na cobertura e na camada subjetiva."""
    L = []
    exe = analise.get("execucao") or {}
    p = analise["ctx"].get("pagamentos") or {}
    if (analise.get("base") or {}).get("estado") != VERIFICADO:
        L.append("pagamentos SIAFE não lidos (base indisponível)")
    if p.get("tem_dados") and exe.get("cobertura_nl_valor", 0) < 99.99:
        L.append(f"liquidação: só {pct(exe.get('cobertura_nl_valor', 0))}% do pago tem a NL na base "
                 f"(R$ {brl(exe.get('pago_sem_nl_na_base'))} sem NL ingerida)")
    procs = analise.get("processos") or []
    sem = [x for x in procs if not x.get("canon")]
    if sem:
        L.append(f"{inteiro(sum(x['n_obs'] for x in sem))} OB(s) (R$ {brl(sum(x['pago'] for x in sem))}) sem nº de "
                 "processo SEI reconhecível na cadeia OB→NL→NE")
    lidos = [x for x in analise.get("leituras") or [] if x.get("lido")]
    if not lidos:
        L.append("íntegra dos processos SEI não lida nesta execução (vícios de planejamento, edital e julgamento "
                 "não examinados)")
    if not (analise.get("tcerj") or {}).get("n_contratos"):
        L.append("nenhum contrato do fornecedor na base de Dados Abertos do TCE-RJ (valor contratado e aditivos não "
                 "confrontados com o pago)")
    cob = (analise.get("investigacao") or {}).get("cobertura") or {}
    ind = [k.replace("_", " ") for k, v in cob.items() if str(v).upper().startswith("INDISPON")]
    if ind:
        L.append("due diligence sem fonte para: " + ", ".join(ind))
    L.append("retenções tributárias por tipo (ISS/IR/INSS) não ingeridas; ISS por nota fiscal depende do acervo SEI")
    return L


def mapa_de_cobertura(analise: dict) -> list[tuple[str, str, str, str]]:
    """(eixo, item, estado, fonte/observação) — verificado × pendente × indisponível, por eixo."""
    exe = analise.get("execucao") or {}
    base = analise.get("base") or {}
    p = analise["ctx"].get("pagamentos") or {}
    st_ob = VERIFICADO if base.get("estado") == VERIFICADO else INDISPONIVEL
    M = [("Financeiro", "OB paga (régua _ob_paga)", st_ob, lf.FONTE_OB),
         ("Financeiro", "Empenho (NE)", PENDENTE if exe.get("tem_ne") else INDISPONIVEL,
          "piso — ingestão parcial de ne_siafe" if exe.get("tem_ne") else "ne_siafe ausente"),
         ("Financeiro", "Liquidação (NL) por OB", (VERIFICADO if exe.get("cobertura_nl_valor", 0) >= 99.99 else PENDENTE)
          if exe.get("tem_nl") else INDISPONIVEL,
          f"{pct(exe.get('cobertura_nl_valor', 0))}% do pago com NL na base" if exe.get("tem_nl") else "nl_siafe ausente"),
         ("Financeiro", "Sazonalidade, cadência e concentração", st_ob if p.get("tem_dados") else INDISPONIVEL,
          "derivadas da mesma série de OB paga"),
         ("Contábil", "OB não paga (cancelada, devolvida, complementar, reemitida)", st_ob, lf.FONTE_OB),
         ("Contábil", "Pago × liquidado na mesma NL; OB × data da NL", PENDENTE if exe.get("tem_nl") else INDISPONIVEL,
          "só onde a NL está na base"),
         ("Contábil", "Retenções na liquidação", PENDENTE if exe.get("tem_nl") else INDISPONIVEL,
          "valor retido da NL (piso); tipo de retenção não ingerido"),
         ("Contábil", "Benford / valores redondos", VERIFICADO if p.get("tem_dados") else INDISPONIVEL,
          "régua descritiva; Benford exige n ≥ 100")]
    lidos = [x for x in analise.get("leituras") or [] if x.get("lido")]
    tc = analise.get("tcerj") or {}
    M += [("Jurídico", "Contratos e compras diretas (TCE-RJ Dados Abertos)",
           VERIFICADO if (tc.get("n_contratos") or tc.get("n_compras_diretas")) else PENDENTE,
           f"{tc.get('n_contratos', 0)} contrato(s), {tc.get('n_compras_diretas', 0)} compra(s) direta(s)"),
          ("Jurídico", "Íntegra dos processos SEI (edital, TR, atas, pareceres)", VERIFICADO if lidos else INDISPONIVEL,
           f"{len(lidos)} processo(s) lidos" if lidos else "leitura não executada"),
          ("Jurídico", "Acervo SEI da casa (fases documentadas por processo)",
           VERIFICADO if any((x.get("acervo") or {}).get("estado") == VERIFICADO for x in analise.get("processos") or [])
           else PENDENTE, "manifesto de data/sei_arquivo dos maiores processos"),
          ("Jurídico", "Padrões da casa por processo", VERIFICADO if (analise.get("padroes") or {}).get("estado") == VERIFICADO
           else INDISPONIVEL, f"{len((analise.get('padroes') or {}).get('lidos') or [])} padrão(ões) lido(s)")]
    cob = (analise.get("investigacao") or {}).get("cobertura") or {}
    for k, v in cob.items():
        sv = str(v)
        st = INDISPONIVEL if sv.upper().startswith("INDISPON") else VERIFICADO if sv.lower().startswith(
            ("verificado", "afastado", "indicio", "confirmado")) or sv[:1].isdigit() else PENDENTE
        M.append(("Compliance", f"Due diligence — {k.replace('_', ' ')}", st, sv))
    for chave, rot in (("sancoes_siga", "Sanções no registro estadual (SIGA)"), ("lista_suja_mte", "Cadastro MTE (trabalho escravo)"),
                       ("socios_agentes_publicos", "Sócio na folha pública"), ("tacs_doerj", "Termos de ajuste de contas (D.O.)")):
        inv = analise.get("investigacao") or {}
        M.append(("Compliance", rot, VERIFICADO if chave in inv else INDISPONIVEL,
                  "consultado" if chave in inv else "fonte não consultada nesta execução"))
    return M


# ─────────────────────────────── seções ───────────────────────────────

def _tab_fatos(F: list[dict]) -> list[str]:
    L = ["| Fato | Valor | Fonte (tabela/consulta) | Estado |", "|---|---|---|---|"]
    for f in F:
        fonte = _limpo(f["fonte"]) + (f" — {_limpo(f['nota'])}" if f.get("nota") else "")
        L.append(f"| {f['fato']} | {_limpo(f['valor'])} | {fonte} | **{f['estado']}** |")
    return L


def _secao_sumario(ctx, analise, G, F, lac, dil) -> list[str]:
    c = G["consolidado"]
    achados = analise.get("achados") or []
    L = ["## 1. SUMÁRIO EXECUTIVO", ""]
    eixos_hit = [f"{G[k]['nome']} ({len(G[k]['achados'])})" for k, _ in EIXOS if G[k]["achados"]]
    if achados:
        por = (f"{len(achados)} indício(s) em {len(eixos_hit)} eixo(s) — {', '.join(eixos_hit)}; gravidade máxima "
               f"{max(a['grav'] for a in achados)}/5")
    else:
        por = c["just"]
    L.append(f"- **Grau consolidado:** {c['emoji']} **{c['rotulo']}** · índice de atenção **{c['score']}/100** — {por}. "
             "Indício ≠ acusação; vigora a presunção de legitimidade.")
    pref = ("Total pago (OB SIAFE, valor > 0)", "Maior UG pagadora", "Pago ÷ capital social",
            "Idade do CNPJ na 1ª OB paga", "Janela das OBs pagas", "OB paga (SIAFE)")
    fatos = sorted((f for f in F if f["estado"] == VERIFICADO and f["fato"] in pref),
                   key=lambda f: pref.index(f["fato"]))[:3]
    if fatos:
        L.append("- **Fatos mais relevantes (camada determinística):**")
        for f in fatos:
            L.append(f"  - {f['fato']}: **{f['valor']}** — fonte {f['fonte']} · {f['estado']}.")
    for a in sorted(achados, key=lambda x: -x["grav"])[:3]:
        L.append(f"  - Indício **{a['rf']}** ({_nome_rf(a['rf'])}, grav. {a['grav']}/5): {_limpo(a['obs'], 220)}")
    if lac:
        L.append("- **Não verificado (lacunas declaradas):** " + "; ".join(lac[:5]) + ".")
    if dil:
        L.append("- **Diligências prioritárias:**")
        for d in dil[:4]:
            L.append(f"  - {d}")
    L.append("")
    return L


def _secao_metodo() -> list[str]:
    return ["## 2. OBJETO, ESCOPO E METODOLOGIA", "",
            "Avalia-se a relação do fornecedor com a Administração estadual em quatro eixos — **financeiro**, "
            "**contábil**, **jurídico** e **compliance/integridade** — instruídos no formato de **tribunal de contas** "
            "(seção 8). Cada eixo declara o critério normativo, examina os fatos e conclui com grau próprio; o grau "
            "consolidado (seção 10) é derivado dos eixos.", "",
            "**Duas camadas, separadas:**", "",
            "- **Determinística** (seções 3 a 8): só o que o código prova contra a fonte primária. Todo número traz "
            "fonte e estado — **VERIFICADO** (lido da fonte primária por código), **PENDENTE** (piso ou cobertura "
            "parcial, a conferir) ou **INDISPONÍVEL** (fonte não lida — INDISPONÍVEL ≠ 0). Pagamento é só a **OB paga "
            "do SIAFE** (régua `_ob_paga`); empenho ≠ liquidação ≠ pagamento; o espelho TFE não é usado como pago.",
            "- **Subjetiva** (seção 9): juízo raciocinado do Claude Opus pela assinatura, marcado como OPINIÃO; não "
            "altera fato nem grau — no máximo recomenda diligência.", "",
            "**Régua do grau:** 🟢 sem indício; 🟡 indício isolado ou pontual; 🔴 convergência de 3+ indícios com ao "
            "menos um grave (≥ 4/5); ⚪ sem base para graduar. O índice de atenção (0-100) é a soma dos P×I da "
            "matriz de risco (seção 8.4) — escala interna de priorização, não juízo de irregularidade.", ""]


def _secao_base(ctx, analise, F, M) -> list[str]:
    cad = analise.get("cadastro") or {}
    cnpj = analise["cnpj"]
    L = ["## 3. BASE DE FATOS (camada determinística)", "", "### 3.1 Identificação", ""]
    L.append(f"- **Fornecedor:** {ctx.get('nome', '')} — CNPJ {fmt_cnpj(cnpj)} (raiz {re.sub(r'[^0-9]', '', cnpj)[:8]}: "
             "matriz e filiais consolidadas)")
    if cad.get("tem"):
        end = ", ".join(x for x in (cad["logradouro"], cad["numero"], cad["complemento"], cad["bairro"],
                                    cad["municipio"], cad["uf"]) if x)
        L.append(f"- **Endereço cadastral:** {end or 'não informado no cadastro'}")
        L.append(f"- **Porte:** {cad['porte'] or 'não informado'} · **CNAE:** {cad['cnae'] or 'não informado'}")
        if cad["socios"]:
            L.append("- **Quadro societário (QSA):** " + "; ".join(
                f"{s['nome'] or '—'}" + (f" ({s['qualificacao']})" if s["qualificacao"] else "")
                + (f", entrada {s['entrada']}" if s["entrada"] else "") for s in cad["socios"][:12])
                + (" …" if len(cad["socios"]) > 12 else "") + " — documentos de pessoa física não são exibidos (LGPD).")
    L += ["", "### 3.2 Quadro de fatos (fonte única por fato)", "",
          "*Cada número do parecer remete a esta tabela; as seções seguintes não consultam outra fonte para o mesmo fato.*", ""]
    L += _tab_fatos(F)
    L += ["", "### 3.3 Mapa de cobertura (verificado × pendente × indisponível)", "",
          "| Eixo | Item | Estado | Fonte / observação |", "|---|---|---|---|"]
    for e, i, s, o in M:
        L.append(f"| {e} | {i} | **{s}** | {_limpo(o, 160)} |")
    L.append("")
    return L


def _conclusao_eixo(G, k) -> list[str]:
    g = G[k]
    L = [f"**Conclusão do eixo {g['nome'].lower()}:** {g['emoji']} **{g['rotulo']}** — "
         + (f"{len(g['achados'])} indício(s) ({', '.join(a['rf'] for a in g['achados'])}); P×I somado {g['score']}."
            if g["achados"] else f"{g['just']}."), ""]
    return L


def _lista_indicios(lst: list[dict], exc_por_rf: dict) -> list[str]:
    L = []
    for a in lst:
        nome, fund = (_nome_rf(a["rf"]), _RF.get(a["rf"], ("", ""))[1])
        L.append(f"#### {a['rf']} — {nome} (gravidade {a['grav']}/5)")
        L.append(f"- **Condição (fato):** {a['obs']}")
        if fund:
            L.append(f"- **Critério:** {fund}")
        if a.get("fonte_padrao"):
            L.append(f"- **Fonte do padrão:** {a['fonte_padrao']} · **Taxa de falso positivo do detector:** não medida "
                     "(INDISPONÍVEL) — tratar como hipótese a conferir no documento.")
        e = exc_por_rf.get(a["rf"]) or {}
        if e:
            L.append(f"- **Explicação inocente:** {e.get('defesa')} → "
                     + ("os dados **não** a refutam: rebaixado a **monitoramento** (não representação)." if e.get("sobrevive")
                        else "os dados a **refutam** (convergência/gravidade): sustenta **requisição de documentos**."))
        if a.get("analise"):
            L.append(f"- **Análise (onde e por quê):** {a['analise']}")
            if a.get("trecho"):
                L.append(f"  > _Trecho do processo {a.get('numero_proc', '')}:_ «{a['trecho'][:300]}»")
        L.append("")
    return L


def _secao_financeiro(ctx, analise, G, exc_por_rf) -> list[str]:
    from compliance_agent import lex_forense as lfo
    p = ctx.get("pagamentos") or {}
    exe = analise.get("execucao") or {}
    L = ["## 4. EIXO FINANCEIRO — execução da despesa", "", "### 4.1 Critério normativo", "",
         "Lei 4.320/64: o **empenho** reserva a dotação e cria a obrigação de pagamento pendente de implemento "
         "(art. 58), vedada a despesa sem prévio empenho (art. 60); a **liquidação** verifica o direito do credor à "
         "vista dos comprovantes da entrega (art. 63); o **pagamento** só ocorre após a regular liquidação (art. 62), "
         "por ordem de pagamento (art. 64). Só a **OB paga** prova o desembolso — empenho ≠ liquidação ≠ pagamento.", ""]
    if not p.get("tem_dados"):
        L += ["> Nenhuma OB paga do SIAFE para este CNPJ na base consultada "
              f"({(analise.get('base') or {}).get('motivo') or 'leitura concluída sem OB paga'}). O eixo fica sem base — "
              "não se presume regularidade nem irregularidade.", ""]
        L += ["### 4.2 Indícios do eixo", ""] + (_lista_indicios(G["financeiro"]["achados"], exc_por_rf)
                                                or ["> Nenhum indício financeiro.", ""])
        L += _conclusao_eixo(G, "financeiro")
        return L
    tot = p["total_geral"]
    L += ["### 4.2 Empenhado × liquidado × pago", "",
          "| Estágio | Valor (R$) | Documentos | Fonte | Estado |", "|---|---:|---:|---|---|",
          f"| Empenhado (NE contabilizadas) | {brl(exe.get('empenhado_piso'))} | {inteiro(exe.get('n_ne'))} | {lf.FONTE_NE} | "
          f"**{PENDENTE if exe.get('tem_ne') else INDISPONIVEL}** (piso) |",
          f"| Liquidado (NL contabilizadas) | {brl(exe.get('liquidado_piso'))} | {inteiro(exe.get('n_nl'))} | {lf.FONTE_NL} | "
          f"**{PENDENTE if exe.get('tem_nl') else INDISPONIVEL}** (piso) |",
          f"| **Pago (OB SIAFE, régua _ob_paga)** | **{brl(tot)}** | {inteiro(p['n_geral'])} | {lf.FONTE_OB} | **{VERIFICADO}** |", ""]
    if exe.get("tem_nl"):
        L.append(f"> **Leitura honesta:** {pct(exe['cobertura_nl_valor'])}% do valor pago ({pct(exe['cobertura_nl_n'])}% das "
                 f"OBs) tem a NL citada presente na base; R$ {brl(exe['pago_sem_nl_na_base'])} foram pagos por OBs cuja NL "
                 "não foi ingerida. Por isso empenhado e liquidado são **piso** e não se comparam ao pago como totais — "
                 "a comparação homogênea (mesma NL nas duas pontas) está no eixo contábil (5.2).")
        L.append("")
    L += ["### 4.3 Pagamento por exercício e sazonalidade", "",
          "*Ano = data da OB. A soma das linhas fecha com o total pago do quadro de fatos.*", ""]
    linhas = [x for b in p["por_ano"].values() for x in b["linhas"]]
    saz = lfo.sazonalidade(linhas)
    L.append("| Ano | " + " | ".join(lfo._MESES) + " | OBs | Total (R$) |")
    L.append("|---|" + "---:|" * 14)
    for ano, b in p["por_ano"].items():
        m = saz.get(ano, {})
        cels = []
        for i in range(1, 13):
            v = m.get(i, 0)
            cels.append("—" if not v else (f"**{brl(v / 1000)}k**" if v >= 0.25 * b["total"] else f"{brl(v / 1000)}k"))
        L.append(f"| {ano} | " + " | ".join(cels) + f" | {inteiro(b['n'])} | {brl(b['total'])} |")
    L.append("| **Total** | " + " | ".join([""] * 12) + f" | **{inteiro(p['n_geral'])}** | **{brl(tot)}** |")
    dez = sum(x["valor"] for x in linhas if x["data"][5:7] == "12")
    L += ["", f"*Células em negrito concentram ≥ 25% do ano. Dezembro responde por {pct(dez / tot * 100)}% do pago "
          "(concentração de fim de exercício pede conferência do atesto das OBs de dezembro — art. 63 da Lei 4.320/64; "
          "aqui é régua descritiva, não indício).*", ""]
    L += ["### 4.4 Cadência e concentração por órgão", "",
          "| Órgão (UG) | OBs | Total (R$) | % do pago | Meses ativos | Média/mês ativo (R$) | Maior OB (R$) | Janela |",
          "|---|---:|---:|---:|---:|---:|---:|---|"]
    cad_o = lfo.cadencia_por_orgao(linhas, top=15)
    for c in cad_o:
        L.append(f"| {c['orgao'][:60]} | {inteiro(c['n'])} | {brl(c['total'])} | {pct(c['total'] / tot * 100)}% | "
                 f"{c['meses_ativos']} | {brl(c['media_mes'])} | {brl(c['maior'])} | {c['primeira']}→{c['ultima']} |")
    resto = len(p["por_orgao_geral"]) - len(cad_o)
    if resto > 0:
        v_resto = tot - sum(c["total"] for c in cad_o)
        L.append(f"| demais {resto} órgão(s) | — | {brl(v_resto)} | {pct(v_resto / tot * 100)}% | — | — | — | — |")
    hhi = p.get("hhi") or {}
    L += ["", f"*HHI {pct(float(hhi.get('indice') or 0))} ({hhi.get('nivel')}); maior órgão com "
          f"{pct(float(hhi.get('top_share') or 0))}% do pago. A régua do indício R8 é ≥ 40% num único órgão "
          "(≥ 60% = extrema).*", ""]
    L += _secao_processos(analise)
    from compliance_agent.lex_render import _secao_auditoria_contrato
    aud = _capturar(_secao_auditoria_contrato, analise.get("auditoria_contrato") or {},
                    titulo="4.6 Auditoria de contrato contínuo (bateria T01–T22)")
    if aud.strip():
        L += [aud, "", "> Os testes CONFIRMADO/INDÍCIO desta bateria entram no grau do parecer como achados `A/…` "
              "(subseção de indícios abaixo). A bateria soma as OB com status «Contabilizado» da UG auditada (base "
              "própria); o pago do parecer é a régua `_ob_paga` do quadro 3.2 — diferença = OB devolvida, complementar "
              "ou reemitida.", ""]
    lst = G["financeiro"]["achados"]
    L += ["### 4.7 Indícios do eixo", ""]
    L += _lista_indicios(lst, exc_por_rf) if lst else ["> Nenhum indício financeiro disparou nas réguas acima.", ""]
    L += _conclusao_eixo(G, "financeiro")
    return L


def _secao_processos(analise: dict) -> list[str]:
    procs = analise.get("processos") or []
    if not procs:
        return []
    tot = sum(x["pago"] for x in procs) or 1
    L = ["### 4.5 Processos: cadeia empenho → liquidação → pagamento", "",
         "*Processo identificado pelo SIAFE: o nº gravado na OB ou, na falta, o da NL que ela cita ou o da NE dessa NL. NL e NE «0» = não ingeridas na base, não ausentes no SIAFE. A coluna «Acervo» diz o que o "
         "arquivo SEI da casa tem do processo; fase ausente = documento a requisitar (lacuna, não irregularidade).*", "",
         "| Processo | UG | OBs | Pago (R$) | 1ª/última OB | NL | Liquidado (R$) | NE | Empenhado (R$) | Acervo SEI |",
         "|---|---|---:|---:|---|---:|---:|---:|---:|---|"]
    for x in procs[:20]:
        ac = x.get("acervo") or {}
        if ac.get("estado") in (VERIFICADO, PENDENTE):
            acv = f"{ac['n_docs']} docs; falta: {', '.join(f.split(' ')[0] for f in ac['faltam_fases']) or 'nenhuma fase'}"
        else:
            acv = ac.get("motivo") or "não consultado"
        rot = x["processo"] if x.get("canon") or x["processo"].startswith("(") else (
            f"«{x['processo'][:30]}» (sem nº SEI reconhecível)")
        ugs = ", ".join(x["ugs"]) if len(x["ugs"]) <= 2 else f"{len(x['ugs'])} UGs"
        L.append(f"| {rot[:60]} | {ugs} | {inteiro(x['n_obs'])} | {brl(x['pago'])} | "
                 f"{x['primeira_ob']}/{x['ultima_ob']} | {x['n_nl']} | {brl(x['liquidado']) if x['n_nl'] else '—'} | "
                 f"{x['n_ne']} | {brl(x['empenhado']) if x['n_ne'] else '—'} | {_limpo(acv, 80)} |")
    if len(procs) > 20:
        resto = procs[20:]
        L.append(f"| demais {len(resto)} processo(s) | — | {inteiro(sum(x['n_obs'] for x in resto))} | "
                 f"{brl(sum(x['pago'] for x in resto))} | — | — | — | — | — | ver Anexo A |")
    L += ["", f"*{inteiro(len(procs))} grupo(s) de processo; os 20 maiores somam "
          f"{pct(sum(x['pago'] for x in procs[:20]) / tot * 100)}% do pago. NL/NE «—» = não ingeridas na base (PENDENTE).*", ""]
    return L


def _secao_contabil(ctx, analise, G, exc_por_rf) -> list[str]:
    from compliance_agent import lex_forense as lfo
    p = ctx.get("pagamentos") or {}
    base = analise.get("base") or {}
    exe = analise.get("execucao") or {}
    L = ["## 5. EIXO CONTÁBIL — conformidade do registro e contabilidade forense", "", "### 5.1 Critério normativo", "",
         "Lei 4.320/64, arts. 36 (restos a pagar), 58-65 (estágios da despesa) e 101-105 (demonstrações); a OB só "
         "é pagamento quando contabilizada e não devolvida pelo banco (régua `_ob_paga`). Retenção na fonte: ISS "
         "(LC 116/2003, art. 6º: o tomador responde pela retenção que deixa de fazer) e IR retido na fonte, cujo produto pertence ao Estado (CF/88, art. 157, I).", ""]
    nao = base.get("nao_pagas") or []
    L += ["### 5.2 Estágios e registro", ""]
    if base.get("estado") == VERIFICADO:
        L += [f"- **OB pagas com valor > 0:** {inteiro(len(base.get('pagas') or []))} — R$ {brl(p.get('total_geral'))} "
              f"({lf.FONTE_OB} · {VERIFICADO}).",
              f"- **OB de valor zero (regularização contábil):** {inteiro(len(base.get('regularizacoes') or []))} "
              "— fora da série paga (régua do indício R10: ≥ 3)."]
        if nao:
            mot: dict = {}
            for d in nao:
                m = mot.setdefault(d["motivo"], [0, 0.0])
                m[0] += 1
                m[1] += d["valor"]
            L += ["- **OB registradas e NÃO pagas** (excluídas do pago pela régua):", "",
                  "| Motivo | OBs | Valor (R$) |", "|---|---:|---:|"]
            for k, (n, v) in sorted(mot.items(), key=lambda kv: -kv[1][1]):
                L.append(f"| {k} | {inteiro(n)} | {brl(v)} |")
            L.append("")
        else:
            L.append("- **OB registradas e NÃO pagas:** nenhuma.")
        if exe.get("tem_nl"):
            L.append(f"- **Pago acima do liquidado na mesma NL:** {inteiro(len(exe['pago_acima_da_nl']))} NL; "
                     f"**OB anterior à NL citada:** {inteiro(len(exe['ob_antes_da_nl']))} OB — conferido só onde a NL "
                     f"está na base ({pct(exe['cobertura_nl_n'])}% das OBs).")
            na = exe.get("nl_anuladas") or []
            ea = exe.get("ne_anuladas") or []
            L.append(f"- **NL não contabilizadas (anuladas/excluídas):** {inteiro(len(na))} — R$ "
                     f"{brl(sum(float(n.get('valor') or 0) for n in na))}; **NE não contabilizadas:** {inteiro(len(ea))} — "
                     f"R$ {brl(sum(float(n.get('valor') or 0) for n in ea))} ({lf.FONTE_NL} / {lf.FONTE_NE}).")
    else:
        L.append(f"> Base SIAFE indisponível ({base.get('motivo')}) — registro não examinado.")
    L += ["", "### 5.3 Retenções", ""]
    if exe.get("tem_nl"):
        L.append(f"Valor retido declarado nas NL contabilizadas do credor: **R$ {brl(exe['retido_piso'])}** ({lf.FONTE_NL} · "
                 f"{PENDENTE}, piso). O **tipo** de cada retenção (ISS, IR, INSS) não está ingerido; a conferência da "
                 "retenção de ISS nota a nota é feita pelo detector `iss_declarado_retido_nao_retido` sobre o acervo SEI — "
                 + ("ver o padrão na seção 5.5." if any(a["rf"] == "P/iss_declarado_retido_nao_retido"
                                                         for a in G["contabil"]["achados"])
                    else "sem disparo nos processos deste fornecedor presentes no acervo."))
    else:
        L.append("> Retenções não examinadas: NL não ingeridas (INDISPONÍVEL).")
    L.append("")
    L += ["### 5.4 Contabilidade forense (régua descritiva)", "",
          "*Benford e valores redondos são RÉGUA, não prova: não entram no grau (detectores sem taxa de falso positivo "
          "medida) e só se leem com amostra suficiente.*", ""]
    if p.get("tem_dados"):
        valores = [x["valor"] for b in p["por_ano"].values() for x in b["linhas"]]
        b = lfo.benford(valores)
        if b.get("ok"):
            L.append(f"- **Benford (1º dígito):** n = {inteiro(b['n'])} OBs; MAD {pct(b['mad'], 4)} → **{b['rotulo']}** "
                     f"(limiares de Nigrini). {b['leitura']}.")
        else:
            L.append(f"- **Benford:** não aplicado — {b.get('motivo')}; afirmar conformidade ou desvio seria fabricar precisão.")
        r = lfo.redondos(valores)
        if r.get("ok"):
            suf = ("amostra pequena demais para inferência (n < 30) — dado descritivo" if r["n"] < 30 else
                   "parcelas fixas de contrato, aluguéis e tarifas fecham redondo legitimamente — interpretar com o objeto")
            L.append(f"- **Valores redondos:** das {inteiro(r['n'])} OBs pagas ≥ R$ 1.000,00 (de {inteiro(len(valores))} OBs "
                     f"pagas), {inteiro(r['n_mil'])} ({pct(r['pct_mil'])}%) fecham em milhar exato e {pct(r['pct_cem'])}% em "
                     f"centena exata — {suf}.")
    else:
        L.append("> Sem série paga para testar.")
    L.append("")
    lst = G["contabil"]["achados"]
    L += ["### 5.5 Indícios do eixo", ""]
    L += _lista_indicios(lst, exc_por_rf) if lst else ["> Nenhum indício contábil disparou.", ""]
    L += _conclusao_eixo(G, "contabil")
    return L


def _secao_juridico(ctx, analise, G, exc_por_rf) -> list[str]:
    from compliance_agent.lex_render import _secao_direcionamento
    tc = analise.get("tcerj") or {}
    L = ["## 6. EIXO JURÍDICO — legalidade da contratação", "", "### 6.1 Critério normativo", "",
         "Lei 14.133/2021: princípios e vedações (arts. 5º, 9º e 11), planejamento (art. 18), pesquisa de preços "
         "(art. 23), habilitação (arts. 62-70), contratação direta instruída (art. 72) e suas hipóteses (arts. 74-75, "
         "vedado o fracionamento — art. 75, §1º), fiscalização do contrato (art. 117) e limites de alteração (art. 125). "
         "LINDB, arts. 20-22 e 28 (consequências práticas; dificuldades reais do gestor; só o erro grosseiro "
         "responsabiliza). Improbidade (Lei 8.429/92 pós-Lei 14.230/2021): exige **dolo** e, no art. 10, **dano efetivo**.", ""]
    L += ["### 6.2 Contratos e contratação direta (TCE-RJ Dados Abertos)", ""]
    if tc.get("n_contratos") or tc.get("n_compras_diretas"):
        from compliance_agent.lex_redflags import _fmt_proc
        L.append(f"A base de Dados Abertos do TCE-RJ registra **{tc.get('n_contratos', 0)} contrato(s)** "
                 f"(R$ {brl(tc.get('soma_contratos', 0))}, valor contratado — não é pago) e **{tc.get('n_compras_diretas', 0)} "
                 f"compra(s) direta(s)** (R$ {brl(tc.get('soma_compras', 0))}), das quais "
                 f"**{tc.get('n_diretas_dispensa', 0)} por dispensa/inexigibilidade**.")
        L.append("")
        if tc.get("contratos"):
            L += ["| Processo | Ano | Objeto | Critério | Valor do contrato (R$) | Unidade |", "|---|---:|---|---|---:|---|"]
            for c in tc["contratos"]:
                L.append(f"| {_fmt_proc(c.get('processo', ''))} | {c.get('ano_processo', '')} | {_limpo(c.get('objeto'), 60) or '—'} | "
                         f"{c.get('criterio_julgamento') or '—'} | {brl(c.get('valor_contrato'))} | {_limpo(c.get('unidade'), 30)} |")
            L.append("")
        if tc.get("compras"):
            L += ["| Processo | Ano | Objeto | Afastamento | Enquadramento legal | Valor (R$) |", "|---|---:|---|---|---|---:|"]
            for c in tc["compras"]:
                L.append(f"| {_fmt_proc(c.get('processo', ''))} | {c.get('ano_processo', '')} | {_limpo(c.get('objeto'), 50) or '—'} | "
                         f"{c.get('afastamento') or '—'} | {_limpo(c.get('enquadramento_legal'), 55) or '—'} | {brl(c.get('valor'))} |")
            L.append("")
    else:
        L += ["> Nenhum contrato nem compra direta deste CNPJ na base de Dados Abertos do TCE-RJ (PENDENTE: confirmar no "
              "PNCP e no próprio processo SEI). Sem o valor contratado, o pago não é confrontado com o teto do contrato "
              "nem com os limites de aditivo do art. 125.", ""]
    lidos = [x for x in analise.get("leituras") or [] if x.get("lido")]
    L += ["### 6.3 Leitura dos processos SEI", ""]
    if lidos:
        for x in lidos:
            L.append(f"- **{x.get('numero')}** — {x.get('tipo') or ''} · objeto: {_limpo(x.get('objeto'), 160) or '—'} · "
                     f"modalidade aparente: {x.get('modalidade', '—')} · {x.get('n_docs', 0)} documentos "
                     f"({x.get('n_docs_lidos', 0)} lidos) · OBs do processo: {x.get('n_obs', '—')} (R$ {brl(x.get('total'))}).")
        L.append("")
    else:
        nao = [x for x in analise.get("leituras") or [] if not x.get("lido")]
        mot = "; ".join(f"{x.get('numero')}: {x.get('erro') or 'sem texto'}" for x in nao[:5])
        L += [f"> Íntegra não lida nesta execução{(' (' + mot + ')') if mot else ''}. Os vícios das fases de planejamento, "
              "edital e julgamento **não foram examinados** — é lacuna, não regularidade.", ""]
    L += _secao_vicios(analise, G)
    direc = _capturar(_secao_direcionamento, analise.get("direcionamento"), titulo="6.5 Direcionamento de licitação")
    if direc.strip():
        L += [direc, ""]
    L += _secao_improbidade(analise)
    lst = G["juridico"]["achados"]
    L += ["### 6.7 Indícios do eixo", ""]
    L += _lista_indicios(lst, exc_por_rf) if lst else ["> Nenhum indício jurídico disparou nas fontes lidas.", ""]
    L += _conclusao_eixo(G, "juridico")
    return L


def _secao_vicios(analise: dict, G: dict) -> list[str]:
    """Catálogo canônico de vícios (knowledge/catalogo_vicios): o vício de cada achado e o que não foi examinado."""
    L = ["### 6.4 Vícios de licitação pelo catálogo canônico", ""]
    try:
        from compliance_agent.knowledge.catalogo_vicios import CATALOGO
    except ImportError as exc:
        return L + [f"> Catálogo de vícios indisponível ({str(exc)[:80]}).", ""]
    achados = analise.get("achados") or []
    rfs = {a["rf"] for a in achados}
    hit = [v for v in CATALOGO if set(v.redflags_lex) & rfs]
    if hit:
        L += ["| Vício (catálogo) | Fase | Achado que o aponta | Dispositivos | Escalada típica |", "|---|---|---|---|---|"]
        for v in hit:
            L.append(f"| {v.nome} | {v.fase} | {', '.join(sorted(set(v.redflags_lex) & rfs))} | "
                     f"{'; '.join(v.dispositivos) or '—'} | {v.escalada} |")
        L.append("")
    else:
        L.append("Nenhum achado deste parecer corresponde a vício catalogado.")
        L.append("")
    lidos = [x for x in analise.get("leituras") or [] if x.get("lido")]
    fases = {}
    for v in CATALOGO:
        fases.setdefault(v.fase, []).append(v)
    if not lidos:
        L.append("> **Não examinados por falta da íntegra do processo:** " + "; ".join(
            f"{f} ({len(fases[f])} vícios)" for f in ("planejamento", "edital", "julgamento") if f in fases)
            + ". O catálogo tem " + str(len(CATALOGO)) + " vícios; sem os documentos da contratação, a ausência de achado "
            "nessas fases não é afirmação de regularidade.")
        L.append("")
    return L


def _secao_improbidade(analise: dict) -> list[str]:
    achados = analise.get("achados") or []
    L = ["### 6.6 Triagem: ilegalidade × improbidade (elemento subjetivo)", ""]
    if not achados:
        return L + ["> Sem indício a triar.", ""]
    L += ["| Indício | Elemento subjetivo (triagem) | Encaminhamento doutrinário |", "|---|---|---|"]
    n_dolo = 0
    for a in achados:
        classe, _ = _elemento_subjetivo(a)
        if classe.startswith("dolo"):
            n_dolo += 1
            enc = "improbidade (MP-RJ) — a apurar dolo + dano efetivo"
        else:
            enc = "controle de contas (TCE-RJ) — não improbidade"
        L.append(f"| {a['rf']} {_nome_rf(a['rf'])} | {classe} | {enc} |")
    L.append("")
    L.append("> " + ("Nenhum indício com sinal de dolo: o conjunto é matéria de **controle de contas**, não de improbidade "
                     "(Lei 14.230/2021 — sem improbidade culposa; art. 10 exige dano efetivo)." if n_dolo == 0 else
                     f"{n_dolo} indício(s) com sinal de elemento subjetivo — apurar dolo e dano antes de cogitar improbidade."))
    L.append("")
    return L


def _secao_compliance(ctx, analise, G, exc_por_rf) -> list[str]:
    from compliance_agent import lex_forense as lfo
    from compliance_agent.lex_render import _secao_investigacao, _secao_padroes_ligados, _secao_pesquisa
    from compliance_agent.reporting.inteligencia import so_digitos
    p = ctx.get("pagamentos") or {}
    cad = analise.get("cadastro") or {}
    L = ["## 7. EIXO COMPLIANCE / INTEGRIDADE — due diligence do fornecedor", "", "### 7.1 Critério normativo", "",
         "Lei 12.846/2013 (responsabilização objetiva da pessoa jurídica por atos lesivos — art. 5º, IV: fraude a "
         "licitação e contrato) e Decreto 11.129/2022 (parâmetros do programa de integridade); Lei 14.133/2021, "
         "art. 14 (impedimentos, inclusive vínculo com agente público), art. 156 (sanções) e art. 25, §4º (programa "
         "de integridade em contratação de grande vulto). Sanção vale pela **vigência e alcance** na data do ato.", ""]
    inv = analise.get("investigacao") or {}
    dd_md = _capturar(_secao_investigacao, inv, so_digitos(ctx.get("cnpj", "")),
                      titulo="7.2 Due diligence — fachada, laranja, sanções e vínculos")
    # o módulo de due diligence imprime um "grau da investigação" próprio (podia sair 🟢 com um fato CONFIRMADO
    # logo abaixo): no parecer o grau é um só, o do eixo — a linha vira o placar da bateria.
    dd_md = re.sub(r"\*\*Grau da investigação:\*\* \S+ · score \d+/100 · ",
                   "**Placar da bateria de due diligence:** ", dd_md)
    L.append(dd_md)
    L.append("")
    if (inv or {}).get("pacote_fachada"):
        L += ["> Sinais do pacote de fachada (rede de comando, veículos do administrador, sede) que **não** viraram "
              "hipótese CONFIRMADA ou INDÍCIO acima são **contexto para diligência** e não entram no grau; o que entra "
              "está listado nos indícios do eixo.", ""]
    # linha do tempo societária × dinheiro (com a régua do R6 dita, para o leitor saber se pesa ou não)
    linhas = [x for b in (p.get("por_ano") or {}).values() for x in b.get("linhas") or []]
    emp = {"data_abertura": cad.get("abertura"), "socios": [{"nome": s["nome"], "entrada": s["entrada"]}
                                                             for s in cad.get("socios") or []]}
    ev = lfo.linha_do_tempo(emp, linhas, analise.get("achados") or [])
    L += ["### 7.3 Linha do tempo societária × pagamentos", ""]
    if len(ev) >= 2:
        L += ["| Data | Evento | Pago até a data (R$) |", "|---|---|---:|"]
        for d, e in ev:
            acum = sum(x["valor"] for x in linhas if x["data"] != "—" and x["data"] < d) if d[:1].isdigit() else 0
            L.append(f"| {d} | {e} | {brl(acum) if d[:1].isdigit() else '—'} |")
        L.append("")
        tot = p.get("total_geral") or 0
        posts = [s for s in cad.get("socios") or [] if s["entrada"] and linhas and s["entrada"] > min(
            x["data"] for x in linhas if x["data"] != "—")]
        if posts and not any(a["rf"] == "R6" for a in analise.get("achados") or []):
            s = max(posts, key=lambda s: s["entrada"])
            antes = sum(x["valor"] for x in linhas if x["data"] != "—" and x["data"] < s["entrada"])
            L.append(f"> Houve ingresso no QSA depois da 1ª OB ({s['entrada']}), com R$ {brl(antes)} pagos antes "
                     f"({pct(antes / tot * 100 if tot else 0)}% do total). A régua do indício R6 (troca de controle após "
                     "receita pública) exige R$ 1.000.000,00 **e** 15% do pago antes do ingresso — **não atingida**: o fato "
                     "fica registrado, não pesa no grau.")
            L.append("")
    else:
        L += ["> Datas insuficientes para a cronologia (abertura, entrada de sócios ou OBs).", ""]
    cartel, cruzado = analise.get("cartel") or {}, analise.get("cruzado") or {}
    vz = cartel.get("vizinhos") or []
    L += ["### 7.4 Rede fornecedor–órgão e sócios em comum", ""]
    if vz:
        L.append(f"O fornecedor atua em **{cartel.get('n_orgaos', 0)} órgão(s)**; fornecedores não-ubíquos que atuam nos mesmos "
                 "órgãos (co-ocorrência não prova conluio):")
        L += ["", "| Fornecedor co-ocorrente | Órgãos em comum | Footprint total | Valor nesses órgãos (R$) |", "|---|---:|---:|---:|"]
        for v in vz[:8]:
            L.append(f"| {_limpo(v.get('nome'), 40)} | {v.get('orgaos_comuns')} | {v.get('footprint_total')} | {brl(v.get('valor_nos_orgaos'))} |")
        L.append("")
        for m in (cruzado.get("co_ocorrencia_com_socio_comum") or [])[:6]:
            L.append(f"- **Sócio em comum:** {_limpo(m.get('nome'), 38)} — {m.get('orgaos_comuns')} órgão(s) em comum; "
                     f"sócio(s): {_limpo(m.get('socios_comuns'), 50)}")
        L.append("")
    else:
        L += ["> Sem co-ocorrência relevante na base fornecedor–órgão.", ""]
    pq = _capturar(_secao_pesquisa, analise.get("pesquisa"), titulo="7.5 Pesquisa em fontes abertas (persistida)")
    if pq.strip():
        L += [pq, ""]
    pl = _capturar(_secao_padroes_ligados, (analise.get("pesquisa") or {}).get("cruzado") or "",
                   titulo="7.6 Aprendizado cruzado — fornecedores ligados")
    if pl.strip():
        L += [pl, ""]
    lst = G["compliance"]["achados"]
    L += ["### 7.7 Indícios do eixo", ""]
    dd = [a for a in lst if str(a["rf"]).startswith("DD/H-")]
    outros = [a for a in lst if a not in dd]
    if dd:
        L += ["*Hipóteses da due diligence que entram no grau (constatação e fonte na subseção da due diligence):*", "",
              "| Indício | Gravidade | Explicação inocente | Refutada pelos dados? |", "|---|---:|---|---|"]
        for a in dd:
            e = exc_por_rf.get(a["rf"]) or {}
            L.append(f"| {a['rf']} {_nome_rf(a['rf'])} | {a['grav']}/5 | {_limpo(e.get('defesa'), 120)} | "
                     f"{'Sim — requisição' if e and not e.get('sobrevive') else 'Não — monitoramento'} |")
        L.append("")
    L += _lista_indicios(outros, exc_por_rf)
    if not lst:
        L += ["> Nenhum indício de integridade disparou nas fontes verificadas (ver lacunas no mapa de cobertura, 3.3).", ""]
    L += _conclusao_eixo(G, "compliance")
    return L


def encaminhamento(analise: dict) -> list[str]:
    """Proposta de encaminhamento DERIVADA dos achados (Deliberação TCE-RJ 279/2017: basta haver elementos que
    indiquem). Sem achado → só diligência. Com achado → requisição, e representação só se a defesa for afastada."""
    from compliance_agent.lex_redflags import jurisdicao
    achados = analise.get("achados") or []
    exc = analise.get("exculpatorio") or []
    jur = jurisdicao(analise.get("esfera") or "")
    refutados = [e for e in exc if not e.get("sobrevive")]
    L = []
    if not achados:
        L.append("> **Sem achado: não se propõe representação nem ciência a outros órgãos.** Propõe-se apenas a "
                 "realização das diligências da seção 11 para cobrir as lacunas declaradas.")
        return L
    L.append("| Medida proposta | Fundamento | Achados que a sustentam |")
    L.append("|---|---|---|")
    L.append(f"| Requisição de documentos ao órgão (diligência) | CF/88 arts. 70-71; Lei 14.133/2021, arts. 169-171 | "
             f"{', '.join(a['rf'] for a in achados)} |")
    if refutados:
        L.append(f"| Representação ao {jur['representacao']} se a resposta não afastar o indício | Deliberação TCE-RJ 279/2017 "
                 "(elementos que indiquem) | " + ", ".join(e["rf"] for e in refutados) + " |")
    for d in analise.get("destinatarios") or []:
        if jur["contas"] in str(d.get("destinatario")):
            continue      # o tribunal de contas já está na linha de representação
        rfs = [a["rf"] for a in achados if d.get("familia") in _RF_DESTINATARIO.get(_fam_exculpatorio(a["rf"]), ())
               # R8 de concentração do pago (eixo financeiro) não é conluio: só o R8 de rede/sócio vai ao CADE
               and not (a["rf"] == "R8" and d.get("familia") == "conluio" and eixo_do_achado(a) != "compliance")]
        if not rfs or not any(e["rf"] in rfs for e in refutados):
            continue      # ciência a outro órgão só por achado cuja defesa os dados afastaram
        L.append(f"| Ciência a {d['destinatario']} | {d['motivo']} | {', '.join(rfs)} |")
    L.append("")
    if not refutados:
        L.append("> Todos os indícios mantiveram explicação inocente plausível: **monitoramento + requisição**, sem "
                 "representação nem ciência a outros órgãos nesta fase.")
    else:
        L.append("> Encaminhamento a outro órgão só para achado cuja explicação inocente os dados afastaram; a tipificação "
                 "(improbidade, crime) é do MP-RJ e do Judiciário, após contraditório (art. 5º, LV, CF/88).")
    return L


def _secao_instrucao(ctx, analise, G) -> list[str]:
    from compliance_agent import lex_forense as lfo
    from compliance_agent.lex_render import _secao_responsaveis
    achados = analise.get("achados") or []
    exc = analise.get("exculpatorio") or []
    L = ["## 8. INSTRUÇÃO NO FORMATO DE TRIBUNAL DE CONTAS", "",
         "*Anatomia do achado (TCU/ISSAI, adotada pelo TCE-RJ): critério × condição × causa × efeito, com evidência, "
         "responsáveis e proposta de encaminhamento.*", "", "### 8.1 Matriz de achados", ""]
    if achados:
        L += ["| # | Eixo | Critério | Condição (fato provado) | Causa provável | Efeito potencial | Evidência |",
              "|---|---|---|---|---|---|---|"]
        for a in achados:
            an = _anatomia(a)
            ev = "SIAFE (OB/NL/NE)" if eixo_do_achado(a) in ("financeiro", "contabil") else (
                "padrão da casa + acervo SEI" if a["rf"].startswith("P/") else "fonte citada na condição")
            L.append(f"| {a['rf']} | {G[eixo_do_achado(a)]['nome']} | {_limpo(an['criterio'], 70)} | {_limpo(an['condicao'], 120)} | "
                     f"{_limpo(an['causa'], 70)} | {_limpo(an['efeito'], 70)} | {ev} |")
        L.append("")
    else:
        L += ["> **Nota técnica SEM achado** — nenhum indício nos dados verificados; presunção de regularidade, com as "
              "lacunas declaradas na seção 3.3.", ""]
    L += ["### 8.2 Responsáveis (art. 117 da Lei 14.133/2021)", ""]
    blocos = _secao_responsaveis(analise.get("sei") or [])
    if blocos:
        for b in blocos:
            L += [b, ""]
    else:
        L += ["> Nenhum responsável identificado nos documentos disponíveis — **lacuna de captura ou de instrução**, não "
              "afirmação de que o processo corra sem responsável. Diligência: requisitar o ato de designação de gestor e "
              "fiscal de cada contrato (art. 117).", ""]
    L += ["### 8.3 Passo exculpatório e cenários discriminantes", ""]
    if exc:
        L += ["| Indício | Explicação inocente mais plausível | Os dados a refutam? | Encaminhamento |", "|---|---|---|---|"]
        for e in exc:
            L.append(f"| {e['rf']} {_nome_rf(e['rf'])} | {_limpo(e.get('defesa'), 160)} | "
                     f"{'**Sim** — afastada' if not e.get('sobrevive') else 'Não — plausível'} | **{e.get('encaminhamento')}** |")
        L.append("")
        cen = lfo.secao_cenarios_md(analise)
        if cen:
            L += [cen.replace("### Cenários", "#### Cenários"), ""]
    else:
        L += ["> Sem indício a submeter ao passo exculpatório.", ""]
    L += ["### 8.4 Matriz de risco (P × I)", "", "| Indício | Eixo | P (1-5) | I (1-5) | P×I | Faixa |",
          "|---|---|---:|---:|---:|---|"]
    for a in achados:
        pp, ii, sc = _pi(a)
        L.append(f"| {a['rf']} {_nome_rf(a['rf'])} | {G[eixo_do_achado(a)]['nome']} | {pp} | {ii} | {sc} | {_faixa(sc)} |")
    if not achados:
        L.append("| — | — | — | — | — | — |")
    L.append(f"| **Índice de atenção (soma, teto 100)** | | | | **{score(achados)}** | |")
    L.append("")
    try:
        from compliance_agent import lex_indicadores_fraude as lif
        ind = lif.parecer_indicadores_md(lif.triagem(lif.sinais_do_contexto(ctx, analise)))
        L += [ind.replace("## III-C. TRIAGEM POR INDICADORES DE RISCO DE FRAUDE",
                          "### 8.5 Triagem por indicadores de risco de fraude"), ""]
    except Exception as exc_:  # noqa: BLE001
        logger.warning("triagem de indicadores falhou: %s", exc_)
    L += ["### 8.6 Proposta de encaminhamento", ""]
    L += encaminhamento(analise)
    L.append("")
    L += _secao_sancao(ctx, analise)
    return L


def _secao_sancao(ctx, analise) -> list[str]:
    achados = analise.get("achados") or []
    exc = analise.get("exculpatorio") or []
    monit = {e.get("rf") for e in exc if e.get("sobrevive")}
    base = [a for a in achados if a.get("rf") not in monit]
    L = ["### 8.7 Proposta preliminar de sanção administrativa", ""]
    if not achados:
        return L + ["> Sem achado: não há base para sanção.", ""]
    if not base:
        return L + ["> **Não se propõe sanção nesta fase**: todos os indícios mantiveram explicação inocente plausível "
                    "(monitoramento). Sanção pressupõe achado com defesa afastada e, para multa, dano efetivo ou dolo "
                    "indiciado.", ""]
    # Dosimetria só quando o próprio parecer sustenta a sanção: grau consolidado VERMELHO e (dolo indiciado pela
    # régua da dosimetria OU dano quantificado em achado). Antes a seção projetava "🔴 GRAVE" e multa de 20% sobre o
    # TOTAL PAGO (Engeprat: R$ 105,7 mi) num parecer de indícios, sem dolo nem dano — e a base legal da multa é o
    # valor do CONTRATO (art. 156, §3º), não o pago. Valor de multa não é estimado aqui (20/11/2026).
    try:
        from compliance_agent import lex_sancoes
        prop = lex_sancoes.sugerir_sancoes(base, valor_contrato=0, regime="14133")
    except (ImportError, KeyError, ValueError, TypeError) as exc_:
        return L + [f"> Dosimetria indisponível ({str(exc_)[:80]}).", ""]
    dano = [a["rf"] for a in base if float(a.get("valor") or 0) > 0]
    a_apurar = [a["rf"] for a in base if _elemento_subjetivo(a)[0].startswith("dolo")]
    if analise.get("rotulo") != "VERMELHO" or not (prop.get("dolo") or dano):
        return L + [f"> **Não se propõe sanção nesta fase.** Há {len(base)} indício(s) cuja explicação inocente os dados "
                    f"afastaram ({', '.join(a['rf'] for a in base)}); o grau consolidado é {analise.get('emoji')} "
                    f"{analise.get('rotulo')}; dolo indiciado: {'sim' if prop.get('dolo') else 'não'}; dano quantificado: "
                    f"{'sim (' + ', '.join(dano) + ')' if dano else 'não'}. Sanção pressupõe achado confirmado após "
                    "diligência e contraditório e, para multa, dano efetivo mensurado ou dolo indiciado. "
                    + (f"Elemento subjetivo **a apurar** (não indiciado) em {', '.join(a_apurar)}. " if a_apurar else "")
                    + "Reavaliar após a resposta às diligências (seção 11).", ""]
    md = lex_sancoes.parecer_sancionatorio_md(prop)
    md = md.replace("## IV-C. PROPOSTA PRELIMINAR DE SANÇÃO ADMINISTRATIVA (dosimetria)", "").strip()
    md = "\n".join(("#" + ln) if ln.startswith("### ") else ln for ln in md.split("\n"))
    return L + [md, "", "> **Valor da multa não estimado:** a base legal é o valor do contrato (art. 156, §3º, da Lei "
                "14.133/2021), não o total pago; sem o contrato e o dano apurado, qualquer número seria fabricado.", ""]


def _secao_subjetiva(sub: dict) -> list[str]:
    L = ["## 9. CAMADA SUBJETIVA — juízo raciocinado (OPINIÃO)", "",
         "*Separada da camada determinística: é opinião do Claude Opus pela assinatura sobre os fatos das seções 3 a 8. "
         "Não altera fato nem grau; pode, no máximo, recomendar diligência.*", ""]
    if sub.get("estado") != "OPINIÃO":
        return L + [f"> **INDISPONÍVEL** — {sub.get('motivo') or 'motor não respondeu'}. Nenhum texto foi gerado no "
                    "lugar; o parecer vale pela camada determinística.", ""]
    L += [f"> **Opinião** · motor: {sub.get('modelo')} · confiança declarada: **{sub.get('confianca')}**", ""]
    L += [sub["juizo"], ""]
    if sub.get("explicacao_inocente"):
        L += [f"**Explicação inocente mais plausível (opinião):** {sub['explicacao_inocente']}", ""]
    if sub.get("diligencias"):
        L += ["**Diligências recomendadas pela camada subjetiva:**", ""] + [f"- {d}" for d in sub["diligencias"]] + [""]
    return L


def _secao_conclusao(G) -> list[str]:
    c = G["consolidado"]
    L = ["## 10. CONCLUSÃO — GRAU CONSOLIDADO", "", "| Eixo | Grau | Indícios | P×I | Fundamento |", "|---|---|---:|---:|---|"]
    for k, _ in EIXOS:
        g = G[k]
        L.append(f"| {g['nome']} | {g['emoji']} {g['rotulo']} | {len(g['achados'])} | {g['score']} | {_limpo(g['just'], 120)} |")
    L.append(f"| **Consolidado** | **{c['emoji']} {c['rotulo']}** | **{sum(len(G[k]['achados']) for k, _ in EIXOS)}** | "
             f"**{c['score']}** | {_limpo(c['just'], 120)} |")
    L.append("")
    maior = max((G[k] for k, _ in EIXOS), key=lambda g: {"VERMELHO": 3, "AMARELO": 2, "VERDE": 1}.get(g["rotulo"], 0))
    if c["rotulo"] == "VERMELHO" and maior["rotulo"] != "VERMELHO":
        L.append("> O consolidado sobe acima do maior grau de eixo por **convergência entre eixos** (fontes independentes "
                 "apontando no mesmo sentido — ISSAI 100/300).")
    else:
        L.append(f"> O grau consolidado decorre dos eixos: {c['emoji']} **{c['rotulo']}** — {c['just']}.")
    L.append("")
    return L


def diligencias(analise: dict) -> list[str]:
    """Diligências CONCRETAS (processo, documento, fonte), ordenadas por valor — a primeira linha do sumário."""
    from compliance_agent import lex_forense as lfo
    D = []
    for x in [y for y in analise.get("processos") or [] if y.get("canon")][:3]:
        ac = x.get("acervo") or {}
        falta = ac.get("faltam_fases") or []
        pedido = (f"requisitar {', '.join(falta)}" if falta and ac.get("estado") != INDISPONIVEL else
                  "ler a íntegra (contrato, aditivos, medições/atestos e notas fiscais)")
        D.append(f"Processo **{x['processo']}** (R$ {brl(x['pago'])} pagos em {inteiro(x['n_obs'])} OB, UG "
                 f"{', '.join(x['ugs'])}): {pedido}.")
    for c in lfo.cenarios(analise.get("achados") or [], analise.get("exculpatorio") or [])[:4]:
        D.append(f"Indício **{c['rf']}** — teste discriminante: {c['teste']}.")
    exe = analise.get("execucao") or {}
    if exe.get("tem_nl") and exe.get("pago_sem_nl_na_base", 0) > 0.01:
        D.append(f"Coletar no SIAFE as NL/NE das OBs sem liquidação ingerida (R$ {brl(exe['pago_sem_nl_na_base'])}) — "
                 "só então comparar empenhado × liquidado × pago como totais.")
    sem = [x for x in analise.get("processos") or [] if not x.get("canon")]
    if sem:
        D.append(f"Identificar o processo SEI da(s) {inteiro(sum(x['n_obs'] for x in sem))} OB sem nº reconhecível "
                 f"(R$ {brl(sum(x['pago'] for x in sem))}) pelo espelho da OB/PD no SIAFE.")
    if not (analise.get("tcerj") or {}).get("n_contratos"):
        D.append("Obter o(s) contrato(s) e aditivos (PNCP / processo SEI) para confrontar pago × valor contratado e o "
                 "limite do art. 125 da Lei 14.133/2021.")
    D.append("Requisitar o ato de designação de gestor e fiscal de cada contrato (art. 117 da Lei 14.133/2021).")
    return D


def _secao_diligencias(ctx, analise, dil) -> list[str]:
    L = ["## 11. DILIGÊNCIAS, QUESITOS E MINUTA DE REQUISIÇÃO", "", "### 11.1 Diligências (ordem de prioridade)", ""]
    L += [f"{i}. {d}" for i, d in enumerate(dil, 1)]
    L += ["", "### 11.2 Quesitos", ""]
    q = ["Qual o instrumento (contrato/ata/termo) que lastreia cada OB paga listada no Anexo A, e qual o seu valor "
         "atualizado com aditivos?",
         "Para cada OB, qual a nota fiscal e o atesto/medição que a liquidaram (data e responsável)?",
         "Houve retenção de ISS, IR e INSS em cada pagamento? Juntar as guias de recolhimento."]
    from compliance_agent import lex_forense as lfo
    for c in lfo.cenarios(analise.get("achados") or [], analise.get("exculpatorio") or []):
        q.append(f"Indício {c['rf']} ({_nome_rf(c['rf'])}): apresentar {c['teste']} — o documento que distingue a "
                 f"hipótese benigna («{_limpo(c['benigno'], 110)}») da hipótese de risco («{_limpo(c['risco'], 90)}»).")
    L += [f"{i}. {x}" for i, x in enumerate(q, 1)]
    procs = [x for x in analise.get("processos") or [] if x.get("canon")][:5]
    orgaos = sorted({u for x in procs for u in x["ugs"]})
    L += ["", "### 11.3 Minuta de ofício de requisição", "",
          f"> **Ofício nº ____/____** — Ao(À) Ordenador(a) de Despesa da(s) UG {', '.join(orgaos) or '________'}.",
          ">",
          f"> Com fundamento nos arts. 70 e 71 da Constituição Federal, nos arts. 169 a 171 da Lei 14.133/2021 e no "
          f"dever de prestar contas, requisitam-se, no prazo de 15 (quinze) dias, os documentos abaixo relativos aos "
          f"pagamentos ao fornecedor {ctx.get('nome', '')} (CNPJ {fmt_cnpj(analise['cnpj'])}):",
          ">"]
    for x in procs:
        ac = x.get("acervo") or {}
        falta = ac.get("faltam_fases") or ["íntegra do processo"]
        L.append(f"> - **{x['processo']}** (R$ {brl(x['pago'])} pagos): {', '.join(falta)}; contrato e aditivos; "
                 "notas fiscais, atestos e medições; guias de retenção; ato de designação do fiscal.")
    if not procs:
        L.append("> - relação dos processos de contratação e pagamento do fornecedor, com contrato, aditivos, notas "
                 "fiscais, atestos/medições e guias de retenção.")
    L += [">", "> A requisição não constitui juízo de irregularidade; visa a instruir exame sob presunção de legitimidade "
          "dos atos administrativos.", ""]
    return L


def _secao_ressalvas(ctx) -> list[str]:
    return ["## 12. RESSALVAS", "",
            "1. Os apontamentos são **indícios**, sujeitos a contraditório e ampla defesa (art. 5º, LV, CF/88).",
            "2. Vigora a **presunção de legitimidade** dos atos administrativos; a dúvida sobre a economicidade favorece "
            "o gestor.",
            "3. **Não se afirma crime, improbidade ou dolo** — competência do tribunal de contas, do MP-RJ e do Judiciário.",
            "4. As conclusões se limitam aos dados verificados (seção 3); lacunas geram **diligência**, não condenação.",
            "5. Pagamento é só a OB paga do SIAFE pela régua da casa; empenho e liquidação aparecem como piso quando a "
            "ingestão é parcial; o espelho TFE não é usado como pago.",
            "6. A camada subjetiva (seção 9) é opinião e não integra a prova.", "",
            f"_Parecer gerado por sistema de controle externo em {ctx.get('data', '')}. Não substitui parecer jurídico "
            "formal._", ""]


def _anexo_obs(analise) -> list[str]:
    p = analise["ctx"].get("pagamentos") or {}
    base = analise.get("base") or {}
    L = ["## ANEXO A — ORDENS BANCÁRIAS DO ALVO (SIAFE)", ""]
    linhas = [x for b in (p.get("por_ano") or {}).values() for x in b.get("linhas") or []]
    if linhas:
        L += [f"*{inteiro(len(linhas))} OB pagas (valor > 0), em ordem de data — soma R$ {brl(p['total_geral'])}. "
              f"Fonte: {lf.FONTE_OB}.*", "", "| Nº OB | Data | UG | NL | Valor (R$) | Estado |", "|---|---|---|---|---:|---|"]
        for x in sorted(linhas, key=lambda y: (y["data"], y["numero_ob"])):
            L.append(f"| {x['numero_ob']} | {x['data']} | {x['ug']} | {x['nl'] or '—'} | {brl(x['valor'])} | paga |")
        L.append(f"| **Total** | | | | **{brl(p['total_geral'])}** | |")
        L.append("")
    nao = base.get("nao_pagas") or []
    reg = base.get("regularizacoes") or []
    if nao or reg:
        L += ["**OB fora do pago (não somadas):**", "", "| Nº OB | Data | UG | Valor (R$) | Motivo |", "|---|---|---|---:|---|"]
        for d in sorted(reg + nao, key=lambda y: (y["data"], y.get("numero_ob") or "")):
            L.append(f"| {d.get('numero_ob') or '—'} | {d['data'] or '—'} | {d.get('ug_emitente')} | {brl(d['valor'])} | "
                     f"{d.get('motivo') or 'regularização (valor zero)'} |")
        L.append("")
    if not linhas and not nao and not reg:
        L += ["> Nenhuma OB do alvo na base SIAFE consultada.", ""]
    return L


def _anexo_fontes(analise) -> list[str]:
    base = analise.get("base") or {}
    exe = analise.get("execucao") or {}
    pad = analise.get("padroes") or {}
    cad = analise.get("cadastro") or {}
    tc = analise.get("tcerj") or {}
    L = ["## ANEXO B — FONTES CONSULTADAS", "", "| Fonte | O que forneceu | Atualização | Estado |", "|---|---|---|---|",
         f"| {lf.FONTE_OB} | OB do alvo (paga e não paga) | coleta mais recente das OB do alvo: {str(base.get('coletado_em') or '—')[:19]} | "
         f"**{base.get('estado')}** |",
         f"| {lf.FONTE_NL} | liquidações do credor | {max((str(n.get('coletado_em') or '') for n in base.get('nl') or []), default='—')[:19]} | "
         f"**{PENDENTE if exe.get('tem_nl') else INDISPONIVEL}** |",
         f"| {lf.FONTE_NE} | empenhos do credor | {max((str(n.get('coletado_em') or '') for n in base.get('ne') or []), default='—')[:19]} | "
         f"**{PENDENTE if exe.get('tem_ne') else INDISPONIVEL}** |",
         f"| {cad.get('fonte') or 'Receita Federal'} | cadastro e QSA | — | **{VERIFICADO if cad.get('tem') else INDISPONIVEL}** |",
         f"| TCE-RJ Dados Abertos (contratos e compras diretas) | {tc.get('n_contratos', 0)} contrato(s), {tc.get('n_compras_diretas', 0)} "
         f"compra(s) | consulta nesta execução | **{VERIFICADO if (tc.get('n_contratos') or tc.get('n_compras_diretas')) else PENDENTE}** |",
         f"| Acervo SEI da casa (data/sei_arquivo) | fases documentadas dos maiores processos | manifesto por processo | "
         f"**{VERIFICADO if any((x.get('acervo') or {}).get('estado') == VERIFICADO for x in analise.get('processos') or []) else PENDENTE}** |"]
    for x in pad.get("lidos") or []:
        L.append(f"| Padrão da casa `{x['id']}` (data/padroes) | {x['n_achados']} achado(s) no universo | {x['gerado_em'] or '—'} | "
                 f"**{VERIFICADO}** |")
    L.append("")
    return L


def _anexo_normas() -> list[str]:
    return ["## ANEXO C — BASE NORMATIVA CITADA", "",
            "| Norma | Dispositivos | Uso no parecer |", "|---|---|---|",
            "| CF/88 | arts. 5º, LV; 37; 70-71 | contraditório; princípios; controle externo |",
            "| Lei 4.320/64 | arts. 36, 58-65 | restos a pagar; estágios da despesa |",
            "| Lei 14.133/2021 | arts. 5º, 9º, 11, 14, 18, 23, 25 §4º, 62-70, 72-75, 117, 125, 156, 169-171 | licitação, "
            "contratação direta, fiscalização, aditivos, sanções, controle |",
            "| Decreto-Lei 4.657/42 (LINDB) | arts. 20-22 e 28 | consequências práticas; erro grosseiro |",
            "| Lei 8.429/92 (red. Lei 14.230/2021) | arts. 9º-11 | improbidade só com dolo; art. 10 com dano efetivo |",
            "| Lei 12.846/2013 e Decreto 11.129/2022 | art. 5º, IV; programa de integridade | responsabilização da PJ |",
            "| LC 116/2003; CF/88 | art. 6º; art. 157, I | retenção de ISS pelo tomador; IR retido pertence ao Estado |",
            "| Deliberação TCE-RJ 279/2017 | — | rito de tomada de contas (limiar: elementos que indiquem) |", ""]


# ─────────────────────────────── montagem ───────────────────────────────

def renumerar(md: str) -> str:
    """Subseções '### N.M' renumeradas em sequência dentro de cada '## N.' — subseção que não se aplica (sem dado)
    some do texto e a numeração não pode ficar com buraco (o golden antigo ia de 1 a 2 e pulava para 5 e 6)."""
    out, sec, sub_ = [], None, 0
    rx_sec = re.compile(r"^## (\d+)\. ")
    rx_sub = re.compile(r"^### (\d+)\.(\d+) ")
    for ln in md.split("\n"):
        m = rx_sec.match(ln)
        if m:
            sec, sub_ = m.group(1), 0
        else:
            m2 = rx_sub.match(ln)
            if m2 and m2.group(1) == sec:
                sub_ += 1
                ln = f"### {sec}.{sub_} " + ln[m2.end():]
        out.append(ln)
    return "\n".join(out)


def montar(ctx_in: dict, analise: dict) -> str:
    """Markdown completo do parecer referência de fornecedor."""
    from compliance_agent import lex_subjetiva
    analise.setdefault("ctx", ctx_in)
    analise.setdefault("cnpj", ctx_in.get("cnpj", ""))
    ctx = analise["ctx"]
    for x in analise.get("processos") or []:
        if x.get("canon") and "acervo" not in x and (analise.get("processos") or []).index(x) < 20:
            x["acervo"] = lf.acervo_processo(x["canon"])
    exc_por_rf = {}
    for e in analise.get("exculpatorio") or []:
        exc_por_rf.setdefault(e.get("rf"), e)
    G = graus(analise)
    F = quadro_de_fatos(analise)
    M = mapa_de_cobertura(analise)
    lac = _lacunas(analise)
    dil = diligencias(analise)
    sub = analise.get("subjetiva") or lex_subjetiva.avaliar(
        f"{ctx.get('nome', '')} (CNPJ {fmt_cnpj(analise['cnpj'])})", F, analise.get("achados") or [], lac)
    analise["subjetiva"] = sub
    c = G["consolidado"]
    achados = analise.get("achados") or []
    L = [f"# PARECER REFERÊNCIA — {ctx.get('nome', '')}",
         "### Avaliação jurídica, financeira, contábil e de integridade de contratação e pagamentos", "",
         "*Instrução preliminar de controle externo (TCE-RJ) — camada determinística + camada subjetiva*", "",
         f"**CNPJ:** {fmt_cnpj(analise['cnpj'])}  |  **Data:** {ctx.get('data', '')}  |  **Analista:** Controle Externo (automatizado)",
         f"**Classificação (modelo CGE-RJ — Decreto 47.408/2020):** Nota Técnica **{'COM' if achados else 'SEM'} Achado**.",
         f"**Grau de atenção:** {c['emoji']} **{c['rotulo']}** · índice {c['score']}/100 — {c['just']}.",
         f"**Base de pagamentos:** {lf.FONTE_OB} · coleta mais recente das OB do alvo: "
         f"{str((analise.get('base') or {}).get('coletado_em') or '—')[:19]}.", "", "---", ""]
    L += _secao_sumario(ctx, analise, G, F, lac, dil)
    L += _secao_metodo()
    L += _secao_base(ctx, analise, F, M)
    L += _secao_financeiro(ctx, analise, G, exc_por_rf)
    L += _secao_contabil(ctx, analise, G, exc_por_rf)
    L += _secao_juridico(ctx, analise, G, exc_por_rf)
    L += _secao_compliance(ctx, analise, G, exc_por_rf)
    L += _secao_instrucao(ctx, analise, G)
    L += _secao_subjetiva(sub)
    L += _secao_conclusao(G)
    L += _secao_diligencias(ctx, analise, dil)
    L += _secao_ressalvas(ctx)
    L += _anexo_obs(analise)
    L += _anexo_fontes(analise)
    L += _anexo_normas()
    return renumerar("\n".join(L))


# ═══════════════════════════════ PARECER DE ÓRGÃO (UG) ═══════════════════════════════

def eixo_do_achado_orgao(a: dict) -> str:
    rf = str(a.get("rf") or "")
    if rf in ("R8", "R2"):
        return "financeiro"
    if rf == "R10":
        return "contabil"
    if rf in ("R7",) or rf.startswith("DD/"):
        return "compliance"
    return "juridico"


def montar_orgao(ctx: dict, analise: dict) -> str:
    """Parecer referência de ÓRGÃO — mesma anatomia do de fornecedor (eixos, base única SIAFE, sumário,
    encaminhamento derivado dos achados). `analise` = {achados, emoji, rotulo, just, base, jurisdicao}."""
    from compliance_agent import lex_forense as lfo
    from compliance_agent.lex_redflags import _exculpatorio, jurisdicao
    p = ctx.get("pagamentos") or {}
    base = analise.get("base") or {}
    achados = analise.get("achados") or []
    jur = analise.get("jurisdicao") or jurisdicao("")
    for a in achados:
        a.setdefault("eixo", eixo_do_achado_orgao(a))
    exc = _exculpatorio(achados)
    exc_por_rf = {e["rf"]: e for e in exc}
    G = {}
    for k, nome in EIXOS:
        lst = [a for a in achados if a["eixo"] == k]
        e, r, j = _grau(lst)
        if not lst and k in ("financeiro", "contabil") and not p.get("tem_dados"):
            e, r, j = "⚪", "SEM BASE", base.get("motivo") or "nenhuma OB paga do SIAFE para a UG"
        G[k] = {"nome": nome, "emoji": e, "rotulo": r, "just": j, "achados": lst, "score": score(lst)}
    G["consolidado"] = {"emoji": analise["emoji"], "rotulo": analise["rotulo"], "just": analise["just"],
                        "score": score(achados)}
    ug = ctx.get("ug", "")
    F = []
    if base.get("estado") != VERIFICADO:
        F.append(lf.fato("OB paga (SIAFE)", "não lida", lf.FONTE_OB, INDISPONIVEL, base.get("motivo", "")))
    elif not p.get("tem_dados"):
        F.append(lf.fato("OB paga (SIAFE)", "nenhuma OB paga da UG", lf.FONTE_OB, VERIFICADO))
    else:
        tot = p["total_geral"]
        F += [lf.fato("Total pago pela UG (OB SIAFE, valor > 0)", f"R$ {brl(tot)}", lf.FONTE_OB, VERIFICADO),
              lf.fato("Nº de OBs pagas", inteiro(p["n_geral"]), lf.FONTE_OB, VERIFICADO),
              lf.fato("Favorecidos distintos", inteiro(len(p["por_favorecido_geral"])), lf.FONTE_OB, VERIFICADO)]
        top_n, top_v = next(iter(p["por_favorecido_geral"].items()))
        F.append(lf.fato("Maior favorecido", f"{top_n} — R$ {brl(top_v)} ({pct(top_v / tot * 100)}%)", lf.FONTE_OB, VERIFICADO))
        hhi = p.get("hhi") or {}
        F.append(lf.fato("Concentração por favorecido (HHI)", f"{pct(float(hhi.get('indice') or 0))} ({hhi.get('nivel')})",
                         f"derivado de {lf.FONTE_OB}", VERIFICADO))
        F.append(lf.fato("OB de valor zero (regularização)", inteiro(p.get("n_regularizacoes")), lf.FONTE_OB, VERIFICADO))
        nao = base.get("nao_pagas") or []
        F.append(lf.fato("OB registradas e NÃO pagas", f"{inteiro(len(nao))} — R$ {brl(sum(d['valor'] for d in nao))}",
                         lf.FONTE_OB, VERIFICADO))
        if base.get("coletado_em"):
            F.append(lf.fato("Última coleta das OBs da UG", str(base["coletado_em"])[:19], lf.FONTE_OB, VERIFICADO))
    c = G["consolidado"]
    L = [f"# PARECER REFERÊNCIA — ÓRGÃO {ctx.get('nome', '')} (UG {ug})",
         "### Avaliação jurídica, financeira, contábil e de integridade da execução da despesa", "",
         f"**UG:** {ug}  |  **Data:** {ctx.get('data', '')}  |  **Analista:** Controle Externo (automatizado)",
         f"**Grau de atenção:** {c['emoji']} **{c['rotulo']}** · índice {c['score']}/100 — {c['just']}.",
         f"**Base de pagamentos:** {lf.FONTE_OB}.", "", "---", ""]
    if jur.get("esfera") == "municipal-rio":
        L += [f"> **Competência (esfera municipal-Rio):** o controle externo desta despesa é do **{jur['contas_nome']}**, "
              f"não do TCE-RJ ({jur['base_competencia']}); controle interno: **{jur['controle_interno']}**.", ""]
    lac = []
    if base.get("estado") != VERIFICADO:
        lac.append("pagamentos SIAFE não lidos")
    lac += ["contratos, certames e medições do órgão não examinados (só pagamentos e cadastro dos favorecidos)",
            "empenho e liquidação da UG não confrontados com o pago neste parecer"]
    L += ["## 1. SUMÁRIO EXECUTIVO", "",
          f"- **Grau consolidado:** {c['emoji']} **{c['rotulo']}** · índice **{c['score']}/100** — "
          + (f"{len(achados)} indício(s), gravidade máxima {max(a['grav'] for a in achados)}/5." if achados else f"{c['just']}.")]
    fv = [f for f in F if f["estado"] == VERIFICADO][:3]
    if fv:
        L.append("- **Fatos mais relevantes:**")
        L += [f"  - {f['fato']}: **{f['valor']}** — fonte {f['fonte']} · {f['estado']}." for f in fv]
    for a in sorted(achados, key=lambda x: -x["grav"])[:3]:
        L.append(f"  - Indício **{a['rf']}** ({_nome_rf(a['rf'])}, grav. {a['grav']}/5): {_limpo(a['obs'], 200)}")
    L.append("- **Não verificado:** " + "; ".join(lac) + ".")
    dil = []
    if p.get("tem_dados"):
        # folha, tributos, fundos e entes públicos não têm "contrato a requisitar" (FOLHA DE PAGAMENTOS saía como
        # 2º "fornecedor" do ITERJ na lista de diligências)
        _inst = re.compile(r"FOLHA|INSS|RECEITA FEDERAL|TESOURO|FUNDO|PREFEITURA|MUNIC[IÍ]PIO|SECRETARIA|BANCO|"
                           r"CAIXA ECON|TRIBUNAL|ESTADO DO RIO|PREVID|PROCURADORIA|DEFENSORIA", re.I)
        top = [(n, v) for n, v in p["por_favorecido_geral"].items() if not _inst.search(str(n))][:3]
        dil += [f"Requisitar à UG {ug} os contratos, certames e medições dos pagamentos a **{n}** (R$ {brl(v)})."
                for n, v in top]
    for cc in lfo.cenarios(achados, exc)[:3]:
        dil.append(f"Indício **{cc['rf']}** — teste discriminante: {cc['teste']}.")
    if dil:
        L.append("- **Diligências prioritárias:**")
        L += [f"  - {d}" for d in dil[:4]]
    L += ["", "## 2. OBJETO, ESCOPO E METODOLOGIA", "",
          "Execução da despesa da UG examinada pelos eixos financeiro, contábil, jurídico e de integridade, a partir "
          "da **OB paga do SIAFE** (régua `_ob_paga`; o espelho TFE não é usado como pago). Camada determinística "
          "apenas; indício ≠ acusação; INDISPONÍVEL ≠ 0. Régua do grau: 🟢 sem indício; 🟡 indício pontual; 🔴 "
          "convergência de 3+ indícios com um grave; ⚪ sem base.", "",
          "## 3. BASE DE FATOS", ""]
    L += _tab_fatos(F) + [""]
    L += ["## 4. EIXO FINANCEIRO", "", "*Critério: Lei 4.320/64, arts. 58-65; competitividade (Lei 14.133/2021, art. 11).*", ""]
    if p.get("tem_dados"):
        tot = p["total_geral"]
        L += ["| Ano | OBs | Total (R$) |", "|---|---:|---:|"]
        L += [f"| {a} | {inteiro(b['n'])} | {brl(b['total'])} |" for a, b in p["por_ano"].items()]
        L += [f"| **Total** | **{inteiro(p['n_geral'])}** | **{brl(tot)}** |", "",
              "| Favorecido | Pago (R$) | % do pago |", "|---|---:|---:|"]
        favs = list(p["por_favorecido_geral"].items())
        L += [f"| {_limpo(n, 60)} | {brl(v)} | {pct(v / tot * 100)}% |" for n, v in favs[:15]]
        if len(favs) > 15:
            vr = tot - sum(v for _, v in favs[:15])
            L.append(f"| demais {len(favs) - 15} favorecido(s) | {brl(vr)} | {pct(vr / tot * 100)}% |")
        L.append("")
    L += _lista_indicios(G["financeiro"]["achados"], exc_por_rf) or ["> Nenhum indício financeiro.", ""]
    L += _conclusao_eixo(G, "financeiro")
    L += ["## 5. EIXO CONTÁBIL", "", "*Critério: Lei 4.320/64, arts. 62-65 (pagamento após liquidação; OB devolvida não é pago).*", ""]
    nao = base.get("nao_pagas") or []
    if nao:
        mot: dict = {}
        for d in nao:
            m = mot.setdefault(d["motivo"], [0, 0.0])
            m[0] += 1
            m[1] += d["valor"]
        L += ["| OB fora do pago — motivo | OBs | Valor (R$) |", "|---|---:|---:|"]
        L += [f"| {k} | {inteiro(n)} | {brl(v)} |" for k, (n, v) in sorted(mot.items(), key=lambda kv: -kv[1][1])]
        L.append("")
    L += _lista_indicios(G["contabil"]["achados"], exc_por_rf) or ["> Nenhum indício contábil.", ""]
    L += _conclusao_eixo(G, "contabil")
    L += ["## 6. EIXO JURÍDICO", "", "*Critério: Lei 14.133/2021, arts. 72-75 (contratação direta) e 147-149 (nulidade e "
          "indenização); LINDB, arts. 20-22 e 28.*", ""]
    if analise.get("conluio_md"):
        L += [analise["conluio_md"], ""]
    L += _lista_indicios(G["juridico"]["achados"], exc_por_rf) or ["> Nenhum indício jurídico nas fontes lidas.", ""]
    L += _conclusao_eixo(G, "juridico")
    L += ["## 7. EIXO COMPLIANCE / INTEGRIDADE", "", "*Critério: Lei 12.846/2013; Lei 14.133/2021, arts. 14 e 156.*", ""]
    L += _lista_indicios(G["compliance"]["achados"], exc_por_rf) or ["> Nenhum indício de integridade nos favorecidos.", ""]
    L += _conclusao_eixo(G, "compliance")
    L += ["## 8. INSTRUÇÃO NO FORMATO DE TRIBUNAL DE CONTAS", "", "### 8.1 Matriz de achados", ""]
    if achados:
        L += ["| # | Eixo | Critério | Condição | Causa provável | Efeito potencial |", "|---|---|---|---|---|---|"]
        for a in achados:
            an = _anatomia(a)
            L.append(f"| {a['rf']} | {G[a['eixo']]['nome']} | {_limpo(an['criterio'], 70)} | {_limpo(an['condicao'], 120)} | "
                     f"{_limpo(an['causa'], 60)} | {_limpo(an['efeito'], 60)} |")
        L.append("")
        L += ["### 8.2 Passo exculpatório", "", "| Indício | Explicação inocente | Refutada? | Encaminhamento |",
              "|---|---|---|---|"]
        L += [f"| {e['rf']} | {_limpo(e['defesa'], 140)} | {'Sim' if not e['sobrevive'] else 'Não'} | **{e['encaminhamento']}** |"
              for e in exc]
        L.append("")
    else:
        L += ["> Nota técnica SEM achado nos pagamentos examinados.", ""]
    L += ["### 8.3 Matriz de risco (P × I)", "", "| Indício | P | I | P×I | Faixa |", "|---|---:|---:|---:|---|"]
    for a in achados:
        pp, ii, sc = _pi(a)
        L.append(f"| {a['rf']} {_nome_rf(a['rf'])} | {pp} | {ii} | {sc} | {_faixa(sc)} |")
    if not achados:
        L.append("| — | — | — | — | — |")
    L += ["", "### 8.4 Proposta de encaminhamento", ""]
    L += encaminhamento({"achados": achados, "exculpatorio": exc, "destinatarios": [],
                         "esfera": jur.get("esfera")})
    L += ["", "## 9. CAMADA SUBJETIVA", "",
          "> **INDISPONÍVEL** — o parecer de órgão não aciona a camada subjetiva; vale a camada determinística.", "",
          "## 10. CONCLUSÃO — GRAU CONSOLIDADO", "", "| Eixo | Grau | Indícios |", "|---|---|---:|"]
    L += [f"| {G[k]['nome']} | {G[k]['emoji']} {G[k]['rotulo']} | {len(G[k]['achados'])} |" for k, _ in EIXOS]
    L += [f"| **Consolidado** | **{c['emoji']} {c['rotulo']}** | **{len(achados)}** |", "",
          f"> {c['emoji']} **{c['rotulo']}** — {c['just']}.", "",
          "## 11. RESSALVAS", "",
          "1. Baseado em pagamentos (OB paga do SIAFE) e no cadastro dos favorecidos, sem exame documental dos contratos.",
          "2. Indícios a verificar, não conclusão de irregularidade; vigora a presunção de legitimidade.",
          f"3. Controle externo competente: {jur['contas_nome']}.", ""]
    return renumerar("\n".join(L))
