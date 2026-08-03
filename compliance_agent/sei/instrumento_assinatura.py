# -*- coding: utf-8 -*-
"""Três achados que moram no TEXTO dos autos, não nos títulos.

Nasceram da leitura integral do SEI-270131/000548/2023 (2026-08-03) confrontada com o veredito da
casa: o sistema acertou o essencial (parecer condicionado sem resposta) e não viu nenhum destes.

  **I1 · ordinal divergente.** A minuta submetida à assessoria jurídica era do "1º TERMO ADITIVO";
  os instrumentos assinados dizem "2º". O art. 38, parágrafo único, da Lei 8.666/93 (art. 53 da
  Lei 14.133/2021) exige exame prévio *da minuta que se celebra* — aprovar uma e assinar outra
  esvazia o controle prévio. No mesmo processo havia DOIS instrumentos com o mesmo ordinal e o
  mesmo objeto, assinados com 8 dias de diferença.

  **I2 · autorização antes do parecer.** O ato do ordenador é de 16/05/2024; o parecer, de
  22/05/2024. A autoridade autorizou antes da manifestação jurídica que condicionou o
  prosseguimento. A casa já detecta "contrato antes do parecer" (A1 da triagem); a AUTORIZAÇÃO,
  que é o ato que compromete o dinheiro, não estava coberta.

  **I3 · ato decisório sem a assinatura de quem decide.** O "ATO DO ORDENADOR DE DESPESAS" trazia
  "* MINUTA DE DOCUMENTO" no topo e apenas a assinatura eletrônica do oficial que o redigiu — a
  ordenadora que o próprio texto nomeia como quem DECIDE não assinou. Autorização de despesa sem
  a assinatura do ordenador é vício do ato (art. 82 da Lei estadual 287/79; art. 38, caput, da
  Lei 8.666/93).

TODOS SÃO INDÍCIO. Documento pode ter sido assinado fora do SEI e a captura pode estar
incompleta: onde falta o dado, o retorno é `indisponivel=True` e NÃO achado — INDISPONÍVEL ≠
irregular, a regra mais dura desta casa.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from datetime import date

# Rodapé de assinatura eletrônica do SEI-RJ, literal e estável desde o Decreto 48.209/2022.
_RE_ASSINATURA = re.compile(
    r"assinado\s+eletronicamente\s+por\s+([^,]{3,80}?)\s*,([^,]{0,60}),\s*em\s+"
    r"(\d{2}/\d{2}/\d{4})(?:,\s*[àa]s\s*(\d{2}:\d{2}))?", re.I)

_RE_ORDINAL_ADITIVO = re.compile(r"(\d{1,2})\s*[ºo°]\s*TERMO\s+ADITIVO", re.I)
# O SEI-RJ grafa o ordinal por EXTENSO com a mesma frequência ("SEGUNDO TERMO ADITIVO AO CONTRATO
# INEA 36/2023"): sem isto o 2º aditivo do 070002/006145/2024 caía no ordinal de outra passagem do
# texto e o processo era acusado de ter dois instrumentos com o mesmo ordinal (2026-08-03).
_EXTENSO = ("primeiro", "segundo", "terceiro", "quarto", "quinto", "sexto", "setimo", "sétimo",
            "oitavo", "nono", "decimo", "décimo")
_RE_ORDINAL_EXTENSO = re.compile(
    r"\b(" + "|".join(_EXTENSO) + r")\s+TERMO\s+ADITIVO", re.I)
_VALOR_EXTENSO = {"primeiro": 1, "segundo": 2, "terceiro": 3, "quarto": 4, "quinto": 5,
                  "sexto": 6, "setimo": 7, "oitavo": 8, "nono": 9, "decimo": 10}
_RE_E_MINUTA = re.compile(r"\bminuta\b", re.I)
# PUBLICAÇÃO no D.O. é EXTRATO do instrumento, não o instrumento; APOSTILAMENTO é registro
# unilateral, não termo aditivo. Ambos entravam como "instrumento assinado" e produziam ordinal
# duplicado — medido em 420001/004224/2024, /004223/2024, /003578/2025 e /004635/2025 (2026-08-03).
_RE_NAO_E_INSTRUMENTO = re.compile(r"publica[çc][ãa]o|extrato|apostilamento", re.I)
# O documento É o instrumento, ou só CITA o aditivo? A justificativa ("Trata o presente processo
# de formalização do 1º Termo Aditivo…") e o parecer citam o ordinal e eram contados como
# instrumento assinado — falso positivo medido no acervo real em 2026-08-03. Instrumento traz a
# fórmula de celebração; peça que fala sobre ele, não.
_RE_INSTRUMENTO = re.compile(
    r"que\s+entre\s+si\s+celebram|resolvem\s+celebrar|RESOLVEM\s+celebrar|"
    r"CL[ÁA]USULA\s+PRIMEIRA", re.I)
_TIPOS_INSTRUMENTO = {"aditivo", "contrato", "termo_contrato", "ata_rp"}
_RE_MARCA_MINUTA = re.compile(r"\*?\s*MINUTA\s+DE\s+DOCUMENTO", re.I)

# Ato que AUTORIZA a despesa — pelo tipo canônico ou pelo cabeçalho que ele mesmo declara.
_TIPOS_AUTORIZACAO = {"autorizacao_despesa", "autorizacao", "ato_ordenador"}
_RE_CABECALHO_ATO = re.compile(
    r"ATO\s+DO\s+ORDENADOR\s+DE\s+DESPESAS?|DECLARA[ÇC][ÃA]O\s+DO\s+ORDENADOR", re.I)
# quem o próprio ato nomeia como a autoridade que decide
_RE_AUTORIDADE = re.compile(
    r"Est[ea]\s+Ordenador[a]?\s+de\s+Despesas?\s*,\s*([A-ZÀ-Ú][A-ZÀ-Ú\s\.]{5,60}?)\s*,", re.I)
_TIPOS_PARECER = {"parecer", "parecer_juridico", "manifestacao_juridica", "cota_juridica"}

# ─── o que é, de fato, o CONTROLE PRÉVIO do art. 53 · doutrina única da casa ───
# O tipo `parecer_juridico` do manifesto não basta: 66% dos pareceres do acervo foram tipados pelo
# CONTEÚDO, e o classificador aceita qualquer documento que MENCIONE "parecer". Lendo os 15
# disparos do I2 em 2026-08-03, o "parecer" era Checklist (2×), Declaração de Conformidade com a
# minuta-padrão da PGE (3×, assinada por quem redigiu a minuta — não é controle externo à unidade),
# Ato de Designação de Servidor, Correspondência Interna sobre troca de marca, e "Parecer de
# Análise para Emissão DL" (revisão de rotina do coordenador de qualidade — o mesmo falso positivo
# que já derrubou 71 disparos do G3). Aqui a peça precisa SE ANUNCIAR como manifestação jurídica.
# `sintese_global` importa estas duas: a doutrina mora num lugar só.
_RE_NAO_E_PARECER = re.compile(
    r"checklist|check-?list|lista\s+de\s+verifica|declara[çc][ãa]o\s+de\s+conformidade|"
    r"anexo\s+[úu]nico|resolu[çc][ãa]o\s+conjunta", re.I)
_RE_CONTROLE_JURIDICO = re.compile(
    r"jur[íi]dic|\bPGE\b|\bPGM\b|procuradoria|assessoria\s+jur|assjur|\bCGE\b|"
    r"controladoria|auditoria|controle\s+interno|opino|opina-se|parecer\s+n[ºo°]", re.I)
_CABECALHO_CHARS = 1500
# O arquivo compacto grava, na 1ª linha do .txt, "[título] (fase: … · tipo: parecer_juridico)".
# Isso põe a palavra `juridico` DENTRO do texto e faz o documento provar a si mesmo: o "Parecer de
# Análise para Emissão DL" (Diretoria Administrativa Financeira, "Procedida a Revisão do
# processo") passava no teste de manifestação jurídica pela própria etiqueta que se queria
# conferir. Medido em 080002/006705/2024 (2026-08-03).
_RE_CABECALHO_DO_ARQUIVO = re.compile(r"\A\[[^\]]{0,200}\]\s*(\([^)]{0,120}\))?\s*", re.M)


def _sem_etiqueta(texto: str) -> str:
    """Texto do documento sem a etiqueta que o ARQUIVO prepõe — só o que o SEI serviu."""
    return _RE_CABECALHO_DO_ARQUIVO.sub("", texto or "", count=2)


def e_controle_juridico(ref: str, texto: str) -> bool:
    """A peça é manifestação de controle prévio (art. 53), ou só fala de uma?

    Decide pelo que o documento declara de si — título e cabeçalho —, nunca pelo tipo herdado do
    manifesto. Formulário de conformidade e declaração da própria unidade não exercem controle.
    """
    alvo = f"{ref or ''}\n{_sem_etiqueta(texto)[:_CABECALHO_CHARS]}"
    if _RE_NAO_E_PARECER.search(alvo):
        return False
    return bool(_RE_CONTROLE_JURIDICO.search(alvo))


# O ato de autorização é aquele em que a autoridade DIZ que autoriza. O título mente nos dois
# sentidos: "Despacho de Solicitação de Reserva Orçamentária" do INEA traz "AUTORIZO a despesa"
# (é o ato), e "Despacho de Solicitação de Análise da NAD" traz "Encaminho o presente processo
# para confecção de NAD" (é pedido de providência, não decisão). Medido em 2026-08-03.
_RE_VERBO_AUTORIZA = re.compile(
    r"\bAUTORIZO\b|\bAPROVO\b|\bRATIFICO\b|\bHOMOLOGO\b|\bADJUDICO\b|"
    r"\bAUTORIZA-SE\b|\bfica\s+autorizad[ao]\b|DECIDE\s*,?\s*AUTORIZAR|"
    r"ORDENADOR[A]?\s+DE\s+DESPESAS?\.?\s*\n?\s*AUTORIZAR", re.I)


# RÓTULO de campo do formulário não é decisão. A Nota de Autorização de Despesa traz impresso
# "39 - APROVO E AUTORIZO ORDENADOR / AUTORIDADE DELEGADA" como cabeçalho do campo — presente em
# toda NAD, assinada ou não. Ler isso como o ato fazia a NAD do setor de orçamento virar a
# autorização do ordenador (080002/006705/2024 e mais quatro, 2026-08-03).
_RE_ROTULO_FORMULARIO = re.compile(
    r"\d{1,2}\s*[-–]\s*APROVO\s+E\s+AUTORIZO[^\n]{0,80}", re.I)


def e_ato_de_autorizacao(texto: str) -> bool:
    """A peça DECIDE autorizar a despesa (verbo em 1ª pessoa), ou apenas pede/informa?"""
    return bool(_RE_VERBO_AUTORIZA.search(
        _RE_ROTULO_FORMULARIO.sub(" ", _sem_etiqueta(texto))))


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").casefold()
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip()


# IDENTIFICADOR ao lado do nome. É o que resolve a dúvida "é a mesma pessoa?" sem chutar: o SEI
# grafa "FULANO, Id Funcional nº 613973-6, CPF 022.318.157-96" e a casa já tem a doutrina em
# `agentes_publicos.chave()` ("ID funcional manda; sem ele, nome normalizado"). Semelhança de nome
# fica como ÚLTIMO recurso, e o veredito diz em que base concluiu.
_RE_CPF = re.compile(r"\b(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})\b")
_RE_ID_FUNC = re.compile(
    r"\b(?:id|identifica[cç][aã]o)\.?\s*(?:[\s\-–]*funcional)?\s*[:\-–]?\s*n?[ºo°.]*\s*"
    r"(\d{6,8}-\d)\b", re.I)
_JANELA_ID = 160     # o identificador vem logo depois do nome, na mesma linha ou na seguinte


def _identificador(nome: str, texto: str) -> tuple[str | None, str | None]:
    """(cpf, id_funcional) que aparecem logo APÓS a primeira menção ao nome. Nunca inventa."""
    alvo = _norm(nome)
    if not alvo:
        return None, None
    base = _norm(texto)
    pos = base.find(alvo)
    if pos < 0:                       # nome do rodapé grafado diferente do corpo: tenta o 1º nome
        primeiro = alvo.split()[0] if alvo.split() else ""
        pos = base.find(primeiro) if len(primeiro) >= 4 else -1
        if pos < 0:
            return None, None
    # a janela é sobre o texto ORIGINAL, para preservar pontuação do CPF/ID
    fatia = texto[pos:pos + len(alvo) + _JANELA_ID]
    cpf = _RE_CPF.search(fatia)
    idf = _RE_ID_FUNC.search(fatia)
    return ("".join(cpf.groups()) if cpf else None, idf.group(1) if idf else None)


def _mesma_pessoa(a: str, b: str) -> bool:
    """O nome do corpo e o da assinatura são da mesma pessoa, tolerando erro de digitação?

    Medido no acervo (270006/020276/2024): o ato grafa "ALINE DE OLIVEIRA NASCXIMENTO" e a
    assinatura é de "Aline de Oliveira Nascimento" — comparação literal transformava um typo em
    "a autoridade não assinou", que é acusação sobre pessoa nomeada. A tolerância é estreita de
    propósito: o PRIMEIRO nome tem de bater e o conjunto precisa de 88% de semelhança, para que
    homônimo parcial e pessoa diferente sigam divergindo.
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    ta, tb = na.split(), nb.split()
    if not ta or not tb or ta[0] != tb[0]:
        return False
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.88


