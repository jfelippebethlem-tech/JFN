# -*- coding: utf-8 -*-
"""Atesto (e pagamento) ANTES do fim do período ou do evento faturado — liquidação de serviço que ainda não ocorreu.

ORIGEM (perícia por agente, 18/11/2026):
  · Buzzline × SETUR, SEI-050001/000054/2026: atestado (doc 182) de 04/11/2026 declara "executados" os serviços da
    NF 77 (doc 179, montagem de stand na FESTURIS, "Período 06 a 11 de novembro de 2026"); OB 2026OB01391/01392 de
    09/11/2026 — pago antes de a feira acabar. Idem SEI-050001/000001/2025 (NF 1378 "PERÍODO: DE 07 A 24 DE JULHO DE
    2025" atestada em 14/07/2025, 2025OB00781 de 17/07/2025).
  · SEEDUC transporte complementar, SEI-030001/041050/2025: "Novembro e Dezembro 2025" atestados em 11/12/2025.
Já existia o FZ1 do 360 (`compliance_agent/sei/fiscalizacao.py`), que só lê o período escrito NO PRÓPRIO atesto.
Este padrão o estende: segue as NFs que o atesto cita pelo id SEI ("NF 77(145642059)") e lê o período na NF, e
cruza com a OB paga do SIAFE.

SINAL, atesto a atesto: data da ÚLTIMA assinatura do atesto < último dia do período (do atesto ou das NFs citadas).
  · forte  = além disso há OB PAGA do processo emitida entre o atesto e o fim do período (pagou-se antes de acabar),
             ou o atesto é anterior ao INÍCIO do período (atestou-se evento que nem começou);
  · medio  = só o atesto é antecipado (1 a 45 dias);
  · fraco  = folga > 45 dias (FZ2: quase sempre erro material de data — ainda assim peça de liquidação errada).

EXPLICAÇÕES INOCENTES TRATADAS POR CÓDIGO: concessionária (o "mês" é o ciclo de leitura — 341 FP medidos no FZ1);
atesto cancelado; "período" que é de VIGÊNCIA/garantia/aditivo do contrato (não do serviço); período só com mês
sem ano não é lido. NÃO tratadas (ficam para quem abre): pré-produção/montagem que de fato termina antes do evento
(a NF fatura o evento inteiro, então o atesto continua cobrindo dias futuros); antecipação autorizada no contrato
(Lei 14.133 art. 145 §1º). Indício para requerer documentos, não acusação.

Norma: Lei 4.320/1964 arts. 62 e 63 (liquidação = direito adquirido, com base na prestação efetiva); Lei 14.133/2021
art. 140 e art. 145 (vedação de pagamento antecipado).
"""
from __future__ import annotations

import calendar
import re
from datetime import date

from compliance_agent.padroes import _pagamento_comum as C

ID = "atesto_antes_do_periodo"

TIT_ATESTO = re.compile(
    r"atestad[oa] de realiza|atesto|relat[oó]rio (t[eé]cnico )?(de|da comiss[aã]o de) fiscaliza|"
    r"termo de recebimento|recebimento (provis[oó]rio|definitivo)", re.I)
TIT_NF = re.compile(r"nota[\s_]+fiscal|\bnfs|nfse|danfse|\bNF\b|fatura", re.I)
TIT_ALVO = re.compile(TIT_ATESTO.pattern + "|" + TIT_NF.pattern, re.I)

_CONCESSIONARIA = re.compile(
    r"\bCEG\b|naturgy|g[aá]s natural|\blight\b|\benel\b|\bampla\b|cedae|[aá]guas do rio|igu[aá] saneamento|"
    r"rio\+saneamento|energia el[eé]trica|telefonia|embratel|correios|fornecimento de [aá]gua|esgot", re.I)
