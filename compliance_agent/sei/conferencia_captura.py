# -*- coding: utf-8 -*-
"""O parecer lista os autos — e essa lista confere a NOSSA captura, documento a documento.

Achado na leitura integral do SEI-270131/000548/2023 (2026-08-03): o relatório do Parecer 462
enumera 31 documentos, cada um com o seu número SEI, e **4 não estavam no nosso arquivo** —
entre eles a documentação de habilitação (74889283) e a planilha de formação de preço
(74889284), que são exatamente a prova de duas das condicionantes que o mesmo parecer impõe.

Por que isso vale tanto: até aqui a casa media a integridade da captura por CONTAGEM DE TEXTO
(`manifesto_norm.captura_integra`) — um limiar interno, que responde "parece pouco". O parecer
responde outra coisa, e melhor: **quais** documentos deveriam estar aqui, com número. É verdade
externa, produzida por um terceiro dentro dos próprios autos, e transforma "captura incompleta"
em uma lista de trabalho para o sweep.

REGRA DURA: isto NUNCA é achado contra o processo. A gravidade é `captura` — o defeito é da
nossa coleta, e imputá-lo ao gestor seria o oposto do que esta casa existe para fazer. Onde há
lacuna, o veredito sobre condicionante se lê com ela declarada: INDISPONÍVEL ≠ descumprido.
"""
from __future__ import annotations

import re

# Onde o parecer LISTA a instrução. Depois disso vem a fundamentação, e ali os números que
# aparecem são de precedentes e normas citadas — cobrar aqueles mandaria o sweep atrás de
# documento que nunca esteve nestes autos.
_RE_FIM_RELATORIO = re.compile(
    r"(II\s*[.\-–]\s*FUNDAMENTA[ÇC][ÃA]O|FUNDAMENTA[ÇC][ÃA]O\s*[:.]|"
    r"II\s*[.\-–]\s*AN[ÁA]LISE|[ée]\s+o\s+relat[óo]rio)", re.I)
# 8-9 dígitos: é o formato do número de documento do SEI-RJ (65334602, 134272869). Com 7 entravam
# números de norma e de processo citados no relatório, e a fila de captura ia atrás do que nunca
# foi documento destes autos — medido no acervo em 2026-08-03.
_RE_ID_SEI = re.compile(r"\b([1-9]\d{7,8})\b")   # nunca começa com zero
_TIPOS_PARECER = {"parecer", "parecer_juridico", "manifestacao_juridica", "cota_juridica"}
_RE_NUM_PROCESSO = re.compile(r"\b(\d{6}\s*/\s*\d{6}\s*/\s*\d{4})\b")
# Janela antes do ID onde uma citação a OUTRO processo o desqualifica como documento DESTES autos.
# Medido no acervo: "…nos autos administrativos SEI-030029/005620/2023 sob index 51726816" — o
# documento existe, mas em processo alheio; cobrá-lo mandaria o sweep ao lugar errado.
_JANELA_PROCESSO = 140
# O rodapé do SEI traz o TELEFONE da unidade, que tem 8 dígitos como um número de documento —
# medido: "Telefone: 23809230" ia para a fila de captura. Mesma coisa para CEP e CNPJ soltos.
_RE_NAO_E_DOC = re.compile(r"(telefone|fone|tel\.?|cep|cnpj|fax)\s*:?\s*$", re.I)


def numero_do_processo(texto: str) -> str | None:
    """Número do processo declarado no cabeçalho do parecer ('PROCESSO Nº SEI-…')."""
    m = re.search(r"PROCESSO\s*N?[ºo°.]?\s*:?\s*SEI-?\s*(\d{6}\s*/\s*\d{6}\s*/\s*\d{4})",
                  texto or "", re.I)
    if m:
        return re.sub(r"\s+", "", m.group(1))
    m = _RE_NUM_PROCESSO.search(texto or "")
    return re.sub(r"\s+", "", m.group(1)) if m else None


def _ids(texto: str, proprio: str | None = None) -> set[str]:
    """IDs de documento no texto. Com `proprio`, descarta o que a frase atribui a OUTRO processo."""
    saida: set[str] = set()
    for m in _RE_ID_SEI.finditer(texto or ""):
        antes_curto = (texto or "")[max(0, m.start() - 18):m.start()]
        if _RE_NAO_E_DOC.search(antes_curto.rstrip()):
            continue                      # telefone/CEP/CNPJ do rodapé, não documento
        if proprio:
            janela = (texto or "")[max(0, m.start() - _JANELA_PROCESSO):m.start()]
            # a citação a outro processo vale só até o fim da ORAÇÃO: no acervo, "…SEI-030029/
            # 005620/2023 sob index 51726816; e o Ofício (51000222) destes autos" fazia o segundo
            # documento, que é destes autos, cair junto com o primeiro.
            corte = max(janela.rfind(";"), janela.rfind("."), janela.rfind("\n"))
            if corte >= 0:
                janela = janela[corte + 1:]
            alheios = {re.sub(r"\s+", "", x) for x in _RE_NUM_PROCESSO.findall(janela)}
            if alheios and proprio not in alheios:
                continue                  # a frase fala de documento de processo alheio
        saida.add(m.group(1))
    return saida


