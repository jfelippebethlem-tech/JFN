# -*- coding: utf-8 -*-
"""Gestor da parceria (ou membro da comissão de monitoramento e avaliação) aparece RECEBENDO da OSC que fiscaliza.

ORIGEM (perícia por agente, 18/11/2026): FIA/RJ × FUNRIO, SEI-310002/000054/2025 (Termo de Fomento 001/2025, PTPA).
Doc 44 (Portaria FIA 747/2025) designa "Patrícia Maria Ribeiro, Id. Funcional 515891-1 – Gestor da Parceria"; doc 8
(Comprovante de Pagamento – Bolsa + CLT, prestação de contas da OSC) traz 12 PIX de R$ 10.000,00 a "PATRICIA MARIA
RIBEIRO" pagos pela FUNRIO. Lei 13.019/2014 art. 35 §6º: não pode ser designado gestor/comissão quem tenha mantido,
nos últimos 5 anos, relação jurídica com a OSC partícipe — receber dela no curso da parceria é o caso extremo.

MÉTODO (duas passadas em TODAS as parcerias do acervo):
  1. designações: em portaria/publicação/ato de processo de parceria que fale de gestor ou comissão de monitoramento,
     o nome seguido de "Id. Funcional"/"ID"/"matrícula" (é o servidor no exercício da função — prova = a portaria);
  2. pagamentos: nos documentos de prestação de contas da OSC (comprovantes, folha, bolsas, extratos, planilhas,
     recibos) o MESMO nome completo (normalizado, ≥ 3 tokens fora partículas) com valor em R$ a ≤ 200 caracteres.

GRAU: forte = designado e pago no MESMO processo; medio = designado numa parceria e pago na prestação de contas de
OUTRA (pode ser vínculo legítimo com outra OSC — e ainda assim é relação jurídica a declarar, art. 35 §6º).

EXPLICAÇÕES INOCENTES AVALIADAS (regra no código):
  · homônimo — só nome completo com ≥ 3 tokens significativos; nome curto ("Patricia Ribeiro") não casa;
  · o nome aparece porque o gestor é DESTINATÁRIO/analista do documento ("À Gestora …", "Comissão …", "analisado por")
    — ocorrência com função do Estado a ≤ 40 caracteres antes é descartada; documento do órgão (despacho, ofício,
    parecer, e-mail, portaria) não é prestação de contas e não é lido na passada 2;
  · servidor que deixou o cargo antes do pagamento — não descartado pelo código (data da exoneração fora do acervo):
    pedir a ficha funcional.
CPF sempre mascarado. Nome de pessoa física só porque é agente público designado em portaria (prova citada).
"""
from __future__ import annotations

import re
from collections import defaultdict

from compliance_agent.padroes import _pagamento_comum as C
from compliance_agent.padroes._mrosc_comum import eh_parceria, plano, tags_parceria

ID = "gestor_recebe_da_osc"

_TITULO_DESIG = re.compile(r"portaria|publica|designa|di[aá]rio oficial|\bD\.?O\.?\b|extrato|resolu|\bato\b|comiss|"
                           r"gestor", re.I)
_TITULO_PAG = re.compile(r"comprovante|pagamento|bolsa|folha|extrato\s+banc|extrato\s+(da\s+)?conta|planilha|"
                         r"rela[cç][aã]o\s+de\s+pag|presta[cç][aã]o\s+de\s+contas|recibo|holerite|contracheque|\bRPA\b|"
                         r"transfer|\bPIX\b|\bDOA\b|despesas", re.I)
_TITULO_ORGAO = re.compile(r"despacho|of[ií]cio|parecer|portaria|relat[oó]rio\s+de\s+fiscaliza|e-?mail|publica[cç]|"
                           r"termo\s+de\s+(fomento|colabora)|minuta|nota\s+t[eé]cnica", re.I)
_CONTEXTO_DESIG = re.compile(r"gestor|comiss[aã]o\s+de\s+monitoramento", re.I)