def _data(txt: str) -> date | None:
    try:
        d, m, a = (int(x) for x in txt.split("/"))
        return date(a, m, d)
    except (ValueError, AttributeError):
        return None


def assinaturas(texto: str) -> list[dict]:
    """Assinaturas eletrônicas do rodapé do SEI: [{nome, cargo, data, hora}] na ordem do texto."""
    return [{"nome": m.group(1).strip(), "cargo": (m.group(2) or "").strip(),
             "data": m.group(3), "hora": (m.group(4) or "")}
            for m in _RE_ASSINATURA.finditer(texto or "")]


def _primeira_data(doc: dict) -> str | None:
    ass = assinaturas(doc.get("texto") or "")
    return ass[0]["data"] if ass else None


_JANELA_ANCORA = 600   # o ordinal abre a fórmula: "3º TERMO ADITIVO … QUE ENTRE SI CELEBRAM"


def _ordinal(doc: dict) -> int | None:
    """O ordinal DO PRÓPRIO instrumento — o que abre a fórmula de celebração.

    Pegar a primeira ocorrência no texto inteiro lia o ordinal errado: um aditivo que menciona os
    anteriores ("… alterado pelo 1º TERMO ADITIVO") saía com o ordinal do que ele cita. Medido no
    acervo em 2026-08-03: dos 10 disparos do I1, 7 vinham daí. Aqui o ordinal é o ÚLTIMO que
    aparece na janela imediatamente anterior à fórmula ("QUE ENTRE SI CELEBRAM"), que é onde o
    instrumento se nomeia; sem fórmula, cai na primeira ocorrência (comportamento antigo).
    """
    texto = doc.get("texto") or ""
    anc = _RE_INSTRUMENTO.search(texto)
    if anc:
        janela = texto[max(0, anc.start() - _JANELA_ANCORA):anc.start()]
        achados = [(m.end(), int(m.group(1))) for m in _RE_ORDINAL_ADITIVO.finditer(janela)]
        achados += [(m.end(), _VALOR_EXTENSO[_norm(m.group(1))])
                    for m in _RE_ORDINAL_EXTENSO.finditer(janela)]
        # Com fórmula de celebração e SEM ordinal antes dela, o documento é o contrato original —
        # não se procura ordinal no resto do corpo. O Contrato 36/2023 do INEA cita "PRIMEIRO
        # TERMO ADITIVO" numa cláusula e saía como se fosse o 1º aditivo, colidindo com o aditivo
        # verdadeiro (070002/006145/2024, 2026-08-03).
        return max(achados)[1] if achados else None
    m = _RE_ORDINAL_ADITIVO.search(texto)
    if m:
        return int(m.group(1))
    m = _RE_ORDINAL_EXTENSO.search(texto)
    return _VALOR_EXTENSO[_norm(m.group(1))] if m else None


