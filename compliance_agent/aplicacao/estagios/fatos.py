# -*- coding: utf-8 -*-
"""E8 `fatos` — fatos do processo com CITAÇÃO LITERAL CONFERIDA (plano mestre v2 §3.2 E8, §6 "E8 destravado"; O6.3).

Entrada: o texto do processo mudou (`fatos:<processo>`). Saída e efeito: fatos com citação literal conferida —
documento, versão (sha256 do texto), página, offset — e a COBERTURA do processo, com `pecas_nao_lidas[]` e o motivo de
cada peça. Absorve `leitura_integral` (reaproveitado, não reescrito) e, depois, `sei_ficha`.

O que vem do `leitura_integral` (sem mudar nada lá):
  · a PORTA (`portao`: captura declarada completa, sem documento faltando, OCR confirmado) e o FATIADOR (`fatiar`: 100%
    do texto na ordem da árvore, documento grande dividido por parágrafo com sobreposição, tabela lida por CÓDIGO,
    OCR pendente e documento já lido FORA — tudo declarado na cobertura);
  · o prompt `SISTEMA` e a sua versão (`VERSAO_PROMPT` = li-2): mesmo prompt ⇒ documento que o piloto já leu com o
    mesmo modelo NÃO é relido (`docs_lidos`, pelo sha do documento);
  · a conferência do VALOR dentro da citação (`verificar`, inclusive data por extenso).

O que o E8 acrescenta:
  1. FATIAS de 8–16k tokens: `ALVO_CHARS` = 26.000 caracteres. A estimativa da casa é 2,5 car./token (`claude_api.
     _tokens_aprox` ⇒ ~10,4k) e o real medido ficou até 1,5× acima (`leitura_integral.FATOR_REAL` ⇒ ~15,6k): as duas
     pontas dentro da faixa — abaixo de ~32k o recall não despenca (NoLiMa/ICML 2025);
  2. MÁSCARA antes do envio (`dominio/mascara`, modo estrito do gateway) e recusa se sobrar CPF com DV válido;
  3. ÂNCORA: a citação do modelo é procurada no texto ORIGINAL do documento citado (espaços flexíveis, nada mais) e
     o que se grava é `texto[inicio:fim]` — substring exata por construção, com `doc_sha`, `pagina` (1 + quebras de
     página `\\f` antes do início; documento sem `\\f` é uma página só) e `inicio`/`fim`. Citação que não ancora, que
     cita documento fora da fatia ou cujo valor não está nela ⇒ `INDETERMINADO_FALHA_CITACAO` (gravada com o motivo,
     nunca vira número);
  4. `_MIN_CITACAO` do E8 (medido em 24/11/2026 sobre os 124.381 fatos aceitos do piloto, relatório
     ~/vault/refatoracao/o63-e8.md §3): citação aceita só com ≥ 25 caracteres (normalizados) OU com um número exato
     (≥ 2 dígitos); a curta com número grava também ±40 caracteres de contexto do documento. A régua global
     `llm/verificacao._MIN_CITACAO = 8` NÃO muda (tem outros consumidores, não medidos);
  5. IDEMPOTÊNCIA pela chave (processo, sha do texto, prompt_version, modelo): fatia = sha256(processo|sha da fatia
     mascarada|prompt|modelo) — reexecução apaga e regrava só aquela chave; processo = sha256(processo|sha do texto
     elegível|prompt|modelo) — mesma chave já concluída ⇒ nada é lido de novo. "Texto elegível" exclui as peças que
     esperam (OCR não confirmado, tabela sem leitor): quando uma delas fica pronta a chave muda e SÓ ela é lida;
  6. ORDEM ÚNICA (`ordem`): OB PAGA (régua canônica `dominio.pagamento.ob_paga_sql` = `_ob_paga`) maior antes e cota
     Couto de 50% (OB paga emitida a partir de `governo_couto.INICIO`) por `fluxo.prioridade.ordenar` — nunca a posição
     na árvore (lição "quais 40").

Onde grava (ADR-001 D3): PostgreSQL `jfn_evidencias`, nas tabelas que o piloto já criou (`fatos`, `leituras`,
`docs_lidos`, `tabelas_lidas` — esquema `public`, 133.750 fatos em 24/11/2026), EVOLUÍDAS por
`deploy/vm2/postgres/fatos_001.sql` (só colunas novas; nada renomeado). Nunca escreve no `compliance.db`; a ordem lê a
coleta (SIAFE) em modo só-leitura imutável (snapshot da parada de obras).

LLM: o leitor é injetável. Padrão = ASSINATURA pelo gateway (`adaptadores/llm/gateway.chamar`, camada 2 só, com trace)
e só se o ritmo deixar: `fluxo.ritmo.motivo` (medição no PG, porta fechada sem ela) e `contingencia.motivo_bloqueio`;
ritmo "contido" ⇒ não chama (`SemCota`, o job volta com backoff; as fatias feitas ficam). O BATCH Haiku (`lote
enviar|colher`) imprime a estimativa ANTES (preço oficial de `config/llm_precos.yaml`), recusa acima do teto pedido,
confere o teto mensal do gateway (US$ 100, corte a 85%) e passa pelo livro-caixa do `claude_api` (baldes, teto do ciclo).

Efeito conferido (`efeito`, outro processo): a leitura do processo está no PG com a chave declarada, os fatos das
fatias declaradas foram recontados = declarados, e uma amostra de até 20 fatos VERIFICADOS foi reaberta no ACERVO:
sha256 do documento = `doc_sha` e `texto[inicio:fim]` = `citacao`.

CLI:
    python -m compliance_agent.aplicacao.estagios.fatos schema aplicar|verificar
    python -m compliance_agent.aplicacao.estagios.fatos ordem [--limite N] [--fonte <compliance.db só-leitura>]
    python -m compliance_agent.aplicacao.estagios.fatos projetar [--fonte …] [--saida arq.json]    # não gasta
    python -m compliance_agent.aplicacao.estagios.fatos ler --processo 020001/000354/2025           # assinatura
    python -m compliance_agent.aplicacao.estagios.fatos lote enviar --processos arq.txt --teto-usd 2 [--enviar]
    python -m compliance_agent.aplicacao.estagios.fatos lote colher
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from compliance_agent import evidencias as EV
from compliance_agent import leitura_integral as LI
from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.dominio import mascara as M
from compliance_agent.fluxo.fila import Adiado, Resultado
from compliance_agent.llm.verificacao import _normal
from compliance_agent.fluxo import fonte_coleta

VERSAO = "e8-1"                                  # lógica do estágio (âncora, régua da citação, chaves)
PROMPT_VERSION = LI.VERSAO_PROMPT                # li-2: o MESMO prompt do piloto (`LI.SISTEMA`)
SISTEMA = LI.SISTEMA
MODELO = "claude-haiku-5-5"                      # = claude_api.MODELO_BARATO (conferido no teste)
TAREFA = LI.TAREFA                               # "leitura_integral": política do gateway e balde do claude_api
ESTAGIO_NOME = "fatos"
ALVO_CHARS = 26_000
SOBREPOSICAO = LI.SOBREPOSICAO
MAX_TOKENS_SAIDA = 8000                          # 4000 cortou 11% no piloto li-1
MIN_CITACAO = 25
CONTEXTO_NUMERO = 40
AMOSTRA_EFEITO = 20
VERIFICADO = "VERIFICADO"
FALHA_CITACAO = "INDETERMINADO_FALHA_CITACAO"
FORA_DA_PORTA = "fora_da_porta"
MOTIVO_JSON_INVALIDO = "resposta do modelo inválida (JSON)"   # peça não lida: a fatia dela é relida na reexecução
ESQUEMA_PADRAO = "public"                        # onde as tabelas do piloto moram (medido 24/11/2026)
ENV_ESQUEMA = "JFN_FATOS_ESQUEMA"
RAIZ = Path(__file__).resolve().parents[3]
SQL_SCHEMA = RAIZ / "deploy" / "vm2" / "postgres" / "fatos_001.sql"
DIR_LOTES = RAIZ / "data" / "leitura_integral" / "e8"      # mapa da máscara: SÓ local (pasta no .gitignore)
FONTE_PARADA = Path.home() / "snapshot-20261124" / "compliance.db"
ENV_FONTE = "JFN_FATOS_FONTE"
_RX_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_RX_NUMERO = re.compile(r"\d(?:[\d.,/\-]*\d)?")


def versao_chave(prompt_version: str = PROMPT_VERSION, modelo: str = MODELO) -> str:
    """`leituras.versao`/`docs_lidos.versao` do E8 = prompt + modelo (a PK antiga é (sha, versao): o modelo entra no
    texto da versão, sem trocar a chave primária)."""
    return f"{prompt_version}|{modelo}"


def versoes_lidas(prompt_version: str = PROMPT_VERSION, modelo: str = MODELO) -> list[str]:
    """Versões de `docs_lidos` que valem como "este documento já foi lido com este prompt e este modelo". O piloto
    gravou 'li-2' sem o modelo; medido em 24/11/2026: os 133.750 fatos do piloto têm `motor = claude-haiku-5-5` (todos
    os lotes colhidos) — então 'li-2' ≡ 'li-2|claude-haiku-5-5'."""
    v = [versao_chave(prompt_version, modelo)]
    if prompt_version == "li-2" and modelo == "claude-haiku-5-5":
        v.append("li-2")
    return v


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def chave_fatia(processo: str, texto_mascarado: str, prompt_version: str = PROMPT_VERSION,
                modelo: str = MODELO) -> str:
    return _sha(f"{processo}|{_sha(texto_mascarado)}|{prompt_version}|{modelo}")


def chave_processo(processo: str, texto_sha: str, prompt_version: str = PROMPT_VERSION, modelo: str = MODELO) -> str:
    return _sha(f"{processo}|{texto_sha}|{prompt_version}|{modelo}")


class SemCota(Adiado):         # espera conhecida: volta sem gastar tentativa (fila.adiar)
    """O leitor não pôde ler agora (ritmo/teto/assinatura): o job tenta de novo com backoff; nada foi marcado como lido."""


# ══ 1. citação: régua, âncora e conferência ════════════════════════════════════════════════════════════════════
def citacao_suficiente(trecho: str) -> bool:
    """A régua do E8: ≥ `MIN_CITACAO` caracteres normalizados OU um número exato (token com ≥ 2 dígitos)."""
    c = _normal(trecho)
    if len(c) >= MIN_CITACAO:
        return True
    return any(len(re.sub(r"\D", "", m[0])) >= 2 for m in _RX_NUMERO.finditer(c))


def localizar(citacao: str, texto: str) -> tuple[int, int] | None:
    """(inicio, fim) da 1ª ocorrência da citação no texto, tolerando SÓ a diferença de espaços (quebra de linha,
    tabulação, espaço duplo). Nenhuma outra normalização: caixa, acento e pontuação têm de bater."""
    partes = (citacao or "").split()
    if not partes:
        return None
    m = re.search(r"\s+".join(re.escape(p) for p in partes), texto or "")
    return (m.start(), m.end()) if m else None


def pagina_de(texto: str, inicio: int) -> int:
    return texto.count("\f", 0, inicio) + 1


def ancorar(fato: dict, docs: dict[str, dict], mapa: dict) -> dict:
    """Fato do modelo → linha de `fatos`. `docs` = {doc_id: documento ORIGINAL (texto, sha)} da fatia; `mapa` = mapa
    da máscara da fatia (a citação volta desmascarada antes de ser procurada no original)."""
    doc_id = str(fato.get("doc_id") or "")
    valor = M.desmascarar(str(fato.get("valor") or ""), mapa)
    citado = M.desmascarar(str(fato.get("citacao") or ""), mapa)
    base = {"doc_id": doc_id or "?", "tipo": fato.get("tipo"), "valor": valor,
            "descricao": M.desmascarar(str(fato.get("descricao") or ""), mapa)[:500], "citacao": citado[:1000],
            "doc_sha": None, "pagina": None, "inicio": None, "fim": None, "contexto": None}

    def falha(motivo: str) -> dict:
        return {**base, "estado": FALHA_CITACAO, "motivo": motivo}

    if not citado.strip():
        return falha("sem citação")
    d = docs.get(doc_id)
    if d is None:
        return falha(f"documento {doc_id!r} não está na fatia")
    span = localizar(citado, d["texto"])
    if span is None:
        return falha("citação não existe no documento")
    ini, fim = span
    trecho = d["texto"][ini:fim]
    if not citacao_suficiente(trecho):
        return falha(f"citação curta (< {MIN_CITACAO} caracteres) sem número exato")
    conf = LI.verificar({"citacao": trecho, "doc_id": "d", "valor": valor, "tipo": fato.get("tipo")}, {"d": trecho})
    if conf["estado"] != VERIFICADO:
        return falha(conf["motivo"] or "valor não conferido")
    curta = len(_normal(trecho)) < MIN_CITACAO
    return {**base, "citacao": trecho, "doc_sha": d["sha"], "pagina": pagina_de(d["texto"], ini), "inicio": ini,
            "fim": fim, "estado": VERIFICADO, "motivo": None,
            "contexto": d["texto"][max(0, ini - CONTEXTO_NUMERO): fim + CONTEXTO_NUMERO] if curta else None}


def interpretar(resposta: str | None, docs: dict[str, dict], mapa: dict) -> list[dict] | None:
    """Resposta do modelo → fatos ancorados. JSON inválido ⇒ None (falha de leitura, NÃO "sem fatos")."""
    m = re.search(r"\{.*\}", resposta or "", re.S)
    try:
        dados = json.loads(m[0]) if m else None
    except ValueError:
        dados = None
    if not isinstance(dados, dict) or not isinstance(dados.get("fatos"), list):
        return None
    return [ancorar(f, docs, mapa) for f in dados["fatos"] if isinstance(f, dict)]


# ══ 2. preparo do processo (porta, fatias, máscara, chaves, cobertura) ═════════════════════════════════════════
@dataclass
class Fatia:
    idx: int
    texto: str                      # MASCARADO — é o que sai da VM
    mapa: dict
    chave: str
    docs: dict[str, dict]           # doc_id → documento original completo (para a âncora)
    shas: list[tuple[str, str]]     # (sha, doc_id) dos documentos desta fatia (vão a docs_lidos)


@dataclass
class Preparo:
    processo: str
    pasta: Path
    fora_da_porta: str | None = None
    texto_sha: str = ""
    chave: str = ""
    fatias: list[Fatia] = field(default_factory=list)
    cobertura: dict = field(default_factory=dict)
    pecas_nao_lidas: list[dict] = field(default_factory=list)
    fonte_texto: str = ""
    reusos: list[dict] = field(default_factory=list)      # documentos cujo texto não foi lido aqui (fatos copiados)
    meta: dict = field(default_factory=dict)              # sha → (texto_sha, cabeça, corte, chars) do que foi lido


def pasta_do(processo: str) -> Path:
    return EV.ARQUIVO / processo.replace("SEI-", "").replace("/", "_")


# ── 2a. a FONTE do texto e a PORTA: a saída do E4/E5 e a confirmação do E6 (O8.5, frente B1) ─────────────────────
# O ensaio O8.5 (25/11/2026) mediu duas quebras: a porta lia a confirmação de OCR do LEGADO (`sei/ocr_confirmacao`,
# `data/sei_ocr_confirmacao.jsonl`) e barrou 7 dos 9 processos que o E6 tinha conferido; e o texto vinha de
# `data/sei_arquivo` (legado), não do E4/E5. Agora, quando o PG da captura tem o processo (documentos do E2/E3), o
# texto é o que o E4 (nativo) e o E5 (OCR) GRAVARAM — `transformacao` + lateral conferido pelo sha256 — e o OCR só
# entra com `ocr_conferencia.estado = 'confirmado'` do E6 para o MESMO texto (processo, doc_id, sha256 da saída do
# E5). `a_conferir`, sem conferência, conferência de outra versão do texto ou página escaneada sem saída do E5: a
# porta barra o processo e declara cada documento. O legado só entra quando o estágio não tem saída para o processo
# (declarado em `fonte_texto`, e contado no efeito).
FONTE_ESTAGIO = "estagio"
FONTE_LEGADO = "legado"


@dataclass
class Acervo:
    fonte: str                                   # FONTE_ESTAGIO | "legado: <por quê>"
    fora_da_porta: str | None
    docs: list[dict] = field(default_factory=list)          # formato de `LI._docs` (+ `ocr_confirmado` no estágio)
    pendencias: list[dict] = field(default_factory=list)    # [{doc_id, motivo}] do que barrou a porta


def _caminho_gravado(rel: str | None) -> Path | None:
    if not rel:
        return None
    p = Path(rel)
    return p if p.is_absolute() else RAIZ / p


def _texto_gravado(tr: dict, etapa: str) -> tuple[str | None, str]:
    """(texto, '') do lateral que o estágio GRAVOU na `transformacao`, conferido: sha256 do arquivo = o gravado e
    sha256 do texto composto = `saida_sha`. Senão (None, motivo) — nunca outro texto no lugar."""
    from compliance_agent.aplicacao.estagios import texto as T
    par = tr.get("parametros") or {}
    p = _caminho_gravado(par.get("lateral"))
    lat = T.ler_lateral(p) if p else None
    if lat is None:
        return None, f"lateral do {etapa} ausente ou ilegível"
    if lat[1] != par.get("lateral_sha"):
        return None, f"lateral do {etapa} não confere com o sha256 gravado no PG"
    if etapa == "E5":
        if lat[0].get("compostas") is None:
            return None, "lateral do E5 sem as páginas compostas"
        texto = T.QUEBRA.join(lat[0]["compostas"])
    else:
        texto = T.texto_composto(lat[0])
    if T.sha256_texto(texto) != tr.get("saida_sha"):
        return None, f"texto do {etapa} não confere com a saída gravada no PG"
    from compliance_agent.fluxo import leituras
    leituras.anotar("texto", _sha(texto.strip()), documento=str(p.name))
    return texto, ""


CABECA = 2048                                    # início do texto guardado em docs_lidos (decide o rótulo sem reler)


def normalizar_texto(bruto: str, titulo: str) -> tuple[str, str, int]:
    """O texto como o leitor do piloto o lê (`acervo_texto.ler`): fim de linha universal (o `read_text` do legado
    troca \r e \r\n por \n) e `sem_etiqueta` (o PDF do SEI abre com o rótulo "[<título>]"). Medido no O8.5 (rb1):
    sem isso 121 de 338 textos do E4 diferiam do que o leitor antigo leria (105 pelo rótulo, 16 pelo \r).
    Devolve (texto, cabeça, corte): `cabeça` = o início do texto de fim de linha universal e `corte` = quantos
    caracteres do início a normalização tirou — o rótulo depende do TÍTULO, e é por eles que outro documento com o
    MESMO texto de saída prova ter o mesmo texto normalizado sem abrir o arquivo (`corte_de`)."""
    from compliance_agent.sei.acervo_texto import sem_etiqueta
    u = bruto.replace("\r\n", "\n").replace("\r", "\n")
    sem = sem_etiqueta(u, str(titulo or ""))
    return sem.strip(), u[:CABECA], len(u) - len(sem.lstrip())


def corte_de(cabeca: str, titulo: str) -> int | None:
    """O `corte` que `normalizar_texto` daria ao texto que começa com `cabeca`, sob este título — ou None quando a
    cabeça não basta para decidir (texto maior que ela sem 3 linhas completas não vazias: o rótulo ocupa no máximo
    as 2 primeiras linhas e a 3ª prova onde o conteúdo começa)."""
    from compliance_agent.sei.acervo_texto import sem_etiqueta
    if len(cabeca) >= CABECA and sum(1 for ln in cabeca.split("\n")[:-1] if ln.strip()) < 3:
        return None
    return len(cabeca) - len(sem_etiqueta(cabeca, str(titulo or "")).lstrip())


def acervo_do_estagio(con_cap, processo: str, textos_lidos: dict | None = None) -> Acervo | None:
    """O processo pela saída do E3/E4/E5/E6 no PG da captura. None = o estágio não tem o processo (volta ao legado).
    A decisão da porta usa SÓ o PG; os laterais (o texto) só são lidos quando a porta abre.
    LEITURA ÚNICA por texto (regra do dono: cada sha256 lido no máximo 1× por estágio × prompt_version): o mesmo
    texto de saída do E4/E5 (`saida_sha`) em dois documentos do processo é aberto UMA vez; e, com `textos_lidos`
    (`textos_ja_lidos`: saida_sha → linha de `docs_lidos`), o texto que o modelo JÁ leu nesta versão do prompt nem é
    aberto — o documento entra sem `texto`, com o sha e o tamanho gravados e `reuso` = de onde vêm os fatos."""
    from compliance_agent.aplicacao.estagios import texto as T
    docs = con_cap.execute("SELECT doc_id, posicao, titulo FROM documentos WHERE processo = %s ORDER BY posicao, "
                           "doc_id", (processo,)).fetchall()
    if not docs:
        return None
    e3 = con_cap.execute("SELECT detalhe->'omitidos' FROM aquisicao WHERE fonte = 'sei:e3' AND detalhe->>'processo' "
                         "= %s ORDER BY concluida_em DESC NULLS LAST, criada_em DESC LIMIT 1", (processo,)).fetchone()
    if e3 is None:
        return Acervo(FONTE_ESTAGIO, "captura não declarada completa", pendencias=[
            {"doc_id": "*", "motivo": "sem aquisição do E3 para o processo"}])
    pend: list[dict] = [{"doc_id": str(o.get("doc_id") or o.get("i")), "motivo": "omitido na captura do E3"}
                        for o in (e3[0] or []) if isinstance(o, dict)]
    alvos = []                                   # (doc_id, posicao, titulo, e4, e5, ocr, confirmado)
    for doc_id, pos, titulo in docs:
        b = con_cap.execute("SELECT sha256 FROM versoes WHERE processo = %s AND doc_id = %s AND hash_de = 'binario' "
                            "ORDER BY vista_em DESC, sha256 LIMIT 1", (processo, doc_id)).fetchone()
        if b is None:
            pend.append({"doc_id": doc_id, "motivo": "sem versão binária do E3"})
            continue
        e4 = T.transformacao_de(con_cap, processo, doc_id, T.TIPO_TRANSFORMACAO, b[0])
        e5 = T.transformacao_de(con_cap, processo, doc_id, "ocr", b[0])
        par4 = (e4 or {}).get("parametros") or {}
        escaneada = any(len(x) > 1 and x[1] == T.ESCANEADA for x in par4.get("paginas") or [])
        ocr, conf = e5 is not None or escaneada, False
        if e5 is not None:
            r = con_cap.execute("SELECT estado FROM ocr_conferencia WHERE processo = %s AND doc_id = %s AND "
                                "texto_sha = %s", (processo, doc_id, e5["saida_sha"])).fetchone()
            conf = r is not None and r[0] == "confirmado"
            # 27/11/2026: «a_conferir» é DECISÃO do E6 (número sem confirmação nível A), não espera — barrar o
            # processo inteiro deixava 518 documentos travando para sempre a leitura dos seus processos. O documento
            # segue SEM ser enviado (o fatiador o separa: `ocr_confirmado` False ⇒ peça não lida, com o motivo) e o
            # resto é lido; confirmado depois, o evento do E6 muda a chave e ele entra. Sem conferência = espera.
            if not conf and (r is None or r[0] != "a_conferir"):
                pend.append({"doc_id": doc_id, "motivo": "OCR ainda não confirmado pelo E6: " + (
                    f"conferência '{r[0]}'" if r else "sem conferência do E6 para este texto")})
        elif escaneada:
            pend.append({"doc_id": doc_id, "motivo": "OCR ainda não confirmado: página escaneada sem saída do E5"})
        elif e4 is None:
            pend.append({"doc_id": doc_id, "motivo": "sem texto do E4"})
        elif par4.get("perfil") == T.INVALIDA:
            pend.append({"doc_id": doc_id, "motivo": "texto inválido no E4 (pede recaptura)"})
        alvos.append((doc_id, pos, titulo, e4, e5, ocr, conf))
    if any(m["motivo"].startswith(("omitido", "sem versão binária")) for m in pend):
        return Acervo(FONTE_ESTAGIO, "documentos faltando na captura", pendencias=pend)
    if any(m["motivo"].startswith("OCR") for m in pend):
        return Acervo(FONTE_ESTAGIO, "documento de OCR ainda não confirmado", pendencias=pend)
    if pend:
        return Acervo(FONTE_ESTAGIO, "documento sem texto", pendencias=pend)
    out, quebra, memoria = [], [], {}
    for doc_id, pos, titulo, e4, e5, ocr, conf in alvos:
        tr = e5 if e5 is not None else e4
        base = {"doc_id": doc_id, "titulo": str(titulo or "").strip(), "ocr": ocr, "ocr_confirmado": conf,
                "i": str(pos), "texto_sha": tr["saida_sha"]}
        lin = (textos_lidos or {}).get(tr["saida_sha"])
        if lin is not None and lin["cabeca"] is not None and corte_de(lin["cabeca"], titulo) == lin["corte"]:
            out.append({**base, "sha": lin["sha"], "chars": lin["chars"],
                        "reuso": {"processo": lin["processo"], "doc_id": lin["doc_id"]}})
            continue
        if tr["saida_sha"] in memoria:
            texto, motivo = memoria[tr["saida_sha"]], ""
        else:
            texto, motivo = _texto_gravado(e5, "E5") if e5 is not None else _texto_gravado(e4, "E4")
            if texto is not None:
                memoria[tr["saida_sha"]] = texto
        if texto is None:
            quebra.append({"doc_id": doc_id, "motivo": motivo})
            continue
        texto, cabeca, corte = normalizar_texto(texto, titulo)
        if not texto:
            pend.append({"doc_id": doc_id, "motivo": "documento sem texto (E4: " + str(
                ((e4 or {}).get("parametros") or {}).get("perfil") or "?") + ")"})
            continue
        out.append({**base, "texto": texto, "sha": _sha(texto), "cabeca": cabeca, "corte": corte})
    if quebra:
        return Acervo(FONTE_ESTAGIO, "texto do estágio não confere com o PG", out, quebra)
    if pend:
        return Acervo(FONTE_ESTAGIO, "documento sem texto", out, pend)
    return Acervo(FONTE_ESTAGIO, None, out)


def acervo(processo: str, con_cap=None, textos_lidos: dict | None = None) -> Acervo:
    """A fonte única do texto do E8: o estágio (E4/E5 + E6) quando o PG da captura tem o processo; senão o legado
    (`data/sei_arquivo` + `LI.portao`), DECLARADO em `fonte`."""
    if con_cap is not None:
        a = acervo_do_estagio(con_cap, processo, textos_lidos)
        if a is not None:
            return a
        por_que = "sem saída do E2–E5 no PG para o processo"
    else:
        por_que = "sem conexão com o PG da captura"
    fonte = f"{FONTE_LEGADO}: {por_que}"
    pasta = pasta_do(processo)
    if not (pasta / "manifest.json").exists():
        return Acervo(fonte, "sem acervo capturado")
    ok, motivo = LI.portao(pasta)
    return Acervo(fonte, None, LI._docs(pasta)) if ok else Acervo(fonte, motivo)


def preparar(processo: str, ja_lidos: set[str], tabelas_lidas: set[str], *, alvo: int = ALVO_CHARS,
             prompt_version: str = PROMPT_VERSION, modelo: str = MODELO, con_cap=None,
             textos_lidos: dict | None = None) -> Preparo:
    """Tudo o que se sabe ANTES de chamar o modelo. Determinístico: mesmo acervo ⇒ mesmas fatias e mesmas chaves.
    `con_cap`: o PG da captura (texto do E4/E5 e porta pelo E6); sem ele, o legado (declarado em `fonte_texto`)."""
    pasta = pasta_do(processo)
    p = Preparo(processo=processo, pasta=pasta)
    ac = acervo(processo, con_cap, textos_lidos)
    p.fora_da_porta, p.fonte_texto = ac.fora_da_porta, ac.fonte
    if p.fora_da_porta:
        p.texto_sha = _sha(f"{FORA_DA_PORTA}:{p.fora_da_porta}")
        p.chave = chave_processo(processo, p.texto_sha, prompt_version, modelo)
        p.pecas_nao_lidas = ac.pendencias or [{"doc_id": "*", "motivo": p.fora_da_porta}]
        p.cobertura = {"chars_existentes": None, "chars_enviados": 0, "fracao": 0.0, "leitura": FORA_DA_PORTA}
        return p
    lidos = ac.docs                              # O8.5: lidos UMA vez; o fatiador recebe a mesma lista
    originais = {d["doc_id"]: d for d in lidos}
    brutas, cob = LI.fatiar(pasta, alvo=alvo, sobreposicao=SOBREPOSICAO, ja_lidos=ja_lidos,
                            tabelas_lidas=tabelas_lidas, docs=lidos)
    espera = ([{"doc_id": x, "motivo": "OCR ainda não confirmado"} for x in cob["docs_ocr_pendente"]]
              + [{"doc_id": x, "motivo": "tabela aguardando o leitor por código"} for x in cob["docs_tabela"]])
    fora = {x["doc_id"] for x in espera}
    p.texto_sha = _sha("\n".join(f"{i}:{d['sha']}" for i, d in originais.items() if i not in fora))
    p.chave = chave_processo(processo, p.texto_sha, prompt_version, modelo)
    for f in brutas:
        texto, mapa = M.mascarar(f["texto"], estrito=True)
        if M.cpfs_expostos(texto):
            raise ErroPermanente(f"{processo}: CPF com DV válido sobrou depois da máscara — nada é enviado")
        docs = {d["doc_id"]: originais[d["doc_id"]] for d in f["docs"]}
        p.fatias.append(Fatia(idx=f["id"], texto=texto, mapa=mapa, chave=chave_fatia(processo, texto, prompt_version,
                                                                                     modelo),
                              docs=docs, shas=[(d["sha"], d["doc_id"]) for d in docs.values()]))
    p.pecas_nao_lidas = espera
    p.cobertura = {k: cob[k] for k in ("chars_existentes", "chars_enviados", "fracao", "leitura")}
    # leitura única por texto: o documento que não foi às fatias por ter o MESMO texto já lido (neste processo ou
    # antes, nesta versão do prompt) recebe os fatos ancorados daquela leitura — citação, página e offset valem
    # porque o texto normalizado é o mesmo (mesmo sha); só muda o documento/processo
    enviados = {d["sha"]: d["doc_id"] for f in p.fatias for d in f.docs.values()}
    for doc_id in cob["docs_duplicados"]:
        d = originais[doc_id]
        src = d.get("reuso") or ({"processo": processo, "doc_id": enviados[d["sha"]]} if d["sha"] in enviados
                                 else None)
        p.reusos.append({"doc_id": doc_id, "sha": d["sha"], "src": src,
                         "chave": _sha(f"reuso|{processo}|{doc_id}|{d['sha']}|{prompt_version}|{modelo}")})
    p.meta = {d["sha"]: (d["texto_sha"], d["cabeca"], d["corte"], len(d["texto"])) for d in lidos if "cabeca" in d}
    return p


# ══ 3. PostgreSQL ══════════════════════════════════════════════════════════════════════════════════════════════
def esquema_vigente() -> str:
    e = os.environ.get(ENV_ESQUEMA) or ESQUEMA_PADRAO
    if not _RX_IDENT.match(e):
        raise ValueError(f"nome de esquema inválido: {e!r}")
    return e


def conectar(dsn: str | None = None, esquema: str | None = None):
    import psycopg
    dsn = dsn or EV.dsn_vigente()
    if not dsn:
        raise RuntimeError("sem DSN do PostgreSQL (JFN_EVIDENCIAS_DSN)")
    esquema = esquema or esquema_vigente()
    if not _RX_IDENT.match(esquema):
        raise ValueError(f"nome de esquema inválido: {esquema!r}")
    con = psycopg.connect(dsn, autocommit=True)
    con.execute(f'SET search_path TO "{esquema}"')
    return con


def aplicar_schema(con, esquema: str | None = None) -> None:
    esquema = esquema or esquema_vigente()
    if not _RX_IDENT.match(esquema):
        raise ValueError(f"nome de esquema inválido: {esquema!r}")
    con.execute(SQL_SCHEMA.read_text(encoding="utf-8").replace(':"esquema"', f'"{esquema}"'))
    con.execute(f'SET search_path TO "{esquema}"')
    con.execute(DDL_TEXTO_LIDO)


# O8.5 B1 (leitura única por TEXTO): `docs_lidos` ganha o sha256 do texto de SAÍDA do E4/E5 (`texto_sha`), a cabeça e o
# corte da normalização e o tamanho — o que deixa o E8 saber, sem abrir o arquivo, que outro documento com o mesmo
# texto já foi lido nesta versão do prompt. Só acrescenta (PK (sha, versao) intocada); linhas do piloto ficam NULL até
# o E8 abrir aquele texto uma vez (`registrar_textos`).
DDL_TEXTO_LIDO = ("ALTER TABLE docs_lidos ADD COLUMN IF NOT EXISTS texto_sha TEXT; "
                  "ALTER TABLE docs_lidos ADD COLUMN IF NOT EXISTS cabeca TEXT; "
                  "ALTER TABLE docs_lidos ADD COLUMN IF NOT EXISTS corte INTEGER; "
                  "ALTER TABLE docs_lidos ADD COLUMN IF NOT EXISTS chars INTEGER; "
                  "CREATE INDEX IF NOT EXISTS docs_lidos_texto_sha_ix ON docs_lidos (texto_sha, versao)")


_COLUNAS_E8 = {"fatos": ("doc_sha", "pagina", "inicio", "fim", "contexto", "chave", "estagio_versao"),
               "leituras": ("texto_sha", "modelo", "chave", "pecas_nao_lidas", "fatos_verificados", "fatos_falha")}


def verificar_schema(con) -> list[str]:
    falta = []
    for t, cols in _COLUNAS_E8.items():
        tem = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s "
                                         "AND table_schema = current_schema()", (t,))}
        falta += [f"{t}.{c}" for c in cols if c not in tem] if tem else [t]
    return falta


def ja_lidos(con, prompt_version: str = PROMPT_VERSION, modelo: str = MODELO) -> set[str]:
    return {r[0] for r in con.execute("SELECT sha FROM docs_lidos WHERE versao = ANY(%s)",
                                      (versoes_lidas(prompt_version, modelo),))}


def textos_ja_lidos(con, prompt_version: str = PROMPT_VERSION, modelo: str = MODELO) -> dict[str, dict]:
    """texto_sha (saída do E4/E5) → a 1ª leitura dele nesta versão do prompt (sha normalizado, cabeça, corte,
    tamanho e de que processo/documento vieram os fatos)."""
    out: dict[str, dict] = {}
    for ts, sha, cab, corte, chars, proc, doc in con.execute(
            "SELECT texto_sha, sha, cabeca, corte, chars, processo, doc_id FROM docs_lidos WHERE versao = ANY(%s) AND "
            "texto_sha IS NOT NULL ORDER BY em, processo, doc_id", (versoes_lidas(prompt_version, modelo),)):
        out.setdefault(ts, {"sha": sha, "cabeca": cab, "corte": corte, "chars": chars, "processo": proc,
                            "doc_id": doc})
    return out


def registrar_textos(con, p: "Preparo", lidos: set[str], prompt_version: str = PROMPT_VERSION,
                     modelo: str = MODELO) -> int:
    """O texto aberto agora cujo sha JÁ estava lido (piloto, ou outra saída do E4/E5 com o mesmo texto) ganha o
    texto_sha na linha de `docs_lidos` — sem esperar o modelo: o próximo documento com o mesmo texto não o reabre."""
    n = 0
    for sha, (ts, cab, corte, chars) in p.meta.items():
        if sha in lidos:
            n += con.execute("UPDATE docs_lidos SET texto_sha = %s, cabeca = %s, corte = %s, chars = %s WHERE sha = %s "
                             "AND versao = ANY(%s) AND texto_sha IS NULL",
                             (ts, cab, corte, chars, sha, versoes_lidas(prompt_version, modelo))).rowcount
    return n


def copiar_fatos(con, p: "Preparo", prompt_version: str = PROMPT_VERSION, modelo: str = MODELO) -> dict:
    """Os fatos ANCORADOS da leitura de origem, regravados para cada documento que reaproveitou o texto: mesmo
    doc_sha, página, offset e citação (o texto é o mesmo), outro processo/documento. Idempotente pela chave."""
    out = {"docs": len(p.reusos), "fatos_copiados": 0, "sem_fatos_ancorados": 0}
    for r in p.reusos:
        src = r["src"]
        if src is None:
            lin = con.execute("SELECT processo, doc_id FROM docs_lidos WHERE sha = %s AND versao = ANY(%s) ORDER BY em "
                              "LIMIT 1", (r["sha"], versoes_lidas(prompt_version, modelo))).fetchone()
            src = {"processo": lin[0], "doc_id": lin[1]} if lin else None
        linhas = con.execute(
            "SELECT tipo, valor, descricao, citacao, estado, motivo, motor, payload_sha, pagina, inicio, fim, contexto "
            "FROM fatos WHERE processo = %s AND doc_id = %s AND doc_sha = %s AND versao = %s AND estado = %s "
            "ORDER BY id", (src["processo"], src["doc_id"], r["sha"], prompt_version, VERIFICADO)).fetchall() \
            if src else []
        agora = EV._agora()
        with con.transaction():
            con.execute("DELETE FROM fatos WHERE chave = %s", (r["chave"],))
            con.cursor().executemany(_INS_FATO, [
                (p.processo, r["doc_id"], t, v, de, c, e, mo, mt, prompt_version, ps, agora, r["sha"], pg, ini, fim, ctx,
                 r["chave"], VERSAO) for t, v, de, c, e, mo, mt, ps, pg, ini, fim, ctx in linhas])
        out["fatos_copiados"] += len(linhas)
        out["sem_fatos_ancorados"] += not linhas
    return out


def tabelas_lidas(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT sha FROM tabelas_lidas")}


def leitura_concluida(con, processo: str, chave: str) -> bool:
    """Lida = registrada nesta chave, não fora da porta e sem fatia de JSON inválido (achado 1.13: a "parcial" por
    JSON inválido voltava `ja_lido` e a fatia nunca era relida). A "parcial" do fatiador (tabela/OCR à espera) segue
    concluída: o que falta não entra na chave e muda a chave quando chegar."""
    r = con.execute("SELECT leitura, pecas_nao_lidas FROM leituras WHERE processo = %s AND estagio = %s AND "
                    "versao = %s AND chave = %s", (processo, ESTAGIO_NOME, versao_chave(), chave)).fetchone()
    if r is None or str(r[0] or "").startswith(FORA_DA_PORTA):
        return False
    pecas = r[1] if isinstance(r[1], list) else json.loads(r[1] or "[]")
    return not any(isinstance(x, dict) and x.get("motivo") == MOTIVO_JSON_INVALIDO for x in pecas)


def fatia_gravada(con, chave: str) -> bool:
    return con.execute("SELECT 1 FROM fatos WHERE chave = %s LIMIT 1", (chave,)).fetchone() is not None


_INS_FATO = ("INSERT INTO fatos(processo, doc_id, tipo, valor, descricao, citacao, estado, motivo, motor, versao, "
             "payload_sha, em, doc_sha, pagina, inicio, fim, contexto, chave, estagio_versao) "
             "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")


def gravar_fatia(con, processo: str, fatia: Fatia, fatos: list[dict], motor: str) -> int:
    """Uma transação: apaga o que houver com a chave da fatia e grava os fatos dela (idempotente)."""
    agora = EV._agora()
    with con.transaction():
        con.execute("DELETE FROM fatos WHERE chave = %s", (fatia.chave,))
        con.cursor().executemany(_INS_FATO, [
            (processo, f["doc_id"], f.get("tipo"), f.get("valor"), f.get("descricao"), f.get("citacao"), f["estado"],
             f.get("motivo"), motor, PROMPT_VERSION, _sha(fatia.texto), agora, f.get("doc_sha"), f.get("pagina"),
             f.get("inicio"), f.get("fim"), f.get("contexto"), fatia.chave, VERSAO) for f in fatos])
    return len(fatos)


def concluir(con, p: Preparo, via: str, invalidas: list[Fatia] = ()) -> dict:
    """Registra a leitura do processo (cobertura + peças não lidas) e os documentos lidos. Fatia com resposta
    inválida: os documentos dela entram em `pecas_nao_lidas` e NÃO em `docs_lidos`."""
    pecas = list(p.pecas_nao_lidas) + [{"doc_id": d, "motivo": MOTIVO_JSON_INVALIDO}
                                       for f in invalidas for d in f.docs]
    chaves = [f.chave for f in p.fatias]
    cont = dict(con.execute("SELECT estado, count(*) FROM fatos WHERE chave = ANY(%s) GROUP BY estado",
                            (chaves,)).fetchall()) if chaves else {}
    ver, fal = int(cont.get(VERIFICADO, 0)), int(sum(v for k, v in cont.items() if k != VERIFICADO))
    leitura = (f"{FORA_DA_PORTA}: {p.fora_da_porta}" if p.fora_da_porta
               else ("parcial" if invalidas else p.cobertura.get("leitura")))
    ok_inv = {f.chave for f in invalidas}
    agora = EV._agora()
    with con.transaction():
        con.execute(
            "INSERT INTO leituras(processo, estagio, versao, chars_existentes, chars_enviados, fracao, leitura, fatias, "
            "lote, em, texto_sha, modelo, chave, pecas_nao_lidas, fatos_verificados, fatos_falha) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s) "
            "ON CONFLICT (processo, estagio, versao) DO UPDATE SET chars_existentes = excluded.chars_existentes, "
            "chars_enviados = excluded.chars_enviados, fracao = excluded.fracao, leitura = excluded.leitura, "
            "fatias = excluded.fatias, lote = excluded.lote, em = excluded.em, texto_sha = excluded.texto_sha, "
            "modelo = excluded.modelo, chave = excluded.chave, pecas_nao_lidas = excluded.pecas_nao_lidas, "
            "fatos_verificados = excluded.fatos_verificados, fatos_falha = excluded.fatos_falha",
            (p.processo, ESTAGIO_NOME, versao_chave(), p.cobertura.get("chars_existentes"),
             p.cobertura.get("chars_enviados"), p.cobertura.get("fracao"), leitura, len(p.fatias), via, agora,
             p.texto_sha, MODELO, p.chave, json.dumps(pecas, ensure_ascii=False), ver, fal))
        linhas = [(sha, versao_chave(), p.processo, doc, via, agora, *(p.meta.get(sha) or (None,) * 4))
                  for f in p.fatias if f.chave not in ok_inv for sha, doc in f.shas]
        if linhas:
            con.cursor().executemany("INSERT INTO docs_lidos(sha, versao, processo, doc_id, lote, em, texto_sha, "
                                     "cabeca, corte, chars) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO "
                                     "NOTHING", linhas)
    return {"fatos_verificados": ver, "fatos_falha": fal, "pecas_nao_lidas": len(pecas)}


# ══ 4. leitores (LLM injetável) ════════════════════════════════════════════════════════════════════════════════
@dataclass
class Leitura:
    texto: str
    motor: str                      # proveniência gravada em fatos.motor (ex.: claude-haiku-5-5@assinatura)


Leitor = Callable[[str, str], "Leitura | None"]


def motivo_assinatura(con_fluxo=None) -> str | None:
    """Por que NÃO usar a assinatura agora (None = pode): ritmo no PG (porta fechada sem medição) e a contingência
    local (ritmo semanal, limite da conta, kill-switch). "contido" ⇒ motivo."""
    from compliance_agent.fluxo import ritmo
    if con_fluxo is not None:
        m = ritmo.motivo(con_fluxo, TAREFA)
        if m:
            return m
    return ritmo.motivo_local(TAREFA)               # contingência + a exceção do dono (só no escopo do ensaio O8.5)


def leitor_assinatura(con_fluxo=None) -> Leitor:
    """Haiku pela ASSINATURA via gateway (só camada 2: nunca cai na API paga), com trace. Sem ritmo ⇒ None."""
    from compliance_agent.adaptadores.llm import gateway as G

    def ler(sistema: str, texto: str) -> Leitura | None:
        if motivo_assinatura(con_fluxo):
            return None
        try:
            r = G.chamar(TAREFA, [{"role": "system", "content": sistema}, {"role": "user", "content": texto}],
                         prompt_version=PROMPT_VERSION, modelo_pref=MODELO, classe_dado="interno",
                         max_tokens=MAX_TOKENS_SAIDA, timeout=600, so_camadas=[2])
        except (G.SemProvedor, G.OrcamentoEsgotado, G.CamadaForaDaPolitica) as e:
            print(f"fatos: assinatura não leu — {str(e)[:200]}", file=sys.stderr)
            return None
        return Leitura(texto=r.texto, motor=f"{r.modelo or MODELO}@assinatura")
    return ler


# ══ 5. o processo inteiro (handler) e a conferência (efeito) ═══════════════════════════════════════════════════
def ler_processo(con, processo: str, leitor: Leitor, via: str = "assinatura", con_cap=None) -> dict:
    lidos = ja_lidos(con)
    p = preparar(processo, lidos, tabelas_lidas(con), con_cap=con_cap, textos_lidos=textos_ja_lidos(con))
    registrar_textos(con, p, lidos)
    base = {"processo": processo, "chave": p.chave, "versao": versao_chave(), "estagio_versao": VERSAO,
            "fatias": [f.chave for f in p.fatias] + [r["chave"] for r in p.reusos], "fatias_lidas_agora": 0,
            "fatos_gravados": 0, "fonte_texto": p.fonte_texto}
    if p.fora_da_porta:
        return {**base, **concluir(con, p, via), "fora_da_porta": p.fora_da_porta, "ja_lido": False}
    if leitura_concluida(con, processo, p.chave):
        return {**base, "ja_lido": True}
    # sem fatia (tudo já lido pelo sha, ou à espera): a cobertura é registrada sem chamar o modelo. Tabela: o leitor
    # por CÓDIGO é o `leitura_integral.ler_tabelas` (à parte); até ele rodar, a peça fica em `pecas_nao_lidas`.
    invalidas: list[Fatia] = []
    for f in p.fatias:
        if fatia_gravada(con, f.chave):
            continue
        r = leitor(SISTEMA, f.texto)
        if r is None:
            raise SemCota(f"{processo}: leitor sem cota na fatia {f.idx} — {base['fatias_lidas_agora']} fatia(s) "
                          "gravada(s); o processo NÃO foi marcado como lido")
        fatos = interpretar(r.texto, f.docs, f.mapa)
        base["fatias_lidas_agora"] += 1
        if fatos is None:
            invalidas.append(f)
            continue
        gravar_fatia(con, processo, f, fatos, r.motor)
    base["reuso"] = copiar_fatos(con, p)
    base["fatos_gravados"] = int(con.execute("SELECT count(*) FROM fatos WHERE chave = ANY(%s)",
                                             (base["fatias"],)).fetchone()[0]) if p.fatias else 0
    return {**base, **concluir(con, p, via, invalidas), "ja_lido": False, "fracao": p.cobertura.get("fracao"),
            "fatias_invalidas": [f.chave for f in invalidas]}


def conferir(con, efeito: dict, amostra: int = AMOSTRA_EFEITO, con_cap=None) -> dict:
    """Conferência INDEPENDENTE do que `ler_processo` declarou (lê o PG e o acervo, não a palavra do handler). O
    texto é relido da MESMA fonte declarada (`fonte_texto`): saída do E4/E5 (`con_cap`) ou o legado."""
    proc, chave = efeito.get("processo"), efeito.get("chave")
    r = con.execute("SELECT leitura FROM leituras WHERE processo = %s AND estagio = %s AND versao = %s AND chave = %s",
                    (proc, ESTAGIO_NOME, versao_chave(), chave)).fetchone()
    out = {"leitura_no_pg": r is not None, "recontados": None, "amostra": 0, "divergentes": []}
    if efeito.get("fora_da_porta"):
        out["motivo"] = (f"fora da porta do E8: {efeito['fora_da_porta']} — nada lido; não é feito (volta quando a "
                         "fonte mudar)")
    if r is None or efeito.get("ja_lido") or efeito.get("fora_da_porta"):
        return out
    fatias = list(efeito.get("fatias") or [])
    out["recontados"] = int(con.execute("SELECT count(*) FROM fatos WHERE chave = ANY(%s)",
                                        (fatias,)).fetchone()[0]) if fatias else 0
    linhas = con.execute("SELECT id, doc_id, doc_sha, inicio, fim, citacao FROM fatos WHERE chave = ANY(%s) "
                         "AND estado = %s", (fatias, VERIFICADO)).fetchall() if fatias else []
    sorteio = random.Random(chave).sample(linhas, min(amostra, len(linhas)))
    docs = {}
    if sorteio:
        if efeito.get("fonte_texto") == FONTE_ESTAGIO:
            if con_cap is None:
                raise ErroPermanente(f"{proc}: efeito declara o texto do estágio e a conferência não tem o PG da "
                                     "captura")
            ac = acervo_do_estagio(con_cap, proc)
            docs = {d["doc_id"]: d for d in (ac.docs if ac is not None else [])}
        else:
            docs = {d["doc_id"]: d for d in LI._docs(pasta_do(proc))}
    for fid, doc, sha, ini, fim, cit in sorteio:
        d = docs.get(doc)
        if d is None or d["sha"] != sha or d["texto"][ini:fim] != cit:
            out["divergentes"].append(fid)
    out["amostra"] = len(sorteio)
    return out


def _efeito_ok(efeito: dict, c: dict) -> bool:
    if not c["leitura_no_pg"]:
        return False
    if efeito.get("fora_da_porta"):              # achado 1.13: sem leitura não é "feito" (falhou_efeito com motivo)
        return False
    if efeito.get("ja_lido"):
        return True
    return c["recontados"] == efeito.get("fatos_gravados") and not c["divergentes"]


def _payload(payload: dict) -> str:
    proc = str(payload.get("processo") or "").strip()
    if not proc:
        raise ErroPermanente("payload sem 'processo'")
    return proc


def _conectar_captura(payload: dict):
    """O PG da captura (E2–E7: `documentos`, `versoes`, `transformacao`, `ocr_conferencia`) — o esquema vem de
    `JFN_CAPTURA_ESQUEMA` (ou `payload.esquema_captura`), o mesmo DSN dos fatos."""
    from compliance_agent.aplicacao.estagios import texto as T
    return T.conectar(payload.get("dsn"), payload.get("esquema_captura"))


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    processo = _payload(payload)
    pg = conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        from compliance_agent.fluxo import fila
        cap = _conectar_captura(payload)
        try:
            cf = fila.conectar()
            try:
                r = ler_processo(pg, processo, leitor_assinatura(cf), via="assinatura", con_cap=cap)
            finally:
                cf.close()
        finally:
            cap.close()
    finally:
        pg.close()
    novos = r.get("fatos_gravados") and r.get("fatias_lidas_agora")
    return Resultado(efeito=r, eventos=[{"fonte": "fatos", "tipo": "mudou", "chave": processo}] if novos else [])


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    pg = conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        cap = _conectar_captura(payload)
        try:
            c = conferir(pg, resultado.efeito, con_cap=cap)
        finally:
            cap.close()
    finally:
        pg.close()
    resultado.efeito["conferencia"] = c
    return _efeito_ok(resultado.efeito, c)


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["llm"], prioridade=45)


# ══ 6. ordem única (OB paga desc + cota Couto 50%) ═════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Candidato:
    processo: str                   # como no acervo ('020001/000354/2025') ou 'SEI-<chave>' sem acervo
    chave: str                      # ob_processo.chave_processo
    ob_paga: float
    couto: bool
    capturado: bool


def abrir_fonte(caminho: str | Path | None = None) -> sqlite3.Connection:
    p = Path(caminho or os.environ.get(ENV_FONTE) or fonte_coleta.caminho())
    if not p.exists():
        raise ErroPermanente(f"fonte só-leitura ausente: {p}")
    return sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)


def ob_paga_por_processo(fonte: sqlite3.Connection) -> dict[str, tuple[float, bool]]:
    """chave do processo → (R$ de OB PAGA no SIAFE, tem OB paga emitida no período Couto). Régua canônica do pago."""
    from compliance_agent.dominio.pagamento import ob_paga_sql
    from compliance_agent.governo_couto import INICIO
    from compliance_agent.ob_processo import chave_processo as cp
    iso = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"
    out: dict[str, tuple[float, bool]] = {}
    for proc, v, ult in fonte.execute(f"SELECT processo, SUM(valor), MAX({iso}) FROM ob_orcamentaria_siafe "
                                      f"WHERE {ob_paga_sql(fonte)} GROUP BY processo"):
        k = cp(proc or "")
        if k:
            v0, c0 = out.get(k, (0.0, False))
            out[k] = (v0 + float(v or 0.0), c0 or bool(ult and ult >= INICIO))
    return out


def pastas_por_chave() -> dict[str, str]:
    from compliance_agent.ob_processo import chave_processo as cp
    out = {}
    for m in EV.ARQUIVO.glob("*/manifest.json"):
        proc = m.parent.name.replace("_", "/")
        k = cp(proc)
        if k:
            out.setdefault(k, proc)
    return out


def ordem(valores: dict[str, tuple[float, bool]], pastas: dict[str, str], fracao_couto: float = 0.5,
          so_couto: bool = False) -> list[Candidato]:
    """A fila do E8 na ordem única (`fluxo.prioridade.ordenar`): OB paga maior antes, com ⌈n·50%⌉ processos do
    período Couto em todo prefixo. Só processo com OB paga entra; a posição na árvore nunca conta."""
    from compliance_agent.fluxo.prioridade import Sinais, ordenar
    cands = [Candidato(processo=pastas.get(k, f"SEI-{k}"), chave=k, ob_paga=v, couto=c, capturado=k in pastas)
             for k, (v, c) in valores.items() if v > 0 and (c or not so_couto)]
    return ordenar(cands, lambda x: Sinais(ob_paga=x.ob_paga, couto=x.couto), fracao_couto=fracao_couto)


# ══ 7. projeção de custo (não gasta) ═══════════════════════════════════════════════════════════════════════════
def precos_haiku() -> dict:
    """Preço oficial em US$/MTok de `config/llm_precos.yaml` (conferido na página oficial; data no próprio YAML)."""
    from compliance_agent.adaptadores.llm import gateway as G
    tab = G.precos()
    m = dict((tab.get("modelos") or {})[MODELO])
    m["desconto_lote"] = float(tab.get("desconto_lote") or 1.0)
    m["fonte"] = tab.get("fonte")
    return m


def custo_fatia(tokens_in: int, tokens_out: int, tokens_sistema: int, *, lote: bool, cache: bool,
                pr: dict) -> float:
    """US$ de uma fatia. Prompt > limiar ⇒ a requisição inteira na faixa longa (regra da página oficial)."""
    faixa = pr["longo"] if tokens_in + tokens_sistema > int(pr.get("longo_acima_de_tokens") or 10**12) else pr
    entrada = tokens_in * faixa["entrada"]
    sist = tokens_sistema * (faixa["cache_leitura"] if cache else faixa["entrada"])
    usd = (entrada + sist + tokens_out * faixa["saida"]) / 1e6
    return usd * (pr["desconto_lote"] if lote else 1.0)


def estimar(fatias_textos: list[str], *, saida_por_fatia: int, pr: dict, fator_real: float = LI.FATOR_REAL) -> dict:
    """Tokens pela régua conservadora da casa (2,5 car./token) × o fator medido real÷projetado; US$ com e sem lote e
    com e sem cache do sistema. `saida_por_fatia` = tokens de saída esperados (o pior caso é `MAX_TOKENS_SAIDA`)."""
    from compliance_agent.llm import claude_api as C
    ts = int(C._tokens_aprox(SISTEMA) * fator_real)
    tin = [int(C._tokens_aprox(t) * fator_real) for t in fatias_textos]
    out = {"fatias": len(tin), "tokens_entrada": sum(tin) + ts * len(tin), "tokens_saida": saida_por_fatia * len(tin)}
    for nome, lote, cache in (("usd_lote", True, False), ("usd_lote_cache", True, True), ("usd_sem_lote", False, False)):
        out[nome] = round(sum(custo_fatia(t, saida_por_fatia, ts, lote=lote, cache=cache, pr=pr) for t in tin), 6)
    return out


def projetar_universo(fonte: sqlite3.Connection, lidos: set[str], tabs: set[str], limite: int = 0) -> dict:
    """O universo-alvo do plano (§6 "E8 destravado"): processos com OB PAGA do período Couto ainda não lidos. Lê o
    acervo e conta; NÃO chama modelo nem grava nada. Processo sem acervo entra como 'a capturar' (a projeção de
    tokens dele é a média dos capturados que vão ao modelo — declarada como projeção, nunca como medida)."""
    pr = precos_haiku()
    fila = ordem(ob_paga_por_processo(fonte), pastas_por_chave(), so_couto=True)
    r = {"universo": len(fila), "ob_paga_universo": round(sum(c.ob_paga for c in fila), 2), "capturados": 0,
         "a_capturar": 0, "fora_da_porta": {}, "ja_lidos": 0, "a_ler": 0, "textos": [], "chars_a_ler": 0}
    for c in fila[: limite or None]:
        if not c.capturado:
            r["a_capturar"] += 1
            continue
        r["capturados"] += 1
        try:
            p = preparar(c.processo, lidos, tabs)
        except (OSError, ValueError) as e:
            r["fora_da_porta"][f"ilegível ({type(e).__name__})"] = r["fora_da_porta"].get(
                f"ilegível ({type(e).__name__})", 0) + 1
            continue
        if p.fora_da_porta:
            r["fora_da_porta"][p.fora_da_porta] = r["fora_da_porta"].get(p.fora_da_porta, 0) + 1
        elif not p.fatias:
            r["ja_lidos"] += 1
        else:
            r["a_ler"] += 1
            r["textos"] += [f.texto for f in p.fatias]
            r["chars_a_ler"] += sum(len(f.texto) for f in p.fatias)
    textos = r.pop("textos")
    r["medido"] = {"esperado_1500": estimar(textos, saida_por_fatia=1500, pr=pr),
                   "pior_caso": estimar(textos, saida_por_fatia=MAX_TOKENS_SAIDA, pr=pr)}
    r["precos"] = {k: pr[k] for k in ("entrada", "saida", "cache_leitura")} | {"desconto_lote": pr["desconto_lote"],
                                                                              "fonte": pr["fonte"]}
    return r


# ══ 8. Batch Haiku (piloto e volume)═══════════════════════════════════════════════════════════════════════════
def lote_enviar(con, processos: list[str], teto_usd: float, enviar: bool) -> dict:
    """Prepara as fatias ainda não gravadas, IMPRIME a estimativa (pior caso = saída no teto) e só envia com
    `enviar=True`, pior caso ≤ `teto_usd` e dentro do teto mensal do gateway. O `claude_api.enviar_lote` ainda passa
    pelo livro-caixa dele (baldes, teto do ciclo) e pode recusar — a recusa é impressa, nunca contornada."""
    from compliance_agent.adaptadores.llm import gateway as G
    from compliance_agent.llm import claude_api as C
    lidos, tabs = ja_lidos(con), tabelas_lidas(con)
    itens, mapas, resumo = [], {}, {"processos": 0, "fatias": 0, "fora_da_porta": 0, "ja_lidos": 0}
    for proc in processos:
        p = preparar(proc, lidos, tabs)
        if p.fora_da_porta:
            resumo["fora_da_porta"] += 1
            print(f"fora da porta: {proc} — {p.fora_da_porta}", file=sys.stderr)
            continue
        if leitura_concluida(con, proc, p.chave):
            resumo["ja_lidos"] += 1
            continue
        resumo["processos"] += 1
        for f in p.fatias:
            if fatia_gravada(con, f.chave):
                continue
            cid = f.chave[:40]
            itens.append((cid, f.texto))
            mapas[cid] = {"processo": proc, "chave": f.chave, "chave_processo": p.chave, "mapa": f.mapa}
    pr = precos_haiku()
    textos = [t for _, t in itens]
    pior = estimar(textos, saida_por_fatia=MAX_TOKENS_SAIDA, pr=pr)
    esperado = estimar(textos, saida_por_fatia=1500, pr=pr)
    orc = G.estado_orcamento()
    resumo.update({"fatias": len(itens), "usd_pior_caso_lote": pior["usd_lote"], "usd_esperado_lote":
                   esperado["usd_lote"], "teto_usd": teto_usd, "gateway_mes": orc, "precos": pr["fonte"]})
    print(json.dumps(resumo, ensure_ascii=False, default=str))
    if not enviar or not itens:
        return resumo
    if pior["usd_lote"] > teto_usd:
        resumo["recusa"] = f"pior caso US$ {pior['usd_lote']:.4f} > teto pedido US$ {teto_usd:.2f}"
        return resumo
    if orc["gasto_usd"] + orc["reservado_usd"] + pior["usd_lote"] > orc["corte_usd"]:
        resumo["recusa"] = "teto mensal do gateway: passaria do corte de 85%"
        return resumo
    lote = C.enviar_lote(TAREFA, itens, sistema=SISTEMA, modelo=MODELO, max_tokens=MAX_TOKENS_SAIDA)
    if not lote:
        resumo["recusa"] = f"claude_api recusou: {C.ultimo_motivo}"
        return resumo
    DIR_LOTES.mkdir(parents=True, exist_ok=True)
    (DIR_LOTES / f"{lote}.json").write_text(json.dumps(mapas, ensure_ascii=False), encoding="utf-8")
    resumo["lote"] = lote
    return resumo


def lote_colher(con) -> list[dict]:
    """Colhe os lotes prontos: cada resposta é ancorada na fatia REFEITA do acervo (mesma chave ⇒ mesmo texto; chave
    diferente = o acervo mudou ⇒ a resposta é descartada, nunca ancorada em texto que o modelo não viu)."""
    from compliance_agent.llm import claude_api as C
    saidas = []
    for arq in sorted(DIR_LOTES.glob("*.json")):
        lote = arq.stem
        saida = C.colher_lote(lote)
        if saida is None:
            saidas.append({"lote": lote, "estado": "em curso"})
            continue
        mapas = json.loads(arq.read_text(encoding="utf-8"))
        lidos, tabs = ja_lidos(con), tabelas_lidas(con)
        por_proc: dict[str, list[str]] = {}
        for cid, info in mapas.items():
            por_proc.setdefault(info["processo"], []).append(cid)
        r = {"lote": lote, "gravadas": 0, "descartadas": 0, "invalidas": 0, "processos_concluidos": 0}
        for proc, cids in por_proc.items():
            p = preparar(proc, lidos, tabs)
            fat = {f.chave: f for f in p.fatias}
            invalidas = []
            for cid in cids:
                f = fat.get(mapas[cid]["chave"])
                if f is None or saida.get(cid) is None:
                    r["descartadas"] += 1
                    continue
                fatos = interpretar(saida[cid], f.docs, mapas[cid]["mapa"])
                if fatos is None:
                    r["invalidas"] += 1
                    invalidas.append(f)
                    continue
                gravar_fatia(con, proc, f, fatos, f"{MODELO}{C.SUFIXO_API}-lote")
                r["gravadas"] += 1
            if p.chave and all(fatia_gravada(con, f.chave) or f in invalidas for f in p.fatias):
                concluir(con, p, f"lote:{lote}", invalidas)
                r["processos_concluidos"] += 1
        arq.rename(arq.with_suffix(".colhido"))
        saidas.append(r)
    return saidas


# ══ CLI ════════════════════════════════════════════════════════════════════════════════════════════════════════
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E8 fatos (O6.3)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("schema")
    s.add_argument("acao", choices=("aplicar", "verificar"))
    o = sub.add_parser("ordem")
    o.add_argument("--limite", type=int, default=30)
    o.add_argument("--fonte")
    o.add_argument("--so-couto", action="store_true")
    pj = sub.add_parser("projetar")
    pj.add_argument("--fonte")
    pj.add_argument("--limite", type=int, default=0)
    pj.add_argument("--saida")
    le = sub.add_parser("ler")
    le.add_argument("--processo", required=True)
    lt = sub.add_parser("lote")
    lt.add_argument("acao", choices=("enviar", "colher"))
    lt.add_argument("--processos", help="arquivo com um processo por linha (enviar)")
    lt.add_argument("--teto-usd", type=float, default=2.0)
    lt.add_argument("--enviar", action="store_true", help="sem isto, só imprime a estimativa")
    a = ap.parse_args(argv)
    if a.cmd == "ordem":
        fonte = abrir_fonte(a.fonte)
        try:
            fila = ordem(ob_paga_por_processo(fonte), pastas_por_chave(), so_couto=a.so_couto)
        finally:
            fonte.close()
        for c in fila[: a.limite]:
            print(json.dumps({"processo": c.processo, "ob_paga": round(c.ob_paga, 2), "couto": c.couto,
                              "capturado": c.capturado}, ensure_ascii=False))
        return 0
    con = conectar()
    try:
        if a.cmd == "projetar":            # só lê: PG (docs_lidos/tabelas_lidas), fonte imutável e acervo
            fonte = abrir_fonte(a.fonte)
            try:
                r = projetar_universo(fonte, ja_lidos(con), tabelas_lidas(con), a.limite)
            finally:
                fonte.close()
            txt = json.dumps(r, ensure_ascii=False, default=str)
            if a.saida:
                Path(a.saida).write_text(txt, encoding="utf-8")
            print(txt)
            return 0
        if a.cmd == "schema":
            if a.acao == "aplicar":
                aplicar_schema(con)
            falta = verificar_schema(con)
            print(json.dumps({"esquema": esquema_vigente(), "ok": not falta, "faltando": falta}, ensure_ascii=False))
            return 0 if not falta else 1
        if a.cmd == "lote":
            if a.acao == "colher":
                print(json.dumps(lote_colher(con), ensure_ascii=False))
                return 0
            procs = [ln.strip() for ln in Path(a.processos).read_text(encoding="utf-8").splitlines() if ln.strip()]
            r = lote_enviar(con, procs, a.teto_usd, a.enviar)
            if r.get("recusa"):
                print(f"fatos: lote NÃO enviado — {r['recusa']}", file=sys.stderr)
                return 1
            return 0
        payload = {"processo": a.processo}
        ctx = Contexto(no=os.environ.get("JFN_NO", "cli"), tipo="fatos", chave=f"fatos:{a.processo}", ficha=0,
                       tentativa=1)
        res = _handler(payload, ctx)
        ok = _efeito(payload, ctx, res)
        print(json.dumps(res.efeito, ensure_ascii=False, default=str))
        if not ok:
            print("fatos: EFEITO NÃO CONFERIDO", file=sys.stderr)
            return 1
        print(f"fatos: {res.efeito.get('fatos_gravados', 0)} fato(s) conferido(s) em {esquema_vigente()}.fatos "
              f"({a.processo})")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