_TOK = r"(?:[A-ZÀ-Ý][a-zà-ÿ]+|[A-ZÀ-Ý]{2,})"
_PART = r"(?:d[aeo]s?|D[AEO]S?|e|E)"
_RE_NOME_ID = re.compile(
    r"(" + _TOK + r"(?:\s+(?:" + _PART + r"\s+)?" + _TOK + r"){2,7})\s*[,(–—\-?]?\s*"
    r"(?:Id\.?\s*Funcional|ID\s*Funcional|Identidade\s+Funcional|ID\.?\s*n?º?\s*\d|Matr[íi]cula|Mat\.)")
_PARTICULAS = {"da", "de", "do", "das", "dos", "e"}
_NAO_NOME = {"governo", "estado", "secretaria", "fundacao", "comissao", "portaria", "processo", "rio", "janeiro",
             "art", "termo", "fomento", "colaboracao", "projeto", "programa", "gestor", "gestora", "membro",
             "servidor", "servidora", "presidente", "coordenador", "coordenadora", "diretor", "diretora", "membros",
             "titular", "suplente", "monitoramento", "avaliacao", "parceria", "lei", "decreto", "resolve", "designar"}
_FUNCAO_ANTES = re.compile(r"(gestor|gestora|comissao|presidente|membro|analisad\w* por|sra|senhora|ilma|"
                           r"fiscal|assinad\w* (eletronicamente )?por)(\s+d[aoe]s?\s+\w+)?\W*$")
_MOEDA_PERTO = re.compile(r"r\$\s*\d")


def nomes_designados(texto: str) -> list[tuple[str, str]]:
    """[(nome normalizado, trecho)] de servidores designados gestor/comissão no texto."""
    t = plano(texto)
    if not _CONTEXTO_DESIG.search(t):
        return []
    out = []
    for m in _RE_NOME_ID.finditer(t):
        nome = C.norm(m.group(1))
        toks = [x for x in nome.split() if x not in _PARTICULAS]
        if len(toks) < 3 or any(x in _NAO_NOME for x in toks):
            continue
        janela = t[m.start():m.end() + 120]
        antes = t[max(0, m.start() - 400):m.start()]
        if not (_CONTEXTO_DESIG.search(janela) or _CONTEXTO_DESIG.search(antes)):
            continue
        out.append((nome, C.trecho(t, m.start(), m.end() + 60, 30)))
    return out


def _trie_regex(nomes: list[str]) -> re.Pattern | None:
    """Alternação em trie (rápida em texto de MB com milhares de nomes)."""
    trie: dict = {}
    for n in nomes:
        no = trie
        for ch in n:
            no = no.setdefault(ch, {})
        no[""] = True

    def rx(no: dict) -> str:
        fim = "" in no
        ramos = [re.escape(ch) + rx(sub) for ch, sub in sorted(no.items()) if ch != ""]
        if not ramos:
            return ""
        corpo = ramos[0] if len(ramos) == 1 else "(?:" + "|".join(ramos) + ")"
        return f"(?:{corpo})?" if fim else corpo

    return re.compile(r"\b(" + rx(trie) + r")\b") if trie else None


def pagamentos_do_nome(texto_norm: str, rx: re.Pattern) -> dict[str, list[str]]:
    """{nome: [trechos com valor em R$ perto]} — texto já normalizado."""
    out = defaultdict(list)
    for m in rx.finditer(texto_norm):
        antes = texto_norm[max(0, m.start() - 40):m.start()]
        if _FUNCAO_ANTES.search(antes):
            continue
        viz = texto_norm[max(0, m.start() - 200):m.end() + 200]
        if not _MOEDA_PERTO.search(viz):
            continue
        if len(out[m.group(1)]) < 3:
            out[m.group(1)].append(C.trecho(texto_norm, m.start(), m.end(), 110))
        else:
            out[m.group(1)].append("")
    return out


# ── passada 1: designações ──
def _desig(pasta, man, sel):
    if not eh_parceria(man):
        return [], {}
    out = []
    for d in sel:
        for nome, tr in nomes_designados(C.ler(pasta, man, d)):
            out.append({"nome": nome, "processo": C.processo(pasta.name), "doc": C.numero_doc(d), "trecho": tr})
    return out, {"parcerias_avaliadas": 1, "designacoes_lidas": len(out)}


