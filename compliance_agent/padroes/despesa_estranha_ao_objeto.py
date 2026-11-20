# -*- coding: utf-8 -*-
"""Despesa ESTRANHA ao objeto: festa, jantar, almoço ou confraternização dos próprios servidores/autoridades paga como
execução de contrato de outro objeto.

ORIGEM (perícia por agente, 18/11/2026): SETUR × Buzzline (contrato de promoção turística 010/2021).
  · SEI-050001/000054/2026, doc 6 (NF 004): "Jantar de encerramento de ano e prestação de contas para servidores da
    Secretaria de turismo do Rio de Janeiro. Local: Roxy Dinner Show" — R$ 137.415,45 (OB 2026OB00159).
  · SEI-050001/000001/2025: doc 283 "almoço para servidores [...] no dia do Servidor Público" (R$ 26.002,94); doc 258
    "JANTAR DE SECRETÁRIOS DE ESTADO" (R$ 194.203,18); doc 314 brindes (R$ 910.680,66).
Despesa de confraternização de servidores não é finalidade pública do contrato (CF art. 37 caput — moralidade e
impessoalidade; Lei 4.320/1964 art. 63 — liquidação contra o objeto contratado; Lei 14.133/2021 art. 115).

SINAL: em documento de EXECUÇÃO/PAGAMENTO (NF, fatura, OS, atestado, medição, planilha de serviços) a descrição traz
evento de comer/festejar (jantar, almoço, confraternização, festa, coquetel, ceia, happy hour) cujo BENEFICIÁRIO, na
mesma frase (≤ 150 caracteres), são servidores, funcionários, colaboradores ou autoridades do próprio órgão.
  · forte = evento festivo + beneficiário interno, sem contexto de capacitação/plantão;
  · medio = "dia do servidor" sem o evento festivo explícito, ou brindes/presentes para servidores;
  · fraco = evento + servidores em contexto de capacitação, seminário, reunião de trabalho, plantão ou operação
            (alimentação de quem trabalha pode ser legítima — quem abre decide).
FORA por código: "servidor" de informática (rede, dados, rack, storage, virtual, hospedagem); documento que não é de
execução/pagamento (convite, ofício, notícia). Reforma paga como outro objeto e festa municipal classificada como
"manutenção administrativa" (Scalle 260005/007167/2024, MRC 150002/000471/2025) dependem de cruzar o objeto do
contrato com a memória de cálculo — NÃO cobertos por este detector (ver cobertura).
Indício para requerer documentos, não acusação.
"""
from __future__ import annotations

import re

from compliance_agent.padroes import _pagamento_comum as C
from compliance_agent.padroes._comum import ORDEM_GRAU

ID = "despesa_estranha_ao_objeto"

GREP = r"jantar|almo[cç]o|confraterniza|coquetel|happy hour|ceia|dia do servidor|festa de (fim|encerramento)"
# nomes dos .txt que podem ter título de execução (o casamento fino é `TIT_EXEC` sobre o título do manifesto)
NOMES = ["nota", "_nf", "fatura", "ordem", "_os", "atest", "medi", "planilha", "relat", "boletim"]
TIT_EXEC = re.compile(r"nota fiscal|\bNFS?e?\b|fatura|ordem de servi[cç]o|\bOS\b|atestad|medi[cç][aã]o|"
                      r"planilha|relat[oó]rio (de execu|fotogr|do evento|final)|boletim", re.I)
# Refeição sozinha NÃO é festa: contrato de alimentação de presídio/hospital/socioeducativo fornece "jantar servidor"
# e "almoço - funcionários" a quem está de serviço — 1ª varredura (19/11/2026): 39 dos 41 "fortes" eram isso (Qualybem,
# Cassarotti, Nova Rodovia, Locasem…). O sinal exige o EVENTO: confraternização, coquetel, jantar/almoço DE algo.
_FESTA = re.compile(r"confraterniza\w*|coquetel|happy hour|ceia de natal|festa de (fim|encerramento)|"
                    r"(jantar|almo[cç]o)\s+(de|do|da|para)\s+(encerramento|confraterniza|gala|secret[aá]rios|natal|fim de "
                    r"ano|homenagem|comemora|celebra)", re.I)
# contexto de FORNECIMENTO DE ALIMENTAÇÃO (o comensal é o objeto do contrato) — fora
_ALIMENTACAO = re.compile(r"\bpresos?\b|internos?\b|pacientes?|adolescentes?|socioeducand|acompanhantes?|\bdieta|"
                          r"desjejum|kit[- ]lanche|refeit[oó]rio|merenda|colação", re.I)
_BENEF = re.compile(r"\bservidor(es|as)?\b|funcion[aá]ri[oa]s|colaborador(es|as)|secret[aá]ri[oa]s de estado|"
                    r"\bsecret[aá]rios\b|equipe da secretaria|quadro de pessoal", re.I)