def _e_minuta(doc: dict) -> bool:
    """Minuta é a peça submetida ao exame; o instrumento é o que se celebra."""
    alvo = f"{doc.get('ref') or ''} {(doc.get('texto') or '')[:400]}"
    return bool(_RE_E_MINUTA.search(alvo))


# ───────────────────────────── I1 · ordinal divergente ─────────────────────────────

def _minuta_foi_atropelada(n: int, minutas: list[tuple], assinados: list[tuple]) -> bool:
    """A minuta do ordinal `n` foi ATROPELADA — examinou-se uma peça e celebrou-se outra?

    Nem toda minuta sem instrumento correspondente é vício. Lendo os disparos no acervo
    (2026-08-03) apareceram três situações que o achado tratava como uma só:

      • **atropelada** — a minuta é do 1º e, dezoito dias depois, assina-se o 2º
        (270131/000548/2023). É o achado: aprovou-se uma peça e celebrou-se outra.
      • **superada** — minuta do 2º em 06/06, minuta do 3º em 11/06, assina-se o 3º em 20/06
        (270131/000564/2023). A correção veio ANTES da assinatura: é o controle funcionando.
      • **pendente** — a minuta é a peça mais recente dos autos e nada foi assinado depois
        (070002/012954/2022). Processo em curso não é processo viciado.

    Sem data legível dos dois lados, a ordem da árvore do SEI (cronológica) decide.
    """
    pos = {id(d): i for i, (_, d) in enumerate(minutas + assinados)}

    def quando(d: dict) -> tuple:
        dt = _primeira_data(d)
        return (0, _data(dt).toordinal()) if dt and _data(dt) else (1, pos[id(d)])

    alvo = min((quando(d) for m, d in minutas if m == n), default=None)
    if alvo is None:
        return False
    posteriores = [(n2, quando(d)) for n2, d in assinados if quando(d) > alvo]
    if not posteriores:
        return False                       # pendente: nada foi celebrado depois da minuta
    for n2, q2 in posteriores:             # superada: a minuta certa foi examinada antes de assinar
        if any(m == n2 and alvo < quando(d) <= q2 for m, d in minutas):
            return False
    return True