_RX: re.Pattern | None = None   # passada 2 lê via fork (multiprocessing herda o global)


def _pag(pasta, man, sel):
    if not eh_parceria(man) or _RX is None:
        return [], {}
    out = []
    lidos = 0
    for d in sel:
        if _TITULO_ORGAO.search(str(d.get("titulo") or "")):
            continue
        lidos += 1
        t = C.norm(plano(C.ler(pasta, man, d)))
        for nome, trechos in pagamentos_do_nome(t, _RX).items():
            out.append({"nome": nome, "processo": C.processo(pasta.name), "doc": C.numero_doc(d),
                        "titulo": str(d.get("titulo") or "")[:100], "ocorrencias": len(trechos),
                        "trechos": [x for x in trechos if x]})
    return out, {"parcerias_com_prestacao_lida": 1 if lidos else 0, "docs_prestacao_lidos": lidos}


def cruzar(desig: list[dict], pags: list[dict]) -> list[dict]:
    """Designação × pagamento → achados por (processo do pagamento, nome)."""
    por_nome = defaultdict(list)
    for d in desig:
        por_nome[d["nome"]].append(d)
    agr = defaultdict(list)
    for p in pags:
        if p["nome"] in por_nome:
            agr[(p["processo"], p["nome"])].append(p)
    achados = []
    for (proc, nome), ps in agr.items():
        ds = por_nome[nome]
        mesmo = [d for d in ds if d["processo"] == proc]
        d0 = (mesmo or ds)[0]
        prova_pag = " · ".join(f"{p['doc']} ({p['titulo']}) — \"{p['trechos'][0] if p['trechos'] else ''}\"" +
                               (f" [{p['ocorrencias']} ocorrências com R$]" if p["ocorrencias"] > 1 else "")
                               for p in ps[:3])
        achados.append({
            "processo": proc, "grau": "forte" if mesmo else "medio",
            "agente_publico": nome.title(),
            "designado_em": f"{d0['processo']} {d0['doc']} — \"{d0['trecho']}\"",
            "prova": f"designação: {d0['processo']} {d0['doc']} — \"{d0['trecho']}\" × pagamento: {prova_pag}",
            "ocorrencias_pagamento": sum(p["ocorrencias"] for p in ps), "valor_pago_ob": None,
            "porque": ("Inocentes avaliadas: homônimo (só nome completo ≥ 3 tokens), nome como destinatário/analista "
                       "(função do Estado antes do nome descarta), documento do órgão (não lido). Não descartada: "
                       "servidor já desligado na data do pagamento — pedir ficha funcional."
                       + ("" if mesmo else " Designado em OUTRA parceria: relação com OSC distinta.")),
            "fonte": "SEI (portaria de designação + prestação de contas da OSC) · OB SIAFE _ob_paga (piso)"})
    return achados


def varrer(limite: int | None = None, so: list[str] | None = None) -> dict:
    global _RX
    so = so or tags_parceria(limite)
    desig, cob1, _ = C.varrer_acervo(_TITULO_DESIG, _desig, so=so)
    nomes = sorted({d["nome"] for d in desig})
    _RX = _trie_regex(nomes)
    pags, cob2, _ = C.varrer_acervo(_TITULO_PAG, _pag, so=so)
    achados = cruzar(desig, pags)
    if achados:
        con = C.con_ro()
        obs = C.obs_pagas(con, [a["processo"] for a in achados])
        con.close()
        for a in achados:
            a["valor_pago_ob"] = C.pago(obs.get(a["processo"], []))
            a["credor"] = "; ".join(sorted({o["nome_credor"] for o in obs.get(a["processo"], [])
                                             if o.get("nome_credor")}))[:200]
    cob = {"designacao": cob1, "prestacao": cob2, "nomes_designados_distintos": len(nomes),
           "universo_definicao": "parcerias (títulos do manifesto) com prestação de contas lida"}
    return C.resultado(ID, cob2.get("parcerias_com_prestacao_lida", 0), cob, achados,
                       "data/sei_arquivo/*/manifest.json + texto; ob_orcamentaria_siafe (_ob_paga, soma = PISO)")