_DIA_SERVIDOR = re.compile(r"dia do servidor", re.I)
_EVENTO = re.compile(r"almo[cç]o|jantar|evento|buffet|coff?ee?|coquetel|festa|show|comemora", re.I)
# "presente" sozinho é "o presente atestado"/"público presente" (1ª varredura: 5 de 6 médios) — só o presente DADO
_BRINDE = re.compile(r"brindes?|presentes?\s+(para|aos?|de natal|de fim de ano)|lembran[cç]as?|kits? de natal", re.I)
_TI = re.compile(r"\bservidor(es)?\s+(de\s+)?(rede|dados|arquivos|aplica|virtual|f[ií]sico|web|backup|rack|storage|"
                 r"blade|hospedagem|banco de dados|e-?mail|dns|proxy|v[ií]deo|m[ií]dia|streaming)|hospedagem de servidor", re.I)
_TRABALHO = re.compile(r"capacita[cç]|treinamento|curso|oficina|semin[aá]rio|workshop|congresso|reuni[aã]o de "
                       r"trabalho|plant[aã]o|opera[cç][aã]o|tropa|efetivo|frente de trabalho|mutir[aã]o|aula|"
                       r"forma[cç][aã]o|palestra|f[oó]rum|confer[eê]ncia", re.I)
_NOTICIA = re.compile(r"of[ií]cio|convite|not[ií]cia|clipping|publica[cç][aã]o|e-?mail", re.I)


def avaliar_texto(texto: str) -> dict | None:
    """Pior ocorrência do sinal num documento de execução, ou None."""
    t = re.sub(r"\s+", " ", texto or "")
    melhor = None
    for m in _FESTA.finditer(t):
        jan = t[max(0, m.start() - 150):m.end() + 150]
        b = _BENEF.search(jan)
        if not b or _TI.search(jan) or _ALIMENTACAO.search(jan):
            continue
        g = "fraco" if _TRABALHO.search(jan) else "forte"
        if melhor is None or (g == "forte" and melhor["grau"] != "forte"):
            melhor = {"grau": g, "trecho": C.trecho(t, m.start(), m.end(), 150)}
    if melhor:
        return melhor
    for m in _DIA_SERVIDOR.finditer(t):
        jan = t[max(0, m.start() - 200):m.end() + 200]
        if _ALIMENTACAO.search(jan):
            continue
        # evento/refeição pago no Dia do Servidor (MRC "1º Evento em comemoração ao Dia do Servidor"; PGERJ coffee break)
        g = "forte" if _EVENTO.search(jan) else "medio"
        return {"grau": g, "trecho": C.trecho(t, m.start(), m.end(), 150)}
    for m in _BRINDE.finditer(t):
        jan = t[max(0, m.start() - 120):m.end() + 120]
        if _BENEF.search(jan) and not _TI.search(jan):
            return {"grau": "medio", "trecho": C.trecho(t, m.start(), m.end(), 120)}
    return None


def varrer(limite: int | None = None, so: list[str] | None = None) -> dict:
    cands = C.grep_candidatos(GREP, so, limite, nomes=NOMES)
    cob = {"processos_com_termo": len(cands), "docs_com_termo": sum(len(v) for v in cands.values()),
           "nao_coberto": "reforma paga como outro objeto; festa classificada como manutenção (exige objeto × memória)"}
    brutos = []
    for tag, arqs in cands.items():
        pasta = C.ACERVO / tag
        man = C.manifesto(pasta)
        if not man:
            continue
        idx = C.docs_por_arquivo(man)
        hits = []
        for a in arqs:
            d = idx.get(a)
            tit = str((d or {}).get("titulo") or "")
            if not d or not TIT_EXEC.search(tit) or _NOTICIA.search(tit):
                continue
            r = avaliar_texto(C.ler(pasta, man, d, teto=80000))
            if r:
                hits.append({**r, "doc": C.numero_doc(d), "titulo": tit[:100]})
        if hits:
            brutos.append((tag, hits))
    cob["docs_de_execucao_com_sinal"] = sum(len(h) for _, h in brutos)
    con = C.con_ro()
    obs = C.obs_pagas(con, [C.processo(t) for t, _ in brutos])
    con.close()
    achados = []
    for tag, hits in brutos:
        proc = C.processo(tag)
        hits.sort(key=lambda h: ORDEM_GRAU[h["grau"]])
        h0 = hits[0]
        achados.append({
            "processo": proc, "grau": h0["grau"], "n_docs": len(hits),
            "prova": "; ".join(f"{h['doc']} ({h['titulo']}) — \"{h['trecho']}\"" for h in hits[:3]),
            "valor_pago_ob": C.pago(obs.get(proc, [])),
            "credor": C.credor_nome(obs.get(proc, [])),
            "porque": ("evento festivo/refeição para servidores ou autoridades do próprio órgão em documento de "
                       "execução; inocentes não excluídas: evento institucional previsto no objeto (ex.: contrato de "
                       "eventos que inclua cerimonial), alimentação de equipe em serviço"),
            "fonte": "data/sei_arquivo (NF/OS/atestado) × ob_orcamentaria_siafe/_ob_paga (piso do processo)"})
    return C.resultado(ID, len(C.pastas(so)) if not limite else limite, cob, achados, "data/sei_arquivo × SIAFE")
