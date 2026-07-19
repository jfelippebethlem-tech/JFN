# -*- coding: utf-8 -*-
"""J8 · ATESTADO DE CAPACIDADE TÉCNICA CRUZADO (emissor vinculado ao licitante) — Ac. TCU 725/2026.

FUNDAMENTO: o Acórdão TCU 725/2026 firma que atestado de capacidade técnica emitido por empresa do
MESMO GRUPO do licitante é indício FORTE de fachada/fraude à habilitação — a empresa "atesta" a própria
capacidade por interposta pessoa jurídica. Mecanismo: (1) extrair do texto de habilitação os blocos de
atestado e o CNPJ do EMISSOR; (2) cruzar emissor × licitante no compliance.db por sócio em comum (QSA)
e por mesmo endereço; (3) emissor ≠ licitante COM vínculo → achado.

REGRA DE PAPÉIS (spec §1.3): tudo aqui é CÓDIGO determinístico (regex + SQL); nenhum limiar em prompt.

GUARDS ANTI-FP (honestidade: indício ≠ acusação):
  • vínculo QSA por NOME normalizado exige nome com ≥ 5 caracteres (mitiga homonímia; ainda é indício,
    não prova — a corroboração por fragmento de CPF fica com `resolucao_cpf`);
  • vínculo por endereço exige `endereco_norm` idêntico e com ≥ 12 caracteres (endereço curto/genérico
    não sustenta);
  • bloco de atestado SEM CNPJ identificável não vira achado (sem emissor não há cruzamento);
  • tabela ausente no DB → warning explícito e vínculo daquela fonte fica sem juízo (nunca silencioso).

HONESTIDADE JFN: sem texto/licitante/db no contexto → `nao_avaliavel` (ausência de dado ≠ 0).
"""
from __future__ import annotations

import logging
import re
import sqlite3

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora, sem_acentos

log = logging.getLogger(__name__)

FUNDAMENTO = "Ac. TCU 725/2026"

# CNPJ formatado (12.345.678/0001-90) ou cru (12345678000190).
_CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
# Marcadores de bloco de atestado (case-insensitive; cobre texto com e sem acento).
_MARCADOR_RE = re.compile(r"atestado\s+de\s+capacidade\s+t[eé]cnica|atestamos\s+que", re.IGNORECASE)

_JANELA_ANTES = 300    # busca do CNPJ do emissor ANTES do marcador (papel timbrado vem primeiro)
_JANELA_DEPOIS = 400   # fallback: primeiro CNPJ APÓS o marcador
_EVIDENCIA_RAIO = 200  # ±200 chars de evidência em volta do marcador
_MIN_NOME_SOCIO = 5    # guard homonímia: nome de sócio muito curto não sustenta vínculo
_MIN_ENDERECO = 12     # guard: endereco_norm curto/genérico não sustenta vínculo


