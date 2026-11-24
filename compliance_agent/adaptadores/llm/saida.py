# -*- coding: utf-8 -*-
"""saida — schema estrito + validação pós-parse das citações + abstenção (plano mestre v2 §3.10 inv. 4, O6.1 d).

Ordem (determinística, a mesma na resposta nova e no acerto de cache):
  1. parse do JSON (`llm/json_resposta.parse_json_llm`) — ou os `dados` que o backend já trouxe;
  2. desmascara (CPF/conta voltam ao texto original, localmente);
  3. ABSTEVE: `{"absteve": true, "motivo": "..."}` (ou `"estado": "ABSTEVE"`) ⇒ `Saida(ABSTEVE, motivo)`;
     abstenção sem motivo é erro (o estado exige motivo — `dominio/estados.Saida`);
  4. citações: cada item de `dados["citacoes"]` passa pelo VERIFICADOR (injetável); o que não confere é
     DESCARTADO (com o motivo). Nenhuma sobrou ⇒ `INDETERMINADO_FALHA_CITACAO` (sem prova literal, não há
     afirmação). O padrão: documento entre os enviados, `versao_sha256` igual, `1 ≤ pagina ≤ total`, trecho
     LITERAL na página (`llm/verificacao.citacao_existe`: ignora caixa, acento, aspas e espaços; ≥ 8 caracteres);
  5. schema: Pydantic (`BaseModel`) ⇒ `model_validate_json(strict=True)` (modo JSON: data em texto vale, "3" por int não) sobre os dados já filtrados (erro ⇒ a camada
     falhou); dict/str (o formato antigo) ⇒ `chaves_faltando`, como antes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from compliance_agent.adaptadores.llm.prompt_seguro import Documento, limpar_invisiveis
from compliance_agent.dominio.estados import Saida, absteve

RESPONDIDO = "RESPONDIDO"
ABSTEVE = "ABSTEVE"
INDETERMINADO_FALHA_CITACAO = "INDETERMINADO_FALHA_CITACAO"

Verificador = Callable[[dict, dict], "tuple[bool, str]"]


@dataclass
class Processado:
    estado: str | None = None          # RESPONDIDO | ABSTEVE | INDETERMINADO_FALHA_CITACAO; None = falhou (erro)
    dados: object = None
    saida: Saida | None = None
    erro: str = ""
    descartadas: list = field(default_factory=list)   # [(documento_id, motivo)] — nunca o trecho


def eh_pydantic(schema) -> bool:
    return isinstance(schema, type) and hasattr(schema, "model_validate") and hasattr(schema, "model_json_schema")


def schema_para_backend(schema):
    """O que os backends entendem (JSON Schema em dict): Pydantic vira `model_json_schema()`."""
    return schema.model_json_schema() if eh_pydantic(schema) else schema


def repr_schema(schema) -> str:
    s = schema_para_backend(schema)
    return s if isinstance(s, str) or s is None else json.dumps(s, ensure_ascii=False, sort_keys=True, default=str)


def _desmascarar_obj(x, desm: Callable[[str], str]):
    if isinstance(x, str):
        return desm(x)
    if isinstance(x, dict):
        return {k: _desmascarar_obj(v, desm) for k, v in x.items()}
    if isinstance(x, list):
        return [_desmascarar_obj(v, desm) for v in x]
    return x


def verificar_citacao(cit: dict, documentos: dict) -> tuple[bool, str]:
    """Verificador padrão. `documentos`: {documento_id: Documento} do que foi enviado nesta chamada."""
    from compliance_agent.llm.verificacao import citacao_existe
    if not isinstance(cit, dict):
        return False, "citação não é objeto"
    did = str(cit.get("documento_id") or "")
    d: Documento | None = documentos.get(did)
    if d is None:
        return False, "documento não está entre os enviados"
    if str(cit.get("versao_sha256") or "").strip().lower() != str(d.versao_sha256).lower():
        return False, "versao_sha256 não confere"
    pag = cit.get("pagina")
    if pag is None and d.total_paginas == 1:
        pag = 1
    try:
        pag = int(pag)
    except (TypeError, ValueError):
        return False, "página ausente ou não numérica"
    if not 1 <= pag <= d.total_paginas:
        return False, f"página {pag} fora de 1..{d.total_paginas}"
    if not citacao_existe(str(cit.get("trecho") or ""), limpar_invisiveis(d.pagina(pag))):
        return False, "trecho não está literalmente na página"
    return True, ""


def processar(texto: str, dados_backend, *, schema, exigir_citacao: bool, documentos: list[Documento] | None,
              verificador: Verificador | None, desmascarar: Callable[[str], str]) -> Processado:
    from compliance_agent.llm.json_resposta import chaves_faltando, parse_json_llm
    if schema is None and not exigir_citacao:
        return Processado(RESPONDIDO, _desmascarar_obj(dados_backend, desmascarar))
    dados = dados_backend if dados_backend is not None else parse_json_llm(texto)
    if not isinstance(dados, dict):
        return Processado(erro="resposta sem o JSON pedido")
    dados = _desmascarar_obj(dados, desmascarar)

    if dados.get("absteve") is True or str(dados.get("estado") or "").upper() == ABSTEVE:
        try:
            s = absteve(str(dados.get("motivo") or "").strip())
        except ValueError:
            return Processado(erro="abstenção sem motivo")
        return Processado(ABSTEVE, dados, saida=s)

    descartadas = []
    cits = dados.get("citacoes")
    if exigir_citacao or cits is not None:
        docs = {d.documento_id: d for d in documentos or []}
        ver = verificador or verificar_citacao
        validas = []
        for c in cits if isinstance(cits, list) else []:
            ok, motivo = ver(c, docs)
            if ok:
                validas.append(c)
            else:
                descartadas.append((str(c.get("documento_id") if isinstance(c, dict) else "?")[:40], motivo))
        dados = {**dados, "citacoes": validas}
        if not validas:
            return Processado(INDETERMINADO_FALHA_CITACAO, dados, descartadas=descartadas)

    if eh_pydantic(schema):
        from pydantic import ValidationError
        try:
            return Processado(RESPONDIDO, schema.model_validate_json(json.dumps(dados, ensure_ascii=False), strict=True), descartadas=descartadas)
        except ValidationError as e:
            errs = e.errors()
            prim = "; ".join(f"{'.'.join(map(str, x.get('loc', ())))}: {x.get('type')}" for x in errs[:3])
            return Processado(erro=f"schema estrito: {len(errs)} erro(s) ({prim})", descartadas=descartadas)
    if schema is not None:
        falta = chaves_faltando(dados, schema)
        if falta:
            return Processado(erro="resposta sem o JSON pedido (faltam " + ", ".join(falta[:5]) + ")",
                              descartadas=descartadas)
    return Processado(RESPONDIDO, dados, descartadas=descartadas)
