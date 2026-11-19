# -*- coding: utf-8 -*-
"""Aditivo "de 25%" que ESTENDE a faixa de volume remunerado (o teto de pagamento por demanda), e volume inflado por
item que não é o serviço contratado.

ORIGEM (perícias integrais 18/11/2026, Poupa Tempo / Consórcio RJ Cidadão — SEI-150001/000217/2025, 000224/2025 e
002095/2024): o Contrato 010/2023 paga por FAIXA de média diária de atendimentos, até "FAIXA 5 9.501 10.500 10.000";
o 2º TA, rotulado "acréscimo ... no percentual de 25%", "passa a permitir ... a faixa de até 20.000 atendimentos/dia"
— o teto de volume remunerado dobra (+100%). E o "Acesso Gratuito à Internet (POUPA TEMPO VIRTUAL)" entra na
contagem de atendimentos (~22%), quando o contrato exclui serviços de apoio ("cópia, fotografia, lanchonete...").

DOIS SINAIS:
  (a) faixa estendida (forte/medio): termo aditivo próprio com "faixa de até N <unidade>" e o contrato do processo
      com tabela de faixas cujo máximo é M; extensão = N/M − 1. forte = extensão ≥ 2 × percentual declarado e acima
      do teto (limites_aditivo); medio = extensão > declarado + 10 p.p.
  (b) internet como atendimento (medio): relatório que lista "Acesso Gratuito à Internet" com número de
      atendimentos na contagem que define a faixa.
EXPLICAÇÕES INOCENTES: a faixa estendida pode ser só "permissão havendo saldo" — o valor do termo continua 25%; o
vício está em remunerar volume que o contrato não previa (quantitativo +100%) sob rótulo de 25%. Internet pode estar
prevista no TR como serviço — conferir o TR antes de concluir.
"""
from __future__ import annotations

import re

from compliance_agent import limites_aditivo as L
from compliance_agent.padroes import _aditivos_comum as C
from compliance_agent.reporting.intel_base import moeda

ID = "faixa_de_volume_estendida"
_RE_FAIXA_NOVA = re.compile(r"faixa\s+de\s+at[ée]\s+([\d.]{3,9})\s+(atendimentos|refei[çc][õo]es|exames|procedimentos|"
                            r"di[áa]rias|usu[áa]rios|consultas)", re.I)
_RE_LINHA_FAIXA = re.compile(r"FAIXA\s*\d{1,2}\s*\n\s*([\d.]{1,9})\s*\n\s*([\d.]{1,9})\s*\n\s*([\d.]{1,9})", re.I)
_RE_TIT_CONTRATO = re.compile(r"^\s*contrato\b", re.I)
_RE_INTERNET = re.compile(r"acesso\s+gratuito\s+[àa]\s+internet[^\n]{0,80}?([\d.]{3,9})\s+atendimentos", re.I)


def _int(s: str) -> int | None:
    try:
        return int(s.replace(".", ""))
    except ValueError:
        return None


def maximo_faixa(texto: str) -> int | None:
    """Maior limite de faixa ('ATÉ') na tabela 'FAIXA k / DE / ATÉ / FATOR'. Função pura."""
    texto = C.sem_rodape(texto)
    vals = [_int(m.group(2)) for m in _RE_LINHA_FAIXA.finditer(texto)]
    vals = [v for v in vals if v]
    return max(vals) if vals else None


def faixas_novas(texto: str) -> list[dict]:
    texto = C.sem_rodape(texto)
    out = []
    for m in _RE_FAIXA_NOVA.finditer(texto):
        if not C.no_corpo(texto, m.start()):
            continue
        n = _int(m.group(1))
        if not n:
            continue
        ds = [x for x in C.declaracoes_de_acrescimo(texto) if abs(x["pos"] - m.start()) < 6000]
        out.append({"novo_max": n, "unidade": m.group(2).lower(), "pct": ds[0]["pct"] if ds else None,
                    "data": C.data_assinatura_apos(texto, m.end()), "trecho": C.trecho(texto, m.start(), m.end(), 140)})
    return out


def grau_extensao(ext: float, pct: float | None, teto: float) -> str | None:
    p = (pct or 0) / 100
    if pct is not None and ext >= 2 * p and ext > teto:
        return "forte"
    if ext > p + 0.10:
        return "medio"
    return None


def varrer(limite: int | None = None) -> dict:
    idx = C.indice(limite=limite)["processos"]
    funil = {"processos": len(idx), "termo_com_faixa_nova": 0, "com_faixa_original": 0, "faixa_estendida": 0,
             "internet_como_atendimento": 0}
    cob = {"termo_com_faixa_sem_contrato_nos_autos": 0}
    achados = []
    for tag, p in idx.items():
        termos, _ = C.termos_do_processo(p)
        novas = [(d, x) for d, t in termos for x in faixas_novas(t)]
        chave = C.chave_de_tag(tag)
        if novas:
            funil["termo_com_faixa_nova"] += 1
            orig, doc_orig = None, None
            for d in p["docs"]:
                if d.get("alheio") or not _RE_TIT_CONTRATO.search(d["titulo"] or "") or C.eh_termo_aditivo(d):
                    continue
                mx = maximo_faixa(C.ler(d))
                if mx and (orig is None or mx > orig):
                    orig, doc_orig = mx, d
            if orig is None:
                cob["termo_com_faixa_sem_contrato_nos_autos"] += 1
            else:
                funil["com_faixa_original"] += 1
                d, x = max(novas, key=lambda dx: dx[1]["novo_max"])
                ext = x["novo_max"] / orig - 1
                teto = L.teto_acrescimo(None)
                g = grau_extensao(ext, x["pct"], teto)
                if g:
                    funil["faixa_estendida"] += 1
                    achados.append(C.achado(
                        chave, g, sinal="faixa_estendida",
                        prova=(f"doc {doc_orig['i']} ({doc_orig['titulo'][:50]}) — maior faixa remunerada "
                               f"{moeda(orig)[:-3]} {x['unidade']}/dia; doc {d['i']} ({d['titulo'][:50]}) — \"{x['trecho']}\""),
                        porque=(f"O termo estende o volume remunerado de {moeda(orig)[:-3]} para {moeda(x['novo_max'])[:-3]} "
                                f"(+{ext:.0%})" + (f" sob acréscimo declarado de {x['pct']:.2f}%" if x["pct"] is not None else "")
                                + f". Teto de acréscimo {teto:.0%} se mede pelo objeto (quantitativo), não só pelo valor do termo."),
                        fonte=f"contrato + termo aditivo ({p['fonte']})", faixa_original=orig,
                        faixa_nova=x["novo_max"], extensao=round(ext, 4), pct_declarado=x["pct"]))
        provas = []
        for d in p["docs"]:
            if d.get("alheio") or not re.search(r"gerencial", d["titulo"] or "", re.I):
                continue
            t = C.ler(d, 40000)
            m = _RE_INTERNET.search(t)
            if m:
                provas.append(f"doc {d['i']} ({d['titulo'][:50]}) — \"{C.trecho(t, m.start(), m.end(), 60)}\"")
        if provas:
            funil["internet_como_atendimento"] += 1
            achados.append(C.achado(
                chave, "medio", sinal="internet_como_atendimento", prova="; ".join(provas[:3]),
                porque=("Acesso gratuito à internet contado como atendimento na base que define a faixa de pagamento. "
                        "Conferir no TR se o serviço é atendimento remunerado; o contrato exclui serviços de apoio."),
                fonte=f"relatórios gerenciais ({p['fonte']})", n_relatorios=len(provas)))
    return C.resultado(ID, funil["processos"], cob, achados, funil)