def ordinal_divergente(docs: list[dict]) -> dict:
    """A minuta aprovada corresponde a algum instrumento assinado? Há ordinal repetido?"""
    minutas, assinados, sem_rodape = [], [], []
    for d in docs or []:
        n = _ordinal(d)
        if n is None:
            continue
        if _norm(d.get("tipo") or "") not in _TIPOS_INSTRUMENTO:
            continue                      # parecer/justificativa citam o ordinal, não o celebram
        if not _RE_INSTRUMENTO.search(d.get("texto") or ""):
            continue                      # sem fórmula de celebração não é o instrumento
        if _RE_NAO_E_INSTRUMENTO.search(str(d.get("ref") or "")):
            continue                      # extrato publicado / apostilamento não é o termo
        if _e_minuta(d):
            minutas.append((n, d))
        elif assinaturas(d.get("texto") or ""):
            assinados.append((n, d))
        else:
            # sem rodapé de assinatura eletrônica não se AFIRMA que o instrumento foi assinado:
            # pode ter sido assinado fora do SEI, e ausência de rodapé não prova ausência de ato.
            sem_rodape.append((n, d))
    ordinais_min = sorted({n for n, _ in minutas})
    ordinais_ass = sorted({n for n, _ in assinados})
    # ordinal que aparece em MAIS DE UM instrumento assinado, DESCONTADA a mesma peça anexada
    # duas vezes: em 270003/000382/2025 o 1º aditivo está na pasta como "Anexo SEI_…" e como
    # "Anexo …_eDO" (com a publicação), com as MESMAS três assinaturas nas mesmas datas. Cópia do
    # mesmo instrumento não é segundo instrumento.
    vistos: dict[int, list[frozenset]] = {}
    for n, d in assinados:
        firmas = frozenset((_norm(a["nome"]), a["data"]) for a in assinaturas(d.get("texto") or ""))
        vistos.setdefault(n, []).append(firmas)
    duplicados = sorted(n for n, fs in vistos.items() if len({f for f in fs}) > 1)
    # Hipótese inocente a declarar: reemissão do MESMO termo para colher assinatura que faltava —
    # o conjunto de assinantes de uma cópia contém estritamente o da outra.
    reemissao = {n for n in duplicados
                 if any(a < b for a in ({_n for _n, _ in f} for f in vistos[n])
                        for b in ({_n for _n, _ in f} for f in vistos[n]))}

    # A minuta só é ÓRFÃ se o instrumento correspondente não estiver nos autos. Um termo que está
    # na pasta mas sem rodapé de assinatura (assinado fora do SEI, ou capturado sem o fim do
    # texto) não é ausência: afirmar orfandade aí acusa por lacuna de captura. Medido em
    # 070002/001289/2022 — o 2º aditivo estava lá, sem rodapé (2026-08-03).
    ordinais_sem_rodape = {n for n, _ in sem_rodape}
    orfas = [n for n in ordinais_min
             if n not in ordinais_ass and n not in ordinais_sem_rodape] if ordinais_ass else []
    orfas = [n for n in orfas if _minuta_foi_atropelada(n, minutas, assinados)]
    if not duplicados and not orfas:
        return {"achado": False, "ordinal_minuta": ordinais_min[0] if ordinais_min else None,
                "ordinais_assinados": ordinais_ass, "duplicados": []}
    partes = []
    if orfas:
        partes.append(f"a minuta examinada é do {orfas[0]}º termo aditivo e nenhum instrumento "
                      f"assinado nos autos tem esse ordinal (assinados: "
                      f"{', '.join(f'{n}º' for n in ordinais_ass)})")
    if duplicados:
        partes.append("há mais de um instrumento assinado com o mesmo ordinal ("
                      + ", ".join(f"{n}º" for n in duplicados) + ")"
                      + (" — salvo reemissão do mesmo termo para colher assinatura faltante, "
                         "hipótese que os assinantes de uma das cópias sugerem e precisa ser "
                         "conferida nos autos" if reemissao else ""))
    ev = next((d for n, d in assinados if n in duplicados or n in ordinais_ass), None)
    return {
        "achado": True, "ordinal_minuta": ordinais_min[0] if ordinais_min else None,
        "ordinais_assinados": ordinais_ass, "duplicados": duplicados,
        "diz": " · ".join(partes),
        "fundamento": ("art. 38, parágrafo único, da Lei 8.666/93 (art. 53 da Lei 14.133/2021): o "
                       "exame jurídico prévio é DA MINUTA QUE SE CELEBRA — aprovar uma peça e "
                       "assinar outra esvazia o controle prévio"),
        "evidencia": (ev or {}).get("ref", "") if ev else "",
    }