_A = r"\s*(?:a|à|á|ate|até|e|-|–)\s*"
_PER = r"per[ií]odo\b[^0-9\n]{0,25}?"
_P1 = re.compile(_PER + r"(\d{1,2}/\d{1,2}/\d{4})" + _A + r"(\d{1,2}/\d{1,2}/\d{4})", re.I)
_P2 = re.compile(_PER + r"(?:de\s+)?(\d{1,2})(?:\s+de\s+" + C.MES + r")?" + _A + r"(\d{1,2})\s+de\s+" + C.MES
                 + r"\s+(?:de\s+)?(\d{4})", re.I)
# Lista de dias antes do intervalo ("PERÍODO: 15, 16, 22, 23 E 28/02 À 09/03 DE 2025") — o início é o 1º dia.
_LISTA = r"((?:\d{1,2}\s*(?:,|e)\s*)*)"
_P3 = re.compile(_PER + _LISTA + r"(\d{1,2})/(\d{1,2})" + _A + r"(\d{1,2})/(\d{1,2})\s*(?:de\s+|/)\s*(\d{4})", re.I)
_P4 = re.compile(_PER + r"(\d{1,2})\s+de\s+" + C.MES + r"\s+(?:de\s+)?(\d{4})", re.I)
_P5 = re.compile(r"(?:servi[cç]os|fornecimento|presta[cç][aã]o|repasse)[^.]{0,60}?(?:m[eê]s(?:es)?\s+de|"
                 r"referentes?\s+ao\s+m[eê]s\s+de)\s+" + C.MES + r"(?:\s*(?:,|e|a)\s*" + C.MES + r")*"
                 r"\s*(?:de\s*|/\s*)?(\d{4})", re.I)
_NAO_SERVICO = re.compile(r"vig[eê]ncia|garantia|aditivo|prorroga|contratual|validade|inscri[cç]", re.I)
FOLGA_MIN_FORTE = 3     # 1–2 dias antes do fim do mês (3STRUCTURE, OB de 30/12) é calendário, não prova de antecipação
_RE_EMISSAO = re.compile(r"(?:data\s+(?:e\s+hora\s+)?(?:de\s+|da\s+)?emiss[ãa]o(?:\s+da\s+nfs-e)?)[^0-9]{0,30}"
                         r"(\d{2}/\d{2}/\d{4})", re.I)
# Concessionária pelo NOME do credor (o texto do atesto nem sempre diz "telefonia"): OI, Cooperativa de Eletrificação…
CREDOR_CONCESSIONARIA = re.compile(r"\bOI S\.?A|TELEMAR|\bCLARO\b|TELEF[OÔ]NICA|\bVIVO\b|\bTIM S|EMBRATEL|LIGHT S|"
                                   r"\bENEL\b|AMPLA|\bCEG\b|NATURGY|CEDAE|[ÁA]GUAS D|COOPERATIVA DE ELETR|ENERGISA|"
                                   r"IGU[AÁ]|CORREIOS|EMPRESA BRASILEIRA DE CORREIOS", re.I)
_RE_IDSEI = re.compile(r"\((\d{7,10})\)")


