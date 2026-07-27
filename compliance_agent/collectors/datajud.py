# -*- coding: utf-8 -*-
"""datajud — API Pública do DataJud/CNJ (Base Nacional de Dados do Poder Judiciário).

Cobre os 182 tribunais. Chave pública documentada pelo CNJ (datajud-wiki.cnj.jus.br), sem cadastro.
Back-end é Elasticsearch: POST `{indice}/_search` com query ES no corpo.
**Verificado 2026-07-27 da VM: HTTP 200, sem WAF.**

HONESTIDADE SOBRE O QUE ESTA BASE **NÃO** TEM (medido no acervo real, não na doc):
os documentos trazem só METADADOS — `numeroProcesso`, `classe`, `assuntos`, `orgaoJulgador`,
`dataAjuizamento`, `movimentos` (tabela CNJ). **Não há nome de parte, CPF/CNPJ nem teor de decisão**
(Portaria CNJ 160/2020, resguardo das partes). Logo:
  - NÃO serve para "achar processo do fornecedor X pelo CNPJ" — isso é falso na doc de terceiros;
  - SERVE para (a) puxar a vida inteira de um processo cujo NÚMERO já temos (do SEI, do TCE, do
    D.O.), e (b) medir a judicialização de um órgão julgador/comarca por classe processual.

Uso no JFN: quando um processo SEI/edital cita um número CNJ, `resumo_processo` diz se já há
ação de improbidade / ACP / mandado de segurança viva sobre aquilo, e em que pé está. Um achado
nosso sobre objeto JÁ judicializado muda a recomendação (representação → subsídio ao MP/juízo).
"""
from __future__ import annotations

import re
from typing import Any

import httpx

_BASE = "https://api-publica.datajud.cnj.jus.br"
# Chave PÚBLICA publicada pelo CNJ na wiki oficial da API — não é credencial de usuário.
_APIKEY = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
_HEADERS = {"Authorization": f"APIKey {_APIKEY}", "Content-Type": "application/json"}

# Movimentos da Tabela Processual Unificada do CNJ que mudam o peso de um achado nosso.
MOVIMENTOS_DESFECHO = {
    219: "Procedência",
    220: "Improcedência",
    218: "Procedência em parte",
    242: "Extinção sem resolução do mérito",
    848: "Homologação de acordo",
    471: "Concessão de liminar/antecipação de tutela",
    455: "Suspensão",
}

# Classes da Tabela CNJ que interessam ao controle externo.
CLASSES_CONTROLE = {
    64: "Ação Civil de Improbidade Administrativa",
    65: "Ação Civil Pública",
    120: "Mandado de Segurança Cível",
    1116: "Execução Fiscal",
    169: "Ação Popular",
}

_RE_CNJ = re.compile(r"(\d{7})-?(\d{2})\.?(\d{4})\.?(\d)\.?(\d{2})\.?(\d{4})")


def indice(tribunal: str) -> str:
    """'TJRJ' -> 'api_publica_tjrj'."""
    return f"api_publica_{tribunal.strip().lower()}"


def normalizar_numero(numero: str) -> str | None:
    """Número CNJ com ou sem máscara -> 20 dígitos puros (formato do campo `numeroProcesso`)."""
    m = _RE_CNJ.search(numero or "")
    return "".join(m.groups()) if m else None


def tribunal_do_numero(numero: str) -> str | None:
    """Deriva o tribunal do próprio número CNJ (NNNNNNN-DD.AAAA.J.TR.OOOO).

    Só resolve com segurança o que interessa aqui: Justiça Estadual (J=8) -> TJ{UF}.
    Nos demais segmentos o par J.TR não mapeia para uma sigla sem tabela auxiliar; devolve None
    em vez de chutar.
    """
    puro = normalizar_numero(numero)
    if not puro:
        return None
    j, tr = puro[13], puro[14:16]
    ufs = {"01": "AC", "02": "AL", "03": "AP", "04": "AM", "05": "BA", "06": "CE", "07": "DF",
           "08": "ES", "09": "GO", "10": "MA", "11": "MT", "12": "MS", "13": "MG", "14": "PA",
           "15": "PB", "16": "PR", "17": "PE", "18": "PI", "19": "RJ", "20": "RN", "21": "RS",
           "22": "RO", "23": "RR", "24": "SC", "25": "SE", "26": "SP", "27": "TO"}
    if j == "8" and tr in ufs:
        return f"TJ{ufs[tr]}"
    return None


def buscar(tribunal: str, query: dict, size: int = 10, timeout: int = 90,
           sort: list | None = None) -> list[dict]:
    """Query Elasticsearch crua contra o índice do tribunal. Devolve os `_source`."""
    corpo: dict[str, Any] = {"size": size, "query": query}
    if sort:
        corpo["sort"] = sort
    r = httpx.post(f"{_BASE}/{indice(tribunal)}/_search", headers=_HEADERS,
                   json=corpo, timeout=timeout)
    r.raise_for_status()
    return [h["_source"] for h in r.json().get("hits", {}).get("hits", [])]