# ─────────────────────── I2 · autorização antes do parecer ───────────────────────

def autorizacao_antes_do_parecer(docs: list[dict]) -> dict:
    """O ordenador autorizou a despesa antes da manifestação jurídica que a condiciona?"""
    aut = par = None
    pareceres_sem_data: list[str] = []
    for d in docs or []:
        tipo = _norm(d.get("tipo") or "")
        texto = d.get("texto") or ""
        e_aut = tipo in _TIPOS_AUTORIZACAO or _RE_CABECALHO_ATO.search(texto[:_CABECALHO_CHARS])
        if e_aut and e_ato_de_autorizacao(texto):
            dt = _primeira_data(d)
            if dt and (aut is None or _data(dt) < _data(aut[0])):
                aut = (dt, d)
        elif not e_aut and tipo in _TIPOS_PARECER and e_controle_juridico(d.get("ref") or "", texto):
            dt = _primeira_data(d)
            if not dt:
                pareceres_sem_data.append(str(d.get("ref") or ""))
            elif par is None or _data(dt) < _data(par[0]):
                par = (dt, d)
    # PARECER SEM DATA LEGÍVEL ⇒ não se compara. A comparação é "a autorização veio antes do
    # PRIMEIRO parecer"; se há parecer cuja data não se lê, o primeiro pode ser justamente ele, e
    # o achado estaria afirmando inversão sobre um universo incompleto. Medido em 2026-08-03:
    # 6 dos 13 disparos eram disto — e a causa é a mesma dos 1.969 documentos que o arquivo guarda
    # cortados em 20.000 caracteres, porque o rodapé de assinatura mora no FIM da peça.
    if pareceres_sem_data:
        return {"achado": False, "indisponivel": True,
                "motivo": ("há parecer sem data de assinatura legível nos autos ("
                           + "; ".join(p[:60] for p in pareceres_sem_data[:3])
                           + ") — não se afirma inversão sem saber quando o primeiro foi assinado"),
                "data_autorizacao": aut[0] if aut else None,
                "data_parecer": par[0] if par else None,
                "pareceres_sem_data": pareceres_sem_data}
    if not aut or not par:
        return {"achado": False, "indisponivel": True,
                "motivo": ("sem data de assinatura na autorização e/ou no parecer — não se afirma "
                           "inversão sem as duas datas"),
                "data_autorizacao": aut[0] if aut else None,
                "data_parecer": par[0] if par else None}
    if _data(aut[0]) >= _data(par[0]):
        return {"achado": False, "indisponivel": False,
                "data_autorizacao": aut[0], "data_parecer": par[0]}
    return {
        "achado": True, "indisponivel": False,
        "data_autorizacao": aut[0], "data_parecer": par[0],
        "diz": (f"a autorização de despesa foi assinada em {aut[0]} e o parecer jurídico em "
                f"{par[0]} — a autoridade autorizou ANTES da manifestação que condiciona o feito"),
        "fundamento": ("art. 38, caput e parágrafo único, da Lei 8.666/93 (art. 53 da Lei "
                       "14.133/2021) e art. 82 da Lei estadual 287/79: o controle prévio precede "
                       "a decisão que compromete a despesa"),
        "evidencia": f"{aut[1].get('ref', '')} ({aut[0]}) × {par[1].get('ref', '')} ({par[0]})",
    }


# ───────────── I3 · ato decisório sem a assinatura de quem decide ─────────────