def periodos(texto: str) -> list[tuple[date | None, date, str]]:
    """[(início, fim, trecho)] dos períodos de SERVIÇO escritos no texto (vigência/garantia ficam fora)."""
    t = re.sub(r"\s+", " ", texto or "")
    out = []

    def ok(m) -> bool:
        return not _NAO_SERVICO.search(t[max(0, m.start() - 70):m.start() + 28])   # "Período contratual: …"

    for m in _P1.finditer(t):
        a, b = C.data_br(m[1]), C.data_br(m[2])
        if b and ok(m):
            out.append((a, b, m[0]))
    for m in _P2.finditer(t):
        mf, ano = C.mes_num(m[4]), int(m[5])
        mi = C.mes_num(m[2]) if m[2] else mf
        b, a = C.data_ymd(ano, mf, m[3]), C.data_ymd(ano if (mi or 0) <= (mf or 0) else ano - 1, mi, m[1])
        if b and ok(m):
            out.append((a, b, m[0]))
    for m in _P3.finditer(t):
        ano = int(m[6])
        b = C.data_ymd(ano, m[5], m[4])
        dia_ini = re.match(r"\d{1,2}", m[1])[0] if m[1] else m[2]
        a = C.data_ymd(ano if int(m[3]) <= int(m[5]) else ano - 1, m[3], dia_ini)
        if b and ok(m):
            out.append((a, b, m[0]))
    for m in _P4.finditer(t):
        b = C.data_ymd(m[3], C.mes_num(m[2]), m[1])
        if b and ok(m) and not any(x[2].startswith(m[0][:20]) for x in out):
            out.append((b, b, m[0]))
    for m in _P5.finditer(t):
        meses = [C.mes_num(x) for x in re.findall(C.MES, m[0], re.I)]
        ano, mf = int(m.groups()[-1]), max(x for x in meses if x)
        if 2000 < ano < 2100:
            b = date(ano, mf, calendar.monthrange(ano, mf)[1])
            out.append((date(ano, min(x for x in meses if x), 1), b, m[0]))
    return [p for p in out if 2000 < p[1].year < 2100]


# Cartão de benefício (vale-refeição/alimentação): o crédito do mês é carregado no INÍCIO do mês — "serviços do mês
# de maio" pagos em 12/05 é o modelo do produto, não antecipação (VR, Green Card, Trivale: 1ª varredura, 19/11/2026).
VALE_BENEFICIO = re.compile(r"vale[- ]?(refei|alimenta)|refei[cç][oõ]es|benef[ií]cios e servi|cart[aã]o[- ](alimenta|"
                            r"refei)|institui[cç][aã]o de pagamento|aux[ií]lio[- ](alimenta|refei)|green card|\bVR\b|"
                            r"trivale|ticket|sodexo|pluxee|alelo", re.I)


def avaliar_atesto(texto_atesto: str, nfs: dict[str, str]) -> dict | None:
    """Um atesto + {id SEI: texto} das NFs que ele cita → pior antecipação, ou None."""
    if _CONCESSIONARIA.search(texto_atesto[:4000]) or VALE_BENEFICIO.search(texto_atesto[:6000]):
        return None
    assinado = C.data_do_atesto(texto_atesto)
    if not assinado:
        return None
    cands = [(p, "o próprio atesto") for p in periodos(texto_atesto)]
    for idsei in dict.fromkeys(_RE_IDSEI.findall(texto_atesto)):
        t = nfs.get(idsei)
        if t and not _CONCESSIONARIA.search(t[:4000]):
            cands += [(p, f"NF ({idsei})") for p in periodos(t)]
    # NF emitida DEPOIS da data do atesto que a atesta: a data do atesto está errada (JRF × CEASA, SEI-020004/000013/2025
    # doc 30: período de fevereiro "assinado" em 10/02, NFS-e de 10/03) — vira fraco, não antecipação
    emissoes = [d for tx in [texto_atesto, *nfs.values()] for d in (C.data_br(x) for x in _RE_EMISSAO.findall(tx or ""))
                if d]
    nf_posterior = any(d > assinado for d in emissoes)
    pior = None
    for (ini, fim, tr), onde in cands:
        folga = (fim - assinado).days
        if folga > 0 and (pior is None or folga > pior["folga"]):
            pior = {"assinado": assinado, "inicio": ini, "fim": fim, "folga": folga, "trecho": tr, "onde": onde,
                    "antes_do_inicio": bool(ini and ini > assinado), "nf_posterior_ao_atesto": nf_posterior}
    return pior