def consultar_processo(numero: str, tribunal: str | None = None,
                       timeout: int = 90) -> dict | None:
    """Documento completo de UM processo. `tribunal` é deduzido do número quando omitido."""
    puro = normalizar_numero(numero)
    if not puro:
        return None
    trib = tribunal or tribunal_do_numero(puro)
    if not trib:
        return None
    # `term` (exato) em vez de `match`: sem analisador no meio. A API é LENTA por natureza
    # (25-35 s medidos no índice do TJRJ) — daí o timeout folgado.
    achados = buscar(trib, {"term": {"numeroProcesso": puro}}, size=1, timeout=timeout)
    return achados[0] if achados else None


def resumo_processo(numero: str, tribunal: str | None = None,
                    timeout: int = 90) -> dict:
    """Leitura pronta para o parecer: classe, assuntos, vara, idade e DESFECHO se houver.

    `desfechos` só lista movimentos da tabela CNJ efetivamente presentes — nada é inferido.
    """
    doc = consultar_processo(numero, tribunal, timeout=timeout)
    if not doc:
        return {"numero": numero, "encontrado": False,
                "observacao": "não localizado no DataJud (ou tribunal fora do segmento estadual)"}

    movs = doc.get("movimentos") or []
    desfechos = [
        {"codigo": m.get("codigo"), "nome": m.get("nome") or MOVIMENTOS_DESFECHO.get(m.get("codigo")),
         "data": m.get("dataHora")}
        for m in movs if m.get("codigo") in MOVIMENTOS_DESFECHO
    ]
    ultimo = max(movs, key=lambda m: m.get("dataHora") or "", default=None)
    classe = (doc.get("classe") or {})
    return {
        "numero": doc.get("numeroProcesso"),
        "encontrado": True,
        "tribunal": doc.get("tribunal"),
        "grau": doc.get("grau"),
        "classe": classe.get("nome"),
        "classe_codigo": classe.get("codigo"),
        "e_classe_de_controle": classe.get("codigo") in CLASSES_CONTROLE,
        "assuntos": [a.get("nome") for a in (doc.get("assuntos") or [])],
        "orgao_julgador": (doc.get("orgaoJulgador") or {}).get("nome"),
        "municipio_ibge": (doc.get("orgaoJulgador") or {}).get("codigoMunicipioIBGE"),
        "data_ajuizamento": doc.get("dataAjuizamento"),
        "sigilo": doc.get("nivelSigilo"),
        "qtd_movimentos": len(movs),
        "ultimo_movimento": {"nome": (ultimo or {}).get("nome"),
                             "data": (ultimo or {}).get("dataHora")} if ultimo else None,
        "desfechos": desfechos,
        "ja_julgado": bool(desfechos),
    }


def contar_por_classe(tribunal: str, classe_codigo: int, desde_ano: int | None = None,
                      municipio_ibge: int | None = None, timeout: int = 90) -> int:
    """Quantos processos de uma classe (ex.: 64 = improbidade) num tribunal/comarca.

    Sinal de contexto, não achado: comarca com muita improbidade é onde o controle já opera.
    """
    must: list[dict] = [{"term": {"classe.codigo": classe_codigo}}]
    if municipio_ibge:
        must.append({"term": {"orgaoJulgador.codigoMunicipioIBGE": municipio_ibge}})
    if desde_ano:
        must.append({"range": {"dataAjuizamento": {"gte": f"{desde_ano}0101000000"}}})
    r = httpx.post(f"{_BASE}/{indice(tribunal)}/_count", headers=_HEADERS,
                   json={"query": {"bool": {"must": must}}}, timeout=timeout)
    r.raise_for_status()
    return int(r.json().get("count", 0))


def extrair_numeros_cnj(texto: str) -> list[str]:
    """Todo número CNJ citado num texto (processo SEI, edital, parecer) — 20 dígitos, sem repetir."""
    vistos: list[str] = []
    for m in _RE_CNJ.finditer(texto or ""):
        puro = "".join(m.groups())
        if puro not in vistos:
            vistos.append(puro)
    return vistos


def judicializacao_de_documento(texto: str, timeout: int = 90) -> list[dict]:
    """Varre um documento, acha os números CNJ e devolve o resumo de cada um.

    É o gancho para o Lex: achado sobre objeto já sub judice muda a recomendação.
    """
    return [resumo_processo(n, timeout=timeout) for n in extrair_numeros_cnj(texto)]


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys
    print(json.dumps(resumo_processo(sys.argv[1]), ensure_ascii=False, indent=2))
