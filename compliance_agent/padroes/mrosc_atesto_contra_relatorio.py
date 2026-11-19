# -*- coding: utf-8 -*-
"""A comissão ATESTA execução/metas cumpridas e o próprio relatório (ou o da OSC, ao lado) diz que não houve.

ORIGEM (perícia por agente, 18/11/2026):
  · Instituto NATA × SEIJES, SEI-280001/000176/2025 (Termo de Colaboração 001/2024 — "60+ Reabilita"): doc 23,
    Relatório de Fiscalização de 10/04/2025 — "os polos ainda não foram efetivamente implantados" e, na conclusão,
    "ATESTAMOS a execução INTEGRAL e SATISFATÓRIA da etapa"; o mesmo texto se repete nos relatórios seguintes.
  · Núcleo Social Bem Viver × SEIJES, SEI-280001/000624/2025: doc 102 (fiscalização) — "A OSC parceira desenvolveu as
    atividades realizadas atendendo o cumprimento das metas" × doc 104 (Relatório EXECUÇÃO OSC, logo adiante) — toda
    etapa "Iniciada – Em andamento", nenhuma concluída, no 11º mês.

SINAL
  · forte: no MESMO documento, frase de atesto pleno (execução integral/satisfatória, metas cumpridas/atingidas) e
    frase que nega a execução (não foram implantados/iniciados/executados; não atingindo a meta);
  · medio: atesto pleno num relatório de fiscalização/monitoramento e, a até 4 documentos de distância, relatório de
    execução da OSC com quadro de etapas em que NENHUMA está concluída (só "não iniciada"/"em andamento").

EXPLICAÇÕES INOCENTES AVALIADAS
  · no MROSC a 1ª parcela é antecipada pelo cronograma: o repasse não exige execução — o vício é o ATESTO, que afirma o
    que o texto nega; por isso o achado é sobre o atesto e o valor é o pago no processo (piso), não "dano";
  · etapa de implantação pode ser a meta do período (plano de trabalho): a forma cruzada (medio) não descarta isso;
  · "não foram implantados" referindo-se a etapa FUTURA ("ainda não foram implantados os polos da 2ª fase, previstos
    para…") — a negação precisa estar a ≤ 60 caracteres do sujeito e o documento ter atesto PLENO, não parcial;
  · relatório que atesta "parcialmente" ou "com ressalvas" não é atesto pleno → fora;
  · "será concluída" (futuro) não conta como etapa concluída nem como negação.

NORMA: Lei 13.019/2014 art. 58 e 59 (monitoramento e relatório técnico com análise das metas), art. 61 (gestor:
acompanhar e fiscalizar), art. 67 (parecer de prestação de contas). Indício, não acusação.
"""
from __future__ import annotations

import re

from compliance_agent.padroes import _pagamento_comum as C
from compliance_agent.padroes._mrosc_comum import eh_parceria, plano, tags_parceria

ID = "mrosc_atesto_contra_relatorio"

_TITULO = re.compile(r"relat[oó]rio|parecer|monitoramento|fiscaliza|atest|execu[cç]|presta[cç][aã]o de contas", re.I)
_TITULO_FISC = re.compile(r"fiscaliza|monitoramento|comiss|gestor|parecer|atest", re.I)
_TITULO_OSC = re.compile(r"execu[cç][aã]o\s+(da\s+)?osc|relat[oó]rio\s+(de\s+)?(atividades|execu[cç][aã]o\s+do\s+objeto)|"
                         r"relat[oó]rio\s+(da\s+)?(osc|entidade|institui)", re.I)

# Sobre texto normalizado (minúsculas, sem acento, espaço único).
_ATESTO = re.compile(
    r"atestamos a execucao integral|execucao integral e satisfatoria|"
    r"atendendo (o|ao) cumprimento das metas|(as )?metas (pactuadas |previstas |estabelecidas )?(foram )?"
    r"(integralmente )?(cumpridas|atingidas|alcancadas)(?! parcialmente)|cumpriu (integralmente )?(as|todas as) metas")
_PARCIAL = re.compile(r"parcialmente|com ressalva|em parte")
_NEGA = re.compile(
    r"(polos|unidades|nucleos|atividades|servicos|turmas|oficinas|obras|equipamentos)[^.]{0,60}?"
    r"(ainda )?nao (foram|foi) (efetivamente )?(implantad|iniciad|executad|realizad|instalad|inaugurad)\w*|"
    r"nao houve (execucao|atendimento|inicio das atividades)|nao atingindo (o|a|os|as) (objetivo|meta)")