def ato_sem_assinatura_da_autoridade(docs: list[dict]) -> dict:
    """O ato que autoriza a despesa foi assinado pela autoridade que ele nomeia como decisora?"""
    for d in docs or []:
        tipo = _norm(d.get("tipo") or "")
        texto = d.get("texto") or ""
        if tipo not in _TIPOS_AUTORIZACAO and not _RE_CABECALHO_ATO.search(texto[:1500]):
            continue
        # documento que se INTITULA minuta é rascunho: não se cobra dele a assinatura da
        # autoridade, porque ela ainda não decidiu. Falso positivo medido em 270003/001666/2024
        # ("Anexo MINUTA AUTORIZAÇÃO DE DESPESAS"). O achado real é o oposto: peça que NÃO se
        # intitula minuta e funciona como o ato, trazendo a marca interna no corpo.
        if _RE_E_MINUTA.search(str(d.get("ref") or "")):
            continue
        m = _RE_AUTORIDADE.search(texto)
        if not m:
            continue
        autoridade = re.sub(r"\s+", " ", m.group(1)).strip(" .,")
        ass = assinaturas(texto)
        marcado = bool(_RE_MARCA_MINUTA.search(texto[:2000]))
        if not ass:
            # Sem rodapé não se afirma nada: o ato pode ter sido assinado fora do SEI.
            return {"achado": False, "indisponivel": True, "autoridade": autoridade,
                    "quem_assinou": [], "marcado_minuta": marcado,
                    "base_da_comparacao": "indisponivel",
                    "motivo": "documento sem rodapé de assinatura eletrônica — pode ter sido "
                              "assinado fora do SEI; ausência de rodapé não prova ausência de ato"}
        nomes = [a["nome"] for a in ass]
        alvo = _norm(autoridade)
        # 1) IDENTIFICADOR manda: CPF, depois Id funcional. Só cai no nome quando não há nenhum.
        cpf_a, id_a = _identificador(autoridade, texto)
        base = "nome"
        assinou = None
        for n in nomes:
            cpf_n, id_n = _identificador(n, texto)
            if cpf_a and cpf_n:
                base = "cpf"
                if cpf_a == cpf_n:
                    assinou = True
                    break
                assinou = False
            elif id_a and id_n:
                if base != "cpf":
                    base = "id_funcional"
                if id_a == id_n:
                    assinou = True
                    break
                assinou = False
        if assinou is None:            # nenhum identificador dos dois lados
            assinou = any(alvo and _mesma_pessoa(alvo, n) for n in nomes)
        if assinou:
            return {"achado": False, "indisponivel": False, "autoridade": autoridade,
                    "quem_assinou": nomes, "marcado_minuta": marcado,
                    "base_da_comparacao": base}
        partes = [f"o ato nomeia {autoridade} como quem DECIDE, e a assinatura eletrônica é de "
                  + ", ".join(nomes)]
        if marcado:
            partes.insert(0, "o ato traz a marca \"MINUTA DE DOCUMENTO\" no topo")
        partes.append(f"identidade conferida por {base.replace('_', ' ')}")
        return {
            "achado": True, "indisponivel": False, "autoridade": autoridade,
            "quem_assinou": nomes, "marcado_minuta": marcado,
            "base_da_comparacao": base,
            "diz": " · ".join(partes),
            "fundamento": ("art. 82 da Lei estadual 287/79 e art. 38, caput, da Lei 8.666/93: a "
                           "autorização da despesa é ato do ORDENADOR — quem a redige não a decide"),
            "evidencia": d.get("ref", ""),
        }
    return {"achado": False, "indisponivel": False, "autoridade": "", "quem_assinou": [],
            "marcado_minuta": False, "base_da_comparacao": "nao_aplicavel"}




# ═══════════ I4 · ordinal incoerente com o prazo total declarado ═══════════
# Achado real: "2º TERMO ADITIVO" que dá ao contrato "prazo total de 24 meses". Contrato de 12 +
# esta prorrogação de 12 = 24 → é o 1º aditivo. Ordinal errado desalinha a contagem de TODO
# aditivo futuro, e o art. 57, II da Lei 8.666/93 limita as prorrogações a 60 meses.
_RE_PRAZO_TOTAL = re.compile(
    r"prazo\s+total\s+de\s+(\d{1,3})\s*\(", re.I)
_RE_PRORROGA_MESES = re.compile(
    r"prorrogad[oa]\s+(?:o\s+prazo[^.]{0,60}?)?por\s+(?:mais\s+)?(\d{1,3})\s*\(", re.I)


def ordinal_incoerente_com_prazo(docs: list[dict]) -> dict:
    """O ordinal declarado bate com o prazo total que o próprio instrumento anuncia?"""
    for d in docs or []:
        if _norm(d.get("tipo") or "") not in _TIPOS_INSTRUMENTO:
            continue
        texto = d.get("texto") or ""
        if _e_minuta(d) or not _RE_INSTRUMENTO.search(texto):
            continue
        n = _ordinal(d)
        mt, mp = _RE_PRAZO_TOTAL.search(texto), _RE_PRORROGA_MESES.search(texto)
        if n is None or not mt or not mp:
            continue
        total, passo = int(mt.group(1)), int(mp.group(1))
        if passo <= 0 or total % passo:
            continue                       # períodos irregulares: não se infere ordinal
        implicado = total // passo - 1     # contrato original + N prorrogações do mesmo tamanho
        if implicado == n or implicado < 0:
            continue
        return {
            "achado": True, "ordinal": n, "total_meses": total, "passo_meses": passo,
            "ordinal_implicado": implicado,
            "diz": (f"o instrumento se declara {n}º termo aditivo mas anuncia prazo total de "
                    f"{total} meses com prorrogação de {passo} — o que corresponde ao "
                    f"{implicado}º aditivo — salvo se houver aditivo anterior que NÃO prorrogou "
                    "prazo (aditivo de valor, por exemplo), hipótese que explica o ordinal sem "
                    "vício e precisa ser conferida nos autos"),
            "fundamento": ("art. 57, II, da Lei 8.666/93: a contagem das prorrogações é o que "
                           "limita a vigência a 60 meses — ordinal errado desalinha o controle"),
            "evidencia": d.get("ref", ""),
        }
    return {"achado": False, "ordinal": None, "total_meses": None, "ordinal_implicado": None}


