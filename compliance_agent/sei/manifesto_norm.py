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
import re
from pathlib import Path

from compliance_agent.sei import acervo_texto, fases

_BASE = acervo_texto.RAIZ

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
    pasta = _BASE / acervo_texto.numero_para_pasta(numero_sei)
    man = acervo_texto.manifesto(pasta)
    if man is None:
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


_RE_NUM_TITULO = re.compile(r"\((\d{7,10})\)\s*$")
_RE_NUM_SOLTO = re.compile(r"(?<!\d)(\d{7,10})(?!\d)")


def numero_sei_do_titulo(titulo: str) -> str:
    """O nº SEI do documento que a árvore põe no título ("Despacho … (121323702)"); "" se não houver."""
    t = str(titulo or "")
    m = _RE_NUM_TITULO.search(t)
    if m:
        return m.group(1)
    soltos = _RE_NUM_SOLTO.findall(t)
    return soltos[-1] if soltos else ""


def _inteiro(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def tamanho_da_arvore(manifest: dict) -> int | None:
    """Quantos documentos DESTE processo a árvore do SEI tem, pelo que o manifesto mediu; None = não medido.

    Dois nomes para o mesmo fato: `total_arvore` (captura da íntegra) e `docs_na_arvore` (arquivo montado do cache
    do sweep) — vale o maior. As peças de OUTRO processo que a íntegra trouxe e o arquivo tirou (`alheios_fora` do
    `sei_arquivar`, `descontaminado.removidos` do `sei_descontaminar`) saem da conta: senão o processo descontaminado
    ficava "incompleto" para sempre e voltava à recaptura eterna."""
    arvore = max(_inteiro(manifest.get("total_arvore")), _inteiro(manifest.get("docs_na_arvore")))
    if arvore <= 0:
        return None
    desc = manifest.get("descontaminado")
    fora = _inteiro(manifest.get("alheios_fora")) + (_inteiro(desc.get("removidos")) if isinstance(desc, dict) else 0)
    return max(0, arvore - fora)


def _tem_foto(doc: dict) -> bool:
    f = doc.get("fotos")
    return bool(f) and str(f).strip() not in ("[]", "")


def motivo_falta(pasta: Path, doc: dict) -> str | None:
    """Por que ESTE documento não veio — ou None se veio (texto com teor no disco, ou página de imagem guardada).

    As quatro marcas de "não veio" que os escritores usam viram um motivo só cada: `nao_capturado` (a captura não
    trouxe), `declarado_sem_teor`, `sem_conteudo` (PDF sem texto e sem imagem), e o que nenhuma marca diz mas o disco
    mostra — `so_etiqueta` (o .txt só tem o rótulo que nós escrevemos) e `sem_texto` (nenhum .txt declarado)."""
    for marca in ("nao_capturado", "declarado_sem_teor", "sem_conteudo"):
        if str(doc.get(marca) or "").lower() in ("true", "1"):
            return marca
    rel = doc.get("texto")
    if rel and acervo_texto.tem_conteudo(pasta / rel):
        return None
    if _tem_foto(doc):
        return None                         # documento-imagem (fotografia, escaneado sem OCR): o teor é a imagem
    return "so_etiqueta" if rel and (pasta / rel).exists() else "sem_texto"


def conferir_documentos(pasta: Path | str, manifest: dict | None = None) -> dict:
    """CADA documento da árvore veio? A régua ÚNICA de "captura completa" do acervo.

    Pedido do dono (20/11/2026): "checar se a íntegra baixada tem todos os documentos mencionados individualmente".
    Até aqui havia 13 réguas divergentes (limiares de 40/50/80/200 bytes e 500 chars, `total_arvore` × `docs_na_arvore`,
    60% por arquivo em disco); esta responde documento a documento e as outras passam a derivar daqui.

    Devolve `medido` (a árvore tem tamanho conhecido), `total_arvore` (já sem peças alheias), `n_docs`, `vieram`,
    `com_texto` (vieram COM texto — o que a leitura usa), `docs_faltantes` [{i, id_documento, numero_sei, titulo,
    motivo}], `faltam_sem_identificacao` (a árvore é maior que o manifesto e o manifesto não diz quais) e
    `captura_completa` — True SÓ com árvore medida, todo documento presente e nenhum faltando sem identificação."""
    pasta = Path(pasta)
    man = manifest if manifest is not None else acervo_texto.manifesto(pasta)
    if not isinstance(man, dict):
        return {"medido": False, "motivo": "sem manifest legível", "total_arvore": None, "n_docs": 0,
                "vieram": 0, "com_texto": 0, "docs_faltantes": [], "faltam_sem_identificacao": 0,
                "captura_completa": False}
    docs = [d for d in (man.get("docs") or []) if isinstance(d, dict)]
    arvore = tamanho_da_arvore(man)
    faltantes, vieram, com_texto = [], 0, 0
    for d in docs:
        motivo = motivo_falta(pasta, d)
        if motivo is None:
            vieram += 1
            rel = d.get("texto")
            com_texto += bool(rel and acervo_texto.tem_conteudo(pasta / rel))
            continue
        faltantes.append({"i": d.get("i"), "id_documento": str(d.get("id_documento") or ""),
                          "numero_sei": numero_sei_do_titulo(d.get("titulo")),
                          "titulo": str(d.get("titulo") or ""), "motivo": motivo})
    if not docs:
        # ÍNDICE QUEBRADO (`docs: []` com `texto/*.txt` intacto — o que `sei_reparar_manifestos` conserta): o diretório
        # é a melhor evidência do que veio (`acervo_texto.declarados`), mas sem índice nada é "completo".
        com_texto = vieram = acervo_texto.docs_com_conteudo(pasta)
    sem_ident = max(0, arvore - len(docs)) if arvore is not None else 0
    return {"medido": arvore is not None, "total_arvore": arvore, "n_docs": len(docs), "vieram": vieram,
            "com_texto": com_texto, "docs_faltantes": faltantes, "faltam_sem_identificacao": sem_ident,
            "captura_completa": bool(arvore is not None and docs and not faltantes and sem_ident == 0)}


def captura_integra(manifest: dict, pasta: Path | str | None = None) -> tuple[bool, dict]:
    """(íntegra?, evidência). Texto no disco decide; etiquetas do manifest só vetam.

    O tamanho da árvore vem de `conferir_documentos` (régua única); o texto, dos documentos que o manifesto EM DISCO
    declara (`acervo_texto.docs_com_conteudo`). O que é só desta função é o LIMIAR de avaliabilidade (60% com
    texto) — não é outra régua de "completo"."""
    docs = [d for d in (manifest.get("docs") or []) if isinstance(d, dict)]
    pasta = Path(pasta or manifest.get("_pasta") or "")
    txt = pasta / "texto"
    n_txt = len(list(txt.glob("*"))) if txt.exists() else 0
    conf = conferir_documentos(pasta, manifest)
    # CONTAR ARQUIVO NÃO É CONTAR TEXTO. 10.332 dos 45.161 arquivos do acervo (22,9%) trazem só a
    # etiqueta `[título] (fase: … · tipo: …)` que nós mesmos escrevemos — zero conteúdo. Contando
    # arquivos, 7 processos passavam por ÍNTEGROS com quase metade dos textos vazios e recebiam
    # faixa de risco sobre o que não se leu; a docstring já dizia "texto no disco decide", e não
    # era o texto que decidia. Medido em 2026-08-03.
    n_com_texto = acervo_texto.docs_com_conteudo(pasta) if txt.exists() else 0
    minimo = max(1, int(len(docs) * 0.6))
    ok = bool(docs) and n_com_texto >= minimo
    # TETO DE COLETA: 40 documentos exatos, e nada acima. Medido em 2026-08-05 sobre o acervo
    # inteiro — dos **1.902 arquivos montados a partir do CACHE do sweep, 176 param em exatamente
    # 40 documentos e ZERO passa de 40** (31 em 39, 11 em 38, e depois o muro). Nos 274 montados
    # por outro caminho não há muro nenhum: 2 em 40, 1 em 41, 1 em 42, 1 em 43. É a assinatura de
    # contagem redonda que a casa já conhece — o corte `documentos[:40]` que existia no sweep e
    # hoje não existe mais no código, mas continua CONGELADO nesses arquivos.
    #
    # Este gate mede densidade de TEXTO: 40 de 40 documentos com teor = "li tudo o que capturei".
    # Só que a pergunta é outra — "capturei tudo?" — e sobre esses 176 a resposta é não. Eles
    # sustentavam **134 acusações de AUSÊNCIA** (63 de pagamento sem evidência de execução, 25 de
    # planejamento, 22 de formalização, 12 de seleção, 12 de art. 53) e **14 dos 28 processos
    # EXTREMO do acervo**. Ausência afirmada sobre captura truncada é a família 20 do catálogo.
    #
    # `tools/sei_sweep._arquivo_incompleto` usa esta MESMA função, então marcá-los aqui os devolve
    # à fila de recaptura — não é só deixar de acusar, é ir buscar o que falta.
    do_cache = "CACHE do sweep" in str(manifest.get("aviso") or "")
    # O FATO ACIMA DA HEURÍSTICA. Contar 40 é reconhecer a assinatura do corte, não medi-lo — e a
    # heurística erra nos dois sentidos. Medido em 2026-08-07 sobre os 198 arquivos parados em 40:
    # **171 estão de fato truncados** (o maior tem 40 de 956 documentos) e **21 têm árvore de
    # exatamente 40**, ou seja, estão COMPLETOS e vinham sendo excluídos da análise por causa do
    # número redondo. Os outros 6 não têm cache legível.
    #
    # Quem arquiva sabe o tamanho da árvore: está em `documentos` no próprio cache que ele lê.
    # `docs_na_arvore` grava esse fato no manifesto, e aqui ele MANDA quando existe — a heurística
    # do 40 fica só para os manifestos legados, que não têm o campo.
    # `conferir_documentos.total_arvore` = o maior de `total_arvore`/`docs_na_arvore`, sem as peças alheias tiradas.
    na_arvore = conf["total_arvore"]
    if isinstance(na_arvore, int) and na_arvore > 0:
        teto_de_coleta = len(docs) < na_arvore
    else:
        teto_de_coleta = do_cache and len(docs) == 40
    veto = bool(manifest.get("captura_vazia") or manifest.get("captura_completa") is False
                or teto_de_coleta)
    # BANDEIRA DESMENTIDA PELO DISCO é dado velho, não veto. Medido em 2026-08-04: **17
    # processos** carregavam `captura_vazia=True` ou `captura_completa=False` tendo 100% dos
    # documentos com teor — 155 de 155, 136 de 136, 247 de 247. A marca foi posta por uma
    # captura que falhou, uma captura POSTERIOR deu certo, e ninguém a limpou; o efeito era
    # NAO_AVALIAVEL perpétuo, ou seja, a casa se recusando a afirmar sobre processo que leu
    # inteiro. A própria docstring aqui sempre disse que o texto no disco decide.
    # O veto segue valendo quando o disco NÃO desmente — é o caso dos outros 149.
    # o teto de coleta NÃO é bandeira velha: o disco confirma os 40 textos justamente porque os 40
    # são tudo o que se capturou. Só a bandeira do manifesto pode ser desmentida pelo disco.
    veto_obsoleto = veto and ok and not teto_de_coleta
    if veto and not veto_obsoleto:
        ok = False
    return ok, {"n_docs": len(docs), "n_txt": n_txt, "n_com_texto": n_com_texto,
                "minimo": minimo, "veto_manifest": veto,
                "veto_obsoleto": veto_obsoleto, "teto_de_coleta": teto_de_coleta,
                # o TAMANHO DO BURACO viaja com o veredito: "40 de 956" é outra conversa que
                # "40 de 40", e quem lê a cobertura precisa dessa diferença para priorizar.
                "docs_na_arvore": na_arvore if isinstance(na_arvore, int) else None,
                "faltam_capturar": (max(0, na_arvore - len(docs))
                                    if isinstance(na_arvore, int) and na_arvore > 0 else None)}
