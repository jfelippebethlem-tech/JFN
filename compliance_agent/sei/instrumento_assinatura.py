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
_RE_E_MINUTA = re.compile(r"\bminuta\b", re.I)
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


def _ordinal(doc: dict) -> int | None:
    m = _RE_ORDINAL_ADITIVO.search(doc.get("texto") or "")
    return int(m.group(1)) if m else None


def _e_minuta(doc: dict) -> bool:
    """Minuta é a peça submetida ao exame; o instrumento é o que se celebra."""
    alvo = f"{doc.get('ref') or ''} {(doc.get('texto') or '')[:400]}"
    return bool(_RE_E_MINUTA.search(alvo))


# ───────────────────────────── I1 · ordinal divergente ─────────────────────────────

def ordinal_divergente(docs: list[dict]) -> dict:
    """A minuta aprovada corresponde a algum instrumento assinado? Há ordinal repetido?"""
    minutas, assinados = [], []
    for d in docs or []:
        n = _ordinal(d)
        if n is None:
            continue
        if _norm(d.get("tipo") or "") not in _TIPOS_INSTRUMENTO:
            continue                      # parecer/justificativa citam o ordinal, não o celebram
        if not _RE_INSTRUMENTO.search(d.get("texto") or ""):
            continue                      # sem fórmula de celebração não é o instrumento
        (minutas if _e_minuta(d) else assinados).append((n, d))
    ordinais_min = sorted({n for n, _ in minutas})
    ordinais_ass = sorted({n for n, _ in assinados})
    # ordinal que aparece em MAIS DE UM instrumento assinado
    vistos: dict[int, int] = {}
    for n, _ in assinados:
        vistos[n] = vistos.get(n, 0) + 1
    duplicados = sorted(n for n, k in vistos.items() if k > 1)

    orfas = [n for n in ordinais_min if n not in ordinais_ass] if ordinais_ass else []
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
                      + ", ".join(f"{n}º" for n in duplicados) + ")")
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
    for d in docs or []:
        tipo = _norm(d.get("tipo") or "")
        texto = d.get("texto") or ""
        if tipo in _TIPOS_AUTORIZACAO or _RE_CABECALHO_ATO.search(texto[:1500]):
            dt = _primeira_data(d)
            if dt and (aut is None or _data(dt) < _data(aut[0])):
                aut = (dt, d)
        elif tipo in _TIPOS_PARECER:
            dt = _primeira_data(d)
            if dt and (par is None or _data(dt) < _data(par[0])):
                par = (dt, d)
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


# ───────────────────────────── saída no formato do 360 ─────────────────────────────

_GRAVIDADE = {
    "I1_ORDINAL_DIVERGENTE": "alta",
    "I2_AUTORIZACAO_ANTES_DO_PARECER": "alta",
    "I3_ATO_SEM_ASSINATURA_DA_AUTORIDADE": "critica",
}


def avaliar(docs: list[dict]) -> list[dict]:
    """Os três, no formato de achado que `processo_360` consome. Sem prova literal, não entra."""
    saida: list[dict] = []
    for codigo, fn in (("I1_ORDINAL_DIVERGENTE", ordinal_divergente),
                       ("I2_AUTORIZACAO_ANTES_DO_PARECER", autorizacao_antes_do_parecer),
                       ("I3_ATO_SEM_ASSINATURA_DA_AUTORIDADE", ato_sem_assinatura_da_autoridade)):
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