def _cabecalho_do_arquivo(texto: str) -> str:
    """A linha '[Título (ID)] (tipo: X)' que o arquivo compacto grava no topo de cada documento.

    É a única parte do texto que identifica O PRÓPRIO documento. Medido: o parecer cita
    'Relatório de Fiscalização (121178482)' e o documento ESTÁ na pasta com título sem número —
    sem ler o cabeçalho, a conferência mandava recapturar o que já temos. E varrer o texto inteiro
    faria o parecer "capturar" tudo o que ele mesmo lista, zerando a conferência.
    """
    linha = (texto or "").lstrip().split("\n", 1)[0]
    return linha if linha.startswith("[") else ""


def _relatorio(texto: str) -> str:
    """A parte do parecer que lista os autos. Sem marca de fim, vale o começo da peça."""
    m = _RE_FIM_RELATORIO.search(texto or "")
    return (texto or "")[:m.start()] if m else (texto or "")[:6000]


def conferir(docs: list[dict]) -> dict:
    """Documentos que o parecer diz existirem nos autos e que NÃO estão na nossa captura."""
    pareceres = [d for d in docs or []
                 if (d.get("tipo") or "").strip().lower() in _TIPOS_PARECER]
    if not pareceres:
        return {"achado": False, "indisponivel": True, "ausentes": [], "n_citados": 0,
                "motivo": "nenhum parecer entre os documentos — sem lista externa para conferir"}
    citados: set[str] = set()
    for p in pareceres:
        texto = p.get("texto") or ""
        citados |= _ids(_relatorio(texto), numero_do_processo(texto))
    if not citados:
        return {"achado": False, "indisponivel": True, "ausentes": [], "n_citados": 0,
                "motivo": "o parecer não enumera os documentos dos autos"}
    # o que TEMOS: o número aparece no título do documento capturado (padrão do SEI-RJ)
    # O que TEMOS: o número aparece no título E no cabeçalho do texto capturado. Medido: o parecer
    # cita "Relatório de Fiscalização (121178482)", o documento ESTÁ na pasta e o título dele não
    # traz o número — cobrar a recaptura mandaria o sweep buscar o que já temos.
    nossos: set[str] = set()
    for d in docs or []:
        nossos |= _ids(str(d.get("ref") or ""))
        # A etiqueta do arquivo vem EXPLÍCITA em `d["etiqueta"]` desde 2026-08-03: o texto passou
        # a chegar limpo dela (ver `sei/acervo_texto`) porque punha a nossa classificação dentro
        # do documento. Aqui ela continua sendo prova legítima — quando o manifesto foi
        # reconstruído do nome do arquivo, o título perde o número e só a etiqueta ainda o tem.
        # O fallback lê do próprio texto para quem ainda passa o bruto.
        nossos |= _ids(str(d.get("etiqueta") or "")
                       or _cabecalho_do_arquivo(d.get("texto") or ""))
    ausentes = sorted(citados - nossos)
    if not ausentes:
        return {"achado": False, "indisponivel": False, "ausentes": [],
                "n_citados": len(citados)}
    return {
        "achado": True, "indisponivel": False, "ausentes": ausentes,
        "n_citados": len(citados), "gravidade": "captura",
        "diz": (f"o parecer jurídico lista {len(citados)} documentos nos autos e "
                f"{len(ausentes)} não estão na nossa captura ({', '.join(ausentes[:8])}"
                f"{'…' if len(ausentes) > 8 else ''}). Lacuna da COLETA, não do processo: o que "
                "depender desses documentos fica INDISPONÍVEL, nunca descumprido."),
        "evidencia": ", ".join(ausentes[:12]),
        "acao": "capturar os documentos listados e reavaliar o processo",
    }


def avaliar(docs: list[dict]) -> list[dict]:
    """No formato de achado do `processo_360` — com gravidade `captura`, jamais de mérito."""
    r = conferir(docs)
    if not r.get("achado"):
        return []
    return [{"origem": "conferencia_captura", "codigo": "C1_DOCUMENTO_CITADO_NAO_CAPTURADO",
             "gravidade": "captura", "diz": r["diz"], "evidencia": r["evidencia"],
             "acao": r["acao"], "ausentes": r["ausentes"],
             "ressalva": ("Lacuna de CAPTURA declarada. Não é vício do processo e não pesa contra "
                          "o gestor: mede o que a nossa coleta ainda não trouxe.")}]
