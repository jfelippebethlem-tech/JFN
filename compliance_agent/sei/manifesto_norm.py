# -*- coding: utf-8 -*-
"""Adaptador READ-side do manifest do sei_arquivo — UM shape para os DOIS escritores.

O acervo tem dois formatos (medição 2026-08-01, 2.057 manifests):
  A. `tools/sei_arquivar.py` (270): `fase` preenchida, `i` int, linha_do_tempo dict[fase,int];
  B. `tools/sei_arquivar_do_cache.py` (1.787): `fase:""` SEMPRE, `i` string,
     linha_do_tempo dict[fase,list] — 72% dos 33.973 docs sem fase.
E dois vocabulários de `tipo`: o FINO de `sei/fases.py` (canônico daqui em diante) e o
grosso de `sei/classificador_doc.py` (empenho vs nota_empenho; parecer_juridico vs parecer).

Este módulo NUNCA regrava o manifest em disco — devolve um dict normalizado novo
(`_norm` sela e torna a operação idempotente). Consumidor canônico: `processo_360`.

O gate `captura_integra` segue a lição da triagem pericial ("MEDIR PELO TEXTO, NÃO PELA
ETIQUETA", tools/sei_triagem_pericia.py): arquivo de texto no disco ≥60% dos docs; as
etiquetas do manifest (`captura_vazia`) só VETAM, nunca aprovam.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from compliance_agent.sei import acervo_texto, fases

_BASE = Path(__file__).resolve().parents[2] / "data" / "sei_arquivo"

# gordo (classificador_doc.TIPOS) → fino (fases._REGRAS). Ambíguos ficam FORA do mapa
# e resolvem pelo título via fases.classificar (tramitacao pode ser despacho OU ofício).
MAPA_TIPO_CANONICO = {
    "parecer_juridico": "parecer",
    "empenho": "nota_empenho",
    "liquidacao": "nota_liquidacao",
    "tr": "termo_referencia",
    "mapa_lances": "julgamento",
    "planilha_preco": "proposta",
    # idênticos nos dois vocabulários (explícito p/ leitura):
    "homologacao": "homologacao", "ata_rp": "ata_rp", "contrato": "contrato",
    "pesquisa_precos": "pesquisa_precos", "etp": "etp", "edital": "edital",
    "ordem_bancaria": "ordem_bancaria", "autorizacao_despesa": "autorizacao_despesa",
}

_TIPOS_FINOS = {t for t, _, _ in fases._REGRAS} | {"outro", "vazio"}


def tipo_canonico(tipo_original: str | None, titulo: str) -> str:
    """Tipo no vocabulário canônico (o fino de `sei/fases.py`)."""
    t = (tipo_original or "").strip()
    canon = t if t in _TIPOS_FINOS else MAPA_TIPO_CANONICO.get(t)
    # o TÍTULO desmente o tipo (doutrina da cadeia_processo): "CERTIDÕES ... PGE" virava
    # parecer_juridico e "Nota Fiscal" virava contrato (classificador por CONTEÚDO mente em
    # doc escaneado) — nos tipos SENSÍVEIS a marcos, o classificador fino por título tem a
    # última palavra quando diverge.
    if canon in ("parecer", "contrato"):
        fino = fases.classificar(titulo)[1]
        if fino not in (canon, "outro", "vazio"):
            return fino
    if canon:
        return canon
    # ambíguo (tramitacao/outros/vazio) ou desconhecido → o título decide; honesto se nada casa
    return fases.classificar(titulo)[1]


def carregar(numero_sei: str) -> dict | None:
    """Localiza a pasta do processo no acervo e devolve o manifest CRU (com `_pasta`)."""
    tag = re.sub(r"\D", "_", re.sub(r"^SEI-?", "", str(numero_sei or ""))).strip("_")
    tag = re.sub(r"_+", "_", tag)
    pasta = _BASE / tag
    mf = pasta / "manifest.json"
    if not mf.exists():
        return None
    try:
        man = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    man["_pasta"] = str(pasta)
    return man


def normalizar(manifest: dict) -> dict:
    """Manifest de qualquer formato → shape canônico. Puro (não muta a entrada), idempotente."""
    if manifest.get("_norm"):
        return copy.deepcopy(manifest)
    man = copy.deepcopy(manifest)
    avisos: list[str] = []

    docs = [d for d in (man.get("docs") or []) if isinstance(d, dict)]
    for d in docs:
        try:
            d["i"] = int(str(d.get("i")))
        except (TypeError, ValueError):
            avisos.append(f"i incoercível: {d.get('i')!r} em {str(d.get('titulo'))[:60]}")
            d["i"] = -1
        titulo = str(d.get("titulo") or "")
        d["tipo_original"] = d.get("tipo")
        d["tipo"] = tipo_canonico(d.get("tipo"), titulo)
        if not d.get("fase"):
            # usa o TIPO já resolvido quando o título é mudo: um Termo de Referência intitulado
            # "Formulário de solicitação de material ou serviço" ficava em fase `indefinida` e o
            # processo era acusado de não ter planejamento (SEI-080007/001365/2024, 2026-08-03).
            d["fase"] = fases.classificar_com_tipo(titulo, d.get("tipo") or "")[0]
    man["docs"] = docs

    # linha do tempo canônica: dict[fase, list[i]] reconstruída dos docs normalizados
    # (a original — int OU lista de títulos — fica preservada em linha_do_tempo_original)
    if "linha_do_tempo_original" not in man:
        man["linha_do_tempo_original"] = man.get("linha_do_tempo")
    tl: dict[str, list[int]] = {f: [] for f in fases.FASES}
    for d in sorted(docs, key=lambda x: x["i"]):
        tl.setdefault(d["fase"], []).append(d["i"])
    man["linha_do_tempo"] = tl

    man["_norm"] = {"versao": 1, "origem": man.get("origem") or "?", "avisos": avisos}
    return man


def captura_integra(manifest: dict, pasta: Path | str | None = None) -> tuple[bool, dict]:
    """(íntegra?, evidência). Texto no disco decide; etiquetas do manifest só vetam."""
    docs = [d for d in (manifest.get("docs") or []) if isinstance(d, dict)]
    pasta = Path(pasta or manifest.get("_pasta") or "")
    txt = pasta / "texto"
    n_txt = len(list(txt.glob("*"))) if txt.exists() else 0
    # CONTAR ARQUIVO NÃO É CONTAR TEXTO. 10.332 dos 45.161 arquivos do acervo (22,9%) trazem só a
    # etiqueta `[título] (fase: … · tipo: …)` que nós mesmos escrevemos — zero conteúdo. Contando
    # arquivos, 7 processos passavam por ÍNTEGROS com quase metade dos textos vazios e recebiam
    # faixa de risco sobre o que não se leu; a docstring já dizia "texto no disco decide", e não
    # era o texto que decidia. Medido em 2026-08-03.
    n_com_texto = acervo_texto.docs_com_conteudo(pasta) if txt.exists() else 0
    minimo = max(1, int(len(docs) * 0.6))
    ok = bool(docs) and n_com_texto >= minimo
    veto = bool(manifest.get("captura_vazia") or manifest.get("captura_completa") is False)
    # BANDEIRA DESMENTIDA PELO DISCO é dado velho, não veto. Medido em 2026-08-04: **17
    # processos** carregavam `captura_vazia=True` ou `captura_completa=False` tendo 100% dos
    # documentos com teor — 155 de 155, 136 de 136, 247 de 247. A marca foi posta por uma
    # captura que falhou, uma captura POSTERIOR deu certo, e ninguém a limpou; o efeito era
    # NAO_AVALIAVEL perpétuo, ou seja, a casa se recusando a afirmar sobre processo que leu
    # inteiro. A própria docstring aqui sempre disse que o texto no disco decide.
    # O veto segue valendo quando o disco NÃO desmente — é o caso dos outros 149.
    veto_obsoleto = veto and ok
    if veto and not veto_obsoleto:
        ok = False
    return ok, {"n_docs": len(docs), "n_txt": n_txt, "n_com_texto": n_com_texto,
                "minimo": minimo, "veto_manifest": veto,
                "veto_obsoleto": veto_obsoleto}