def _pasta(pasta, man, sel):
    nfs, atestos = {}, []
    for d in sel:
        tit = str(d.get("titulo") or "")
        if TIT_ATESTO.search(tit) and not re.search(r"cancelad", tit, re.I):
            atestos.append(d)
        elif TIT_NF.search(tit):
            m = re.search(r"\(?(\d{7,10})\)?\s*$", tit)
            if m:
                nfs[m[1]] = d
    if not atestos:
        return [], {}
    cache: dict[str, str] = {}

    def txt(d):
        k = str(d.get("i"))
        if k not in cache:
            cache[k] = C.ler(pasta, man, d, teto=60000)
        return cache[k]

    out = []
    for d in atestos:
        ta = txt(d)
        citadas = {i: txt(nfs[i]) for i in dict.fromkeys(_RE_IDSEI.findall(ta)) if i in nfs}
        r = avaliar_atesto(ta, citadas)
        if r:
            out.append({**r, "doc": C.numero_doc(d), "titulo": str(d.get("titulo") or "")[:120]})
    return ([{"tag": pasta.name, "atestos": out}] if out else []), {"atestos_lidos": len(atestos)}


def classificar(r: dict, obs: list[dict]) -> tuple[str, list[dict]]:
    pagas_antes = [o for o in obs if (d := C.data_br(o.get("data_emissao"))) and r["assinado"] <= d < r["fim"]]
    if r["folga"] > 45 or r.get("nf_posterior_ao_atesto"):
        return "fraco", pagas_antes
    if (pagas_antes or r["antes_do_inicio"]) and r["folga"] >= FOLGA_MIN_FORTE:
        return "forte", pagas_antes
    return "medio", pagas_antes


def varrer(limite: int | None = None, so: list[str] | None = None) -> dict:
    brutos, cob, n = C.varrer_acervo(TIT_ALVO, _pasta, so=so, limite=limite)
    con = C.con_ro()
    obs = C.obs_pagas(con, [C.processo(b["tag"]) for b in brutos])
    con.close()
    achados = []
    for b in brutos:
        proc = C.processo(b["tag"])
        ob_p = obs.get(proc, [])
        if any(CREDOR_CONCESSIONARIA.search(o.get("nome_credor") or "") for o in ob_p):
            cob["fora_concessionaria_pelo_credor"] = cob.get("fora_concessionaria_pelo_credor", 0) + len(b["atestos"])
            continue
        if any(VALE_BENEFICIO.search(o.get("nome_credor") or "") for o in ob_p):
            cob["fora_cartao_beneficio"] = cob.get("fora_cartao_beneficio", 0) + len(b["atestos"])
            continue
        for r in b["atestos"]:
            g, pagas = classificar(r, ob_p)
            obs_txt = ", ".join(f"{o['numero_ob']} de {o['data_emissao']} R$ {C.fmt(float(o['valor'] or 0))}"
                                for o in pagas[:6])
            achados.append({
                "processo": proc, "grau": g,
                "prova": (f"{r['doc']} assinado em {r['assinado']:%d/%m/%Y} — período lido em {r['onde']}: "
                          f"\"{C.mascarar_cpf(r['trecho'])}\" (fim {r['fim']:%d/%m/%Y}, {r['folga']} dia(s) depois)"
                          + (f"; OB paga antes do fim: {obs_txt}" if pagas else "")),
                "dias_antes_do_fim": r["folga"], "antes_do_inicio": r["antes_do_inicio"],
                "obs_pagas_antes_do_fim": [o["numero_ob"] for o in pagas],
                "valor_obs_antes_do_fim": round(sum(float(o["valor"] or 0) for o in pagas), 2) if pagas else None,
                "valor_pago_ob": C.pago(ob_p),
                "credor": C.credor_nome(ob_p),
                "porque": ("atesto anterior ao fim do período de serviço" + (" e anterior ao início" if
                           r["antes_do_inicio"] else "") + "; inocentes não excluídas: montagem/pré-produção que "
                           "termina antes do evento, data digitada errada, antecipação contratual (art. 145 §1º)"),
                "fonte": "data/sei_arquivo (atesto + NFs citadas pelo id SEI) × ob_orcamentaria_siafe/_ob_paga (piso)"})
    return C.resultado(ID, n, cob, achados, "data/sei_arquivo × SIAFE")