_STATUS = re.compile(r"(nao iniciad[ao]|em andamento|(?<!sera )(?<!serao )conclui?d[ao]s?(?! concomitante)|finalizad[ao])")


def avaliar_documento(texto: str) -> dict | None:
    """Atesto pleno + negação da execução no mesmo texto → {atesto, nega}."""
    t = C.norm(plano(texto))
    a = _ATESTO.search(t)
    if not a or _PARCIAL.search(t[max(0, a.start() - 80):a.end() + 80]):
        return None
    n = _NEGA.search(t)
    if not n:
        return None
    return {"atesto": C.trecho(t, a.start(), a.end(), 80), "nega": C.trecho(t, n.start(), n.end(), 80)}


def atesto_pleno(texto: str) -> str | None:
    t = C.norm(plano(texto))
    a = _ATESTO.search(t)
    if not a or _PARCIAL.search(t[max(0, a.start() - 80):a.end() + 80]):
        return None
    return C.trecho(t, a.start(), a.end(), 80)


def quadro_sem_conclusao(texto: str) -> str | None:
    """Relatório da OSC cujo quadro de etapas não tem NENHUMA concluída (≥ 3 status lidos)."""
    t = C.norm(plano(texto))
    st = [m.group(1) for m in _STATUS.finditer(t)]
    if len(st) < 3 or any(s.startswith(("conclu", "finaliz")) for s in st):
        return None
    m = _STATUS.search(t)
    return C.trecho(t, m.start(), m.end(), 120)


def _processo(pasta, man, sel):
    if not eh_parceria(man):
        return [], {}
    cob = {"parcerias_avaliadas": 1}
    textos = {d["i"]: (d, C.ler(pasta, man, d)) for d in sel if d.get("i") is not None}
    fortes, medios = [], []
    for i, (d, t) in sorted(textos.items()):
        r = avaliar_documento(t)
        if r:
            fortes.append(f"{C.numero_doc(d)} — \"{r['atesto']}\" × \"{r['nega']}\"")
            continue
        if not _TITULO_FISC.search(str(d.get("titulo") or "")):
            continue
        at = atesto_pleno(t)
        if not at:
            continue
        for j in range(i - 4, i + 5):
            if j == i or j not in textos or not _TITULO_OSC.search(str(textos[j][0].get("titulo") or "")):
                continue
            q = quadro_sem_conclusao(textos[j][1])
            if q:
                medios.append(f"{C.numero_doc(d)} — \"{at}\" × {C.numero_doc(textos[j][0])} (relatório da OSC) — "
                              f"\"{q}\" (nenhuma etapa concluída)")
                break
    if not (fortes or medios):
        return [], cob
    provas = fortes or medios
    return [{"processo": C.processo(pasta.name), "grau": "forte" if fortes else "medio",
             "prova": " · ".join(provas[:3]), "documentos_com_o_vicio": len(provas),
             "documentos_cruzados_medio": len(medios), "valor_pago_ob": None,
             "porque": ("Inocente avaliada: no MROSC a 1ª parcela é antecipada e a etapa do período pode ser só a "
                        "implantação; o vício é o atesto pleno que o texto nega — exige o plano de trabalho (metas do "
                        "período) e a visita técnica."),
             "fonte": "SEI (manifesto + texto) · OB SIAFE _ob_paga (piso)"}], cob


def varrer(limite: int | None = None, so: list[str] | None = None) -> dict:
    so = so or tags_parceria(limite)
    achados, cob, n = C.varrer_acervo(_TITULO, _processo, so=so)
    if achados:
        con = C.con_ro()
        obs = C.obs_pagas(con, [a["processo"] for a in achados])
        con.close()
        for a in achados:
            a["valor_pago_ob"] = C.pago(obs.get(a["processo"], []))
            a["credor"] = "; ".join(sorted({o["nome_credor"] for o in obs.get(a["processo"], [])
                                             if o.get("nome_credor")}))[:200]
    cob["universo_definicao"] = "processos de parceria (títulos do manifesto, _mrosc_comum.eh_parceria)"
    return C.resultado(ID, cob.get("parcerias_avaliadas", 0), cob, achados,
                       "data/sei_arquivo/*/manifest.json + texto; ob_orcamentaria_siafe (_ob_paga, soma por processo = PISO)")