# ═══════════ I5 · declaração que atesta conformidade de OUTRO contrato ═══════════
# Achado real: "a minuta da renovação do contrato 04/2022 segue a MINUTA-PADRÃO" num processo do
# Contrato 16/2023 — e é nessa declaração que o parecer se apoia para dar a conformidade por
# atendida. Documento de outro contrato usado como atestado neste.
_RE_NUM_CONTRATO = re.compile(r"contrato\s*(?:n?[ºo°.]?\s*)?(\d{1,4}\s*/\s*\d{4})", re.I)
_RE_E_DECLARACAO = re.compile(r"\bDECLARA[ÇC][ÃA]O\b|\bDeclaro\b", re.I)


def _num(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def declaracao_de_outro_contrato(docs: list[dict]) -> dict:
    """Declaração nos autos que atesta algo sobre um contrato DIFERENTE do que se discute."""
    do_processo = None
    for d in docs or []:
        if _norm(d.get("tipo") or "") in _TIPOS_INSTRUMENTO and _RE_INSTRUMENTO.search(
                d.get("texto") or ""):
            m = _RE_NUM_CONTRATO.search(d.get("texto") or "")
            if m:
                do_processo = _num(m.group(1))
                break
    if not do_processo:
        return {"achado": False, "contrato_do_processo": None, "contrato_citado": None}
    for d in docs or []:
        texto = d.get("texto") or ""
        if not _RE_E_DECLARACAO.search(texto[:600]):
            continue
        citados = {_num(m.group(1)) for m in _RE_NUM_CONTRATO.finditer(texto)}
        if not citados or do_processo in citados:
            continue
        return {
            "achado": True, "contrato_do_processo": do_processo,
            "contrato_citado": ", ".join(sorted(citados)),
            "diz": (f"declaração juntada aos autos atesta sobre o contrato "
                    f"{', '.join(sorted(citados))}, e o processo discute o contrato "
                    f"{do_processo} — documento de outro contrato usado como atestado neste"),
            "fundamento": ("a conformidade com a minuta-padrão da PGE (Resolução Conjunta "
                           "PGE/SEPLAG 187/2021) é atestada por declaração específica; "
                           "declaração de outro ajuste não a supre"),
            "evidencia": d.get("ref", ""),
        }
    return {"achado": False, "contrato_do_processo": do_processo, "contrato_citado": None}


# ═══════════ I6 · quantitativo do atesto diverge do objeto ═══════════
# Achado real: o objeto contratado são 03 aeronaves e o atesto do fiscal — requisito implícito da
# prorrogação (Enunciado 09 da PGE/RJ) — fala em 04. O parecer transcreveu sem enfrentar.
_RE_QTD_UNIDADE = re.compile(
    r"(\d{1,3})\s*\(\s*[a-zà-ú]+\s*\)\s+([a-zà-ú]{4,20}s?)\b", re.I)
# Unidade de TEMPO e de trâmite não é quantitativo do objeto. Falso positivo medido no processo
# real: "5 (cinco) dias" no objeto × "10 (dez) dias" no atesto viraram "quantitativo divergente".
# Guardadas JÁ na forma em que `_qtds` compara (normalizadas e sem o 's' final) — "meses" vira
# "mese", e escrever "meses" aqui deixava o veto passar batido. Falso positivo medido no acervo.
_UNIDADES_NAO_OBJETO = {
    "dia", "mese", "mes", "ano", "hora", "minuto", "semana", "prazo", "parcela", "via", "copia",
    "vez", "etapa", "fase", "item", "lote", "exercicio", "unidade", "percentual",
}
_RE_OBJETO = re.compile(r"do\s+objeto|CL[ÁA]USULA\s+PRIMEIRA", re.I)
_RE_ATESTO = re.compile(
    r"qualidade\s+da\s+presta[çc][ãa]o|presta[çc][ãa]o\s+de\s+servi[çc]o\s+compat[íi]vel|"
    r"executad[oa]\s+pela\s+contratada|atesto|a\s+contento", re.I)


def _qtds(texto: str) -> dict[str, int]:
    """{unidade: quantidade} das ocorrências no padrão do SEI ('03 (três) aeronaves')."""
    saida: dict[str, int] = {}
    for m in _RE_QTD_UNIDADE.finditer(texto or ""):
        uni = _norm(m.group(2)).rstrip("s")
        if uni in _UNIDADES_NAO_OBJETO:
            continue
        saida.setdefault(uni, int(m.group(1)))
    return saida


def quantitativo_divergente(docs: list[dict]) -> dict:
    """O atesto de boa execução fala do mesmo quantitativo que o objeto contratado?"""
    obj: dict[str, int] = {}
    for d in docs or []:
        texto = d.get("texto") or ""
        if _norm(d.get("tipo") or "") in _TIPOS_INSTRUMENTO and _RE_OBJETO.search(texto):
            obj = _qtds(texto)
            if obj:
                break
    if not obj:
        return {"achado": False, "objeto": None, "atesto": None}
    for d in docs or []:
        texto = d.get("texto") or ""
        if not _RE_ATESTO.search(texto):
            continue
        for uni, q in _qtds(texto).items():
            if uni in obj and obj[uni] != q:
                return {
                    "achado": True, "unidade": uni, "objeto": obj[uni], "atesto": q,
                    "diz": (f"o objeto contratado é de {obj[uni]} {uni}(s) e o atesto de execução "
                            f"fala em {q} — o documento que sustenta a prorrogação refere "
                            "quantitativo diferente do contratado"),
                    "fundamento": ("Enunciado 09 da PGE/RJ: o desempenho contratual satisfatório é "
                                   "requisito implícito da prorrogação — atesto sobre outro "
                                   "quantitativo não o comprova"),
                    "evidencia": d.get("ref", ""),
                }
    return {"achado": False, "objeto": obj, "atesto": None}


# ═══════════ I7 · quem o documento diz que aprovou não é quem assinou ═══════════
# Achado real na Justificativa 74779736: nomeia "Conferido por: RAFAEL BENVINDO FREITAS" e
# "Aprovado por: RODRIGO HINAGO", e as assinaturas eletrônicas são de Renato e Vinicius. É o I3
# generalizado: vale para QUALQUER peça que declare quem a conferiu ou aprovou.
# "de acordo" saiu do gatilho: no acervo real ele casou "a despesa está de acordo com a
# LEGISLACAO ORCAMENTARIA" e transformou a norma em nome de aprovador. Ficam só os blocos que
# declaram RESPONSABILIDADE por um ato — conferir, aprovar, autorizar.
_RE_BLOCO_APROVACAO = re.compile(
    r"(conferido\s+por|aprovado\s+por|autorizado\s+por|visto\s+por)\s*[:\-–]?\s*\n{0,3}\s*"
    r"([A-ZÀ-Ú][A-ZÀ-Ú\s\.]{5,60}?)\s*(?:\n|[-–,])", re.I)


def aprovador_nao_assinou(docs: list[dict]) -> dict:
    """Nomes declarados como conferente/aprovador que não constam das assinaturas eletrônicas."""
    for d in docs or []:
        texto = d.get("texto") or ""
        nomeados = [(m.group(1).strip(), re.sub(r"\s+", " ", m.group(2)).strip(" .,-–"))
                    for m in _RE_BLOCO_APROVACAO.finditer(texto)]
        # `nome_plausivel` é da casa (agentes_publicos) e já sabe recusar "meio do Processo
        # Admi" e "este coordenador" — dois falsos positivos medidos no acervo real.
        from compliance_agent.sei.agentes_publicos import nome_plausivel
        nomeados = [(p, n) for p, n in nomeados
                    if len(n.split()) >= 2 and nome_plausivel(n)]
        if not nomeados:
            continue
        ass = assinaturas(texto)
        if not ass:
            continue     # sem rodapé não se afirma nada: pode ter sido assinado fora do SEI
        nomes = [a["nome"] for a in ass]
        faltam = []
        for papel, nome in nomeados:
            cpf_a, id_a = _identificador(nome, texto)
            achou = False
            for n in nomes:
                cpf_n, id_n = _identificador(n, texto)
                if (cpf_a and cpf_n and cpf_a == cpf_n) or (id_a and id_n and id_a == id_n) \
                        or _mesma_pessoa(nome, n):
                    achou = True
                    break
            if not achou:
                faltam.append(f"{nome} ({papel.lower()})")
        if not faltam:
            continue
        return {
            "achado": True, "nao_assinaram": faltam, "quem_assinou": nomes,
            "diz": (f"o documento declara {'; '.join(faltam)}, e nenhum deles consta das "
                    f"assinaturas eletrônicas (assinaram: {', '.join(nomes)})"),
            "fundamento": ("art. 28 e 29 do Decreto est. 48.209/2022: no SEI a assinatura "
                           "eletrônica é a prova do ato — nome no corpo sem assinatura não "
                           "atesta conferência nem aprovação"),
            "evidencia": d.get("ref", ""),
        }
    return {"achado": False, "nao_assinaram": [], "quem_assinou": []}


# ───────────────────────────── saída no formato do 360 ─────────────────────────────

_GRAVIDADE = {
    "I1_ORDINAL_DIVERGENTE": "alta",
    "I2_AUTORIZACAO_ANTES_DO_PARECER": "alta",
    "I3_ATO_SEM_ASSINATURA_DA_AUTORIDADE": "critica",
    "I4_ORDINAL_INCOERENTE_COM_PRAZO": "media",
    "I5_DECLARACAO_DE_OUTRO_CONTRATO": "alta",
    "I6_QUANTITATIVO_DIVERGENTE": "alta",
    "I7_APROVADOR_NAO_ASSINOU": "media",
}
CODIGOS = tuple(_GRAVIDADE)


def avaliar(docs: list[dict]) -> list[dict]:
    """Os três, no formato de achado que `processo_360` consome. Sem prova literal, não entra."""
    saida: list[dict] = []
    for codigo, fn in (("I1_ORDINAL_DIVERGENTE", ordinal_divergente),
                       ("I2_AUTORIZACAO_ANTES_DO_PARECER", autorizacao_antes_do_parecer),
                       ("I3_ATO_SEM_ASSINATURA_DA_AUTORIDADE", ato_sem_assinatura_da_autoridade),
                       ("I4_ORDINAL_INCOERENTE_COM_PRAZO", ordinal_incoerente_com_prazo),
                       ("I5_DECLARACAO_DE_OUTRO_CONTRATO", declaracao_de_outro_contrato),
                       ("I6_QUANTITATIVO_DIVERGENTE", quantitativo_divergente),
                       ("I7_APROVADOR_NAO_ASSINOU", aprovador_nao_assinou)):
        try:
            r = fn(docs)
        except (AttributeError, TypeError, ValueError, re.error):
            continue
        if not r.get("achado"):
            continue
        saida.append({"origem": "instrumento_assinatura", "codigo": codigo,
                      "gravidade": _GRAVIDADE[codigo], "diz": r["diz"],
                      "fundamento": r.get("fundamento", ""),
                      "evidencia": r.get("evidencia", ""),
                      "ressalva": ("Indício a verificar, não acusação: presunção de legitimidade "
                                   "do ato administrativo e possibilidade de captura incompleta "
                                   "dos autos.")})
    return saida