def _dig(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def _norm_nome(nome) -> str:
    """Nome de sócio normalizado p/ comparação (minúsculas, sem acento, espaços colapsados)."""
    return " ".join(sem_acentos(nome).split())


def extrair_atestados(texto: str) -> list[dict]:
    """Acha blocos de atestado ("atestado de capacidade técnica" / "atestamos que") e extrai o CNPJ do
    EMISSOR + trecho de evidência (±200 chars do marcador).

    Heurística do emissor: o ÚLTIMO CNPJ antes do marcador (papel timbrado do emissor precede o corpo);
    fallback = primeiro CNPJ após o marcador. Bloco sem CNPJ é descartado (sem emissor não há cruzamento).
    Marcadores a <200 chars um do outro contam como o MESMO bloco (dedup).

    Retorna [{emissor_cnpj: '14 dígitos', cnpjs_bloco: [...], evidencia: str}]."""
    achados: list[dict] = []
    if not texto:
        return achados
    ultimo_inicio = -10**9
    for m in _MARCADOR_RE.finditer(texto):
        if m.start() - ultimo_inicio < 2 * _EVIDENCIA_RAIO:
            continue  # mesmo bloco (ex.: título "ATESTADO..." seguido de "Atestamos que")
        ultimo_inicio = m.start()
        antes = texto[max(0, m.start() - _JANELA_ANTES):m.start()]
        depois = texto[m.end():m.end() + _JANELA_DEPOIS]
        cnpjs_antes = [c for c in (_dig(x.group(0)) for x in _CNPJ_RE.finditer(antes)) if len(c) == 14]
        cnpjs_depois = [c for c in (_dig(x.group(0)) for x in _CNPJ_RE.finditer(depois)) if len(c) == 14]
        emissor = (cnpjs_antes[-1] if cnpjs_antes else None) or (cnpjs_depois[0] if cnpjs_depois else None)
        if not emissor:
            continue
        evid = " ".join(texto[max(0, m.start() - _EVIDENCIA_RAIO):m.end() + _EVIDENCIA_RAIO].split())
        cnpjs_bloco = list(dict.fromkeys(cnpjs_antes + cnpjs_depois))
        achados.append({"emissor_cnpj": emissor, "cnpjs_bloco": cnpjs_bloco, "evidencia": evid})
    return achados


def _nomes_socios(db: sqlite3.Connection, cnpj14: str) -> set[str]:
    """Nomes (normalizados) dos sócios de um CNPJ: `socios_receita` (por cnpj_basico = 8 primeiros dígitos)
    + `socios_fornecedor` (por cnpj de 14 dígitos). Tabela ausente → warning e segue (parcial explícito)."""
    nomes: set[str] = set()
    consultas = (
        ("SELECT nome_norm, nome_socio FROM socios_receita WHERE cnpj_basico = ?", cnpj14[:8]),
        ("SELECT socio_nome_norm, socio_nome FROM socios_fornecedor WHERE cnpj = ?", cnpj14),
    )
    for sql, arg in consultas:
        try:
            linhas = db.execute(sql, (arg,)).fetchall()
        except sqlite3.OperationalError as e:
            log.warning("atestado_cruzado: consulta QSA indisponível (%s) — vínculo societário PARCIAL", e)
            continue
        for norm, bruto in linhas:
            n = _norm_nome(norm or bruto)
            if len(n) >= _MIN_NOME_SOCIO:
                nomes.add(n)
    return nomes


def _endereco_norm(db: sqlite3.Connection, cnpj14: str) -> str:
    """`endereco_fornecedor.endereco_norm` do CNPJ ('' se ausente/curto demais p/ sustentar vínculo)."""
    try:
        linha = db.execute(
            "SELECT endereco_norm FROM endereco_fornecedor WHERE cnpj = ? "
            "AND endereco_norm IS NOT NULL AND endereco_norm != '' LIMIT 1", (cnpj14,)
        ).fetchone()
    except sqlite3.OperationalError as e:
        log.warning("atestado_cruzado: endereco_fornecedor indisponível (%s) — vínculo de endereço sem juízo", e)
        return ""
    end = str(linha[0]).strip() if linha else ""
    return end if len(end) >= _MIN_ENDERECO else ""


def vinculos_emissor_licitante(emissor_cnpj: str, licitante_cnpj: str, db: sqlite3.Connection) -> list[str]:
    """Vínculos objetivos entre EMISSOR do atestado e LICITANTE no compliance.db.

    Fontes: sócio em comum (`socios_receita` por cnpj_basico + `socios_fornecedor` por cnpj, match por
    nome normalizado com guard de homonímia) → 'qsa'; mesmo `endereco_fornecedor.endereco_norm` → 'endereco'.
    Retorna a lista dos vínculos achados (ex.: ['qsa', 'endereco']); [] = nenhum vínculo NAS FONTES DISPONÍVEIS."""
    emissor, licitante = _dig(emissor_cnpj), _dig(licitante_cnpj)
    if len(emissor) != 14 or len(licitante) != 14:
        log.warning("atestado_cruzado: CNPJ inválido (emissor=%r licitante=%r) — sem cruzamento", emissor_cnpj, licitante_cnpj)
        return []
    vinculos: list[str] = []
    if _nomes_socios(db, emissor) & _nomes_socios(db, licitante):
        vinculos.append("qsa")
    end_e, end_l = _endereco_norm(db, emissor), _endereco_norm(db, licitante)
    if end_e and end_e == end_l:
        vinculos.append("endereco")
    return vinculos


def atestado_cruzado(texto_habilitacao: str, licitante_cnpj: str, db_path: str) -> list[dict]:
    """Pipeline completo: extrai atestados do texto de habilitação e cruza cada EMISSOR com o LICITANTE.

    Achado (emissor ≠ licitante E vínculo no DB): {emissor_cnpj, licitante_cnpj, vinculos, evidencia,
    fundamento: 'Ac. TCU 725/2026'}. DB aberto READONLY (nunca escreve). Licitante sem CNPJ válido → []
    com warning (sem cruzamento possível)."""
    licitante = _dig(licitante_cnpj)
    if len(licitante) != 14:
        log.warning("atestado_cruzado: licitante_cnpj inválido (%r) — análise NÃO realizada", licitante_cnpj)
        return []
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        achados: list[dict] = []
        emissores_vistos: set[str] = set()
        for atestado in extrair_atestados(texto_habilitacao):
            emissor = atestado["emissor_cnpj"]
            if emissor == licitante or emissor in emissores_vistos:
                continue
            emissores_vistos.add(emissor)
            vincs = vinculos_emissor_licitante(emissor, licitante, db)
            if vincs:
                achados.append({
                    "emissor_cnpj": emissor,
                    "licitante_cnpj": licitante,
                    "vinculos": vincs,
                    "evidencia": atestado["evidencia"],
                    "fundamento": FUNDAMENTO,
                })
        return achados
    finally:
        db.close()


class JAtestadoCruzado(Detector):
    """Detector J8 — atestado de capacidade técnica emitido por empresa vinculada ao licitante.

    `avaliar(contexto)` espera:
      contexto["processo"]: id do certame/processo.
      contexto["texto_habilitacao"]: str — texto (OCR/extraído) dos documentos de habilitação do licitante.
      contexto["licitante_cnpj"]: str — CNPJ do licitante (formatado ou cru).
      contexto["db_path"]: str — caminho do compliance.db (aberto READONLY).
      contexto["achados_atestado"] (opcional, teste): achados pré-computados — pula texto/DB.

    Âncora: vínculo objetivo emissor↔licitante = 'forte' (Ac. TCU 725/2026: indício forte de fachada;
    não é prova de fraude — a explicação inocente clássica é grupo econômico declarado executando de fato).
    Sem entradas → nao_avaliavel; avaliado sem achado → descartado (regra testada, indício não encontrado)."""

    id = "J8"
    nome = "Atestado de capacidade técnica cruzado (emissor do mesmo grupo)"
    familia = "conluio"  # peso 0.9 na convergência §7.2

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        achados = contexto.get("achados_atestado")
        if achados is None:
            texto = contexto.get("texto_habilitacao") or ""
            licitante = _dig(contexto.get("licitante_cnpj"))
            db_path = contexto.get("db_path") or ""
            if not texto or len(licitante) != 14 or not db_path:
                res.motivo_refutacao = ("nao_avaliavel: exige texto_habilitacao + licitante_cnpj (14 díg.) + "
                                        "db_path — campo ausente ≠ 0")
                return res
            achados = atestado_cruzado(texto, licitante, db_path)

        res.valores = {"achados": achados, "n_achados": len(achados)}
        if not achados:
            res.status = "descartado"
            res.score = ancora("ausente")
            res.motivo_refutacao = "nenhum atestado com emissor vinculado ao licitante (fontes disponíveis)"
            return res

        res.status = "confirmado"
        res.score = ancora("forte")
        res.explicacao_inocente = ("grupo econômico declarado em que a experiência atestada foi de fato "
                                   "executada pela emissora — exige verificação da execução real")
        for a in achados:
            res.add_evidencia(
                fonte=f"habilitacao:{processo} · {FUNDAMENTO}",
                trecho=f"emissor {a['emissor_cnpj']} × licitante {a['licitante_cnpj']} "
                       f"(vínculos: {', '.join(a['vinculos'])}) — {a['evidencia']}",
            )
        return res
