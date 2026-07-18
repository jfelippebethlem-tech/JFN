# -*- coding: utf-8 -*-
"""FUNDAMENTO do framework de detectores de corrupção em licitações (§1 do spec V2 do dono).

Arquitetura para IA FRACA (manual V2, `~/vault/notas/detectores-corrupcao-licitacoes-v2.md`): cada red flag é
decomposta em (a) REGRAS OBJETIVAS computáveis em código determinístico e (b) avaliações subjetivas convertidas
em RUBRICAS FECHADAS de 3-4 níveis com citação literal obrigatória. O LLM extrai e classifica (âncora, nunca
valor contínuo); o CÓDIGO compara e pontua. Separação de papéis inegociável: **limiar numérico fica no código,
nunca no prompt do LLM**.

HONESTIDADE JFN (cláusula absoluta): indício ≠ acusação; presunção de regularidade; `INDISPONÍVEL`/`nao_avaliavel`
≠ 0; nunca inventar número. Score é indício INTERNO (não nota pública). Tudo que toca o LLM degrada honesto: se
o LLM cai, o detector marca `nao_avaliavel` no campo afetado e NUNCA quebra nem fabrica.

Camadas (spec §1.1): 1.Extração · 2.Regras objetivas (código puro) · 3.Avaliação subjetiva (LLM rubrica fechada)
· 4.Agregação + verificador adversarial. Score padronizado [0,1] com ÂNCORAS fixas (§1.2). Schema de saída fixo
(§1.4) em `ResultadoDetector`. Convergência multiplicativa (§7.2): `score_processo = 1 − Π(1 − w·s)`.


MAPA DOS 30 DETECTORES → O QUE O JFN JÁ TEM (para os próximos plugarem REUSANDO, sem duplicar)
============================================================================================
Convenção: ✅ já coberto (reusar) · 🟡 parcial (base existe, falta o card do detector) · ⬜ a construir.
Os módulos citados vivem em `compliance_agent/`.

  FASE DE PLANEJAMENTO
  P1  Especificação dirigida / marca disfarçada ...... 🟡 `direcionamento_cerebro` (cérebro edital+ata) +
                                                          `precos_extract` (extrai requisitos do TR)
  P2  Cotações combinadas (orçamentos fachada) ....... 🟡 `precos_extract.sobrepreco_interno` (CV das cotações)
                                                          + `rede_societaria`/`relacoes` (vínculo cotantes)
  P3  Sobrepreço na estimativa ....................... ✅ `precos_extract` + `sobrepreco.py` + `anomalias.py`
  P4  Fracionamento de despesa ....................... ✅ `detectores/p4_fracionamento.py` (ESTE pacote)
  P5  Emergência fabricada ........................... ⬜ (timeline em `correlacao_sei`/`processos_sei`; falta o card)

  FASE DE EDITAL
  E1  Barreira de entrada (qualificação) ............. 🟡 `direcionamento_cerebro` (exigências restritivas/atestado)
  E2  Publicidade e prazos minimizados ............... ⬜ (datas no PNCP; falta o card)
  E3  Lote-pacote (agregação anticompetitiva) ........ ⬜
  E4  Visita técnica como filtro ..................... ⬜
  E5  Edital iterado (republicações dirigidas) ....... ⬜ (`corpus_editais` guarda versões; falta o diff)
  E6  Pontuação técnica dirigida ..................... 🟡 `direcionamento_cerebro` (matriz/cascata de julgamento)

  FASE DE JULGAMENTO (conluio — estatístico, exige série)
  J1  Rodízio de vencedores .......................... ✅ `grafo_cartel.concentracao_por_grupo` (HHI/grupo) +
                                                          `rodizio_temporal` (runs/alternância)
  J2  Propostas de cobertura (screens de preço) ...... 🟡 `anomalias.py` (Benford/dispersão); falta CV/RD/DIFFP
  J3  Desconto anômalo ............................... 🟡 `anomalias.py` / `sobrepreco.py` (desconto vs baseline)
  J4  Supressão de propostas / licitante único ....... 🟡 `rodizio_temporal` (perdedora profissional)
  J5  Digitais compartilhadas (metadados) ............ ⬜ (exiftool; falta o card)
  J6  Subcontratação cruzada / consórcio ............. 🟡 `rede_societaria`/`grafo_cartel.socios_compartilhados`
  J7  Inabilitação seletiva (dois pesos) ............. 🟡 `direcionamento_cerebro` (lê a ata de julgamento)

  PERFIL DO CONTRATADO
  C1  CNPJ recém-nascido ............................. 🟡 `fornecedor` enrich (idade CNPJ) — ver `enrichers/`
  C2  Estrutura incompatível com o objeto ............ 🟡 `verificacao_endereco` (sede real) + capital social
  C3  Atividade (CNAE) incompatível .................. 🟡 enrich CNAE (BrasilAPI) em `enrich/`/`enrichers/`
  C4  Quadro societário suspeito (laranjas) .......... ✅ `grafo_cartel.cartel_com_qsa` + `rede_societaria` +
                                                          `relacoes` + `resolucao_cpf` (QSA/grafo/homonímia)
  C5  Reencarnação de empresa sancionada ............. ✅ `lex_sancoes` (CEIS/CNEP/inidôneos TCU) + QSA histórico
  C6  Vínculo político-financeiro (doações) .......... ✅ `grafo_poder` + tabela `doacoes_eleitorais` (TSE)

  EXECUÇÃO
  X1  Crescimento aditivo (contrato engorda) ......... 🟡 `contratos` (aditivos); falta o teto art.125
  X2  Prorrogação perpétua ........................... ⬜
  X3  Execução financeira anômala .................... ✅ `ob_orcamentaria_siafe` + `ordens_bancarias`
                                                          (tríade empenho→liquidação→pagamento) + `anomalias.py`
  X4  Carona abusiva em Ata de Registro de Preços .... ⬜ (limites art.86; falta o card)
  X5  Jogo de planilha ............................... ⬜ (precisa execução medida item a item)
  X6  Entrega fantasma / atesto de fachada ........... 🟡 `correlacao_sei` (atesto↔OB) + `verificacao_endereco` (C2)

  TRANSVERSAIS (já no JFN, alimentam vários cards)
  · Teto remuneratório CF 37 XI ..................... ✅ `acima_do_teto.py` (não é card de licitação, mas é detector)
  · Acúmulo de cargos .............................. ✅ `acumulo_cargos.py`
  · Investigação doubt-driven (H-hipóteses) ........ ✅ `investigacao_dd` / `investigacao_orgao_dd`
  · Priorização / dual scoring (§7.3) .............. ✅ `priorizacao.py`
  · Cérebro LLM (Gemini→Groq→Cerebras) ............. ✅ `direcionamento_cerebro` (reusado por `verificar_adversarial`)
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

# ───────────────────────────── Score: ÂNCORAS FIXAS (spec §1.2) ─────────────────────────────
# A IA NUNCA inventa valores intermediários: escolhe a âncora. O código pondera/agrega.
ANCORAS: dict[str, float] = {
    "ausente": 0.0,   # regra testada, indício NÃO encontrado
    "fraco": 0.3,     # compatível com irregularidade mas com explicações inocentes comuns; só vale em convergência
    "medio": 0.6,     # anomalia clara frente à base; exige confirmação por outro detector
    "forte": 0.85,    # anomalia grave; explicação inocente improvável; sustenta representação se houver outro forte
    "critico": 1.0,   # violação objetiva de norma ou prova direta (ex.: sócio comum entre licitantes)
}

# Pesos por família para a convergência multiplicativa (spec §7.2).
PESOS_FAMILIA: dict[str, float] = {
    "violacao_legal": 1.0,   # limites art.86/125 excedidos, sancionado contratado, sócio comum
    "conluio": 0.9,          # J1–J7
    "perfil": 0.8,           # C1–C6 (perfil do contratado)
    "preco": 0.8,            # P2/P3
    "desenho_certame": 0.6,  # E1–E6
    "execucao": 0.8,         # X1–X6
}

STATUS_VALIDOS = ("confirmado", "descartado", "nao_avaliavel")


def ancora(nivel: str) -> float:
    """Converte um nível NOMEADO de âncora no score fixo [0,1]. O LLM/regra escolhe a âncora, nunca o valor
    contínuo (spec §1.2). Nível desconhecido → erro explícito (não silenciar com 0)."""
    n = (nivel or "").strip().lower()
    if n not in ANCORAS:
        raise ValueError(f"âncora inválida: {nivel!r} — use uma de {tuple(ANCORAS)}")
    return ANCORAS[n]


def sha256_hex(texto: str) -> str:
    """Hash de higiene probatória (spec §7.4): toda evidência citada carrega sha256 do trecho-fonte."""
    return "sha256:" + hashlib.sha256((texto or "").encode("utf-8")).hexdigest()


def sem_acentos(texto: str) -> str:
    """Minúsculas sem acentos (NFKD, completo — cobre ê/ô/õ/â/ú/ü etc.) p/ chaves de comparação de texto."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def evidencia(fonte: str, trecho: str, capturado_em: str | None = None) -> dict:
    """Monta um item de evidência no schema fixo {fonte, trecho, hash, capturado_em} com sha256 do trecho
    (higiene probatória §7.4). Use isto para nunca esquecer o hash/timestamp."""
    return {
        "fonte": fonte,
        "trecho": trecho,
        "hash": sha256_hex(trecho),
        "capturado_em": capturado_em or _agora_iso(),
    }


# ───────────────────────────── Schema de saída padrão (spec §1.4) ─────────────────────────────
@dataclass
class ResultadoDetector:
    """SCHEMA PADRÃO de saída de TODO detector (spec §1.4). Honesto por construção: `status` distingue
    `confirmado`/`descartado`/`nao_avaliavel` (este ≠ score 0 — é ausência de juízo). `refutada` registra o
    veredito do verificador adversarial. `valores` guarda os números brutos (transparência/reprodutibilidade)."""

    detector: str
    processo: str
    score: float = 0.0
    valores: dict[str, Any] = field(default_factory=dict)
    evidencia: list[dict] = field(default_factory=list)
    explicacao_inocente: str = ""
    refutada: bool = False
    motivo_refutacao: str = ""
    status: str = "nao_avaliavel"

    def __post_init__(self) -> None:
        if self.status not in STATUS_VALIDOS:
            raise ValueError(f"status inválido: {self.status!r} — use {STATUS_VALIDOS}")
        # clamp defensivo: score é sempre [0,1] (jamais NaN/negativo/>1 por bug de cálculo)
        try:
            self.score = max(0.0, min(1.0, float(self.score)))
        except (TypeError, ValueError):
            self.score = 0.0

    def add_evidencia(self, fonte: str, trecho: str, capturado_em: str | None = None) -> "ResultadoDetector":
        """Acrescenta um item de evidência (com hash/timestamp). Retorna self p/ encadear."""
        self.evidencia.append(evidencia(fonte, trecho, capturado_em))
        return self

    def to_dict(self) -> dict:
        """Serializa no schema EXATO do spec §1.4 (ordem dos campos preservada)."""
        return {
            "detector": self.detector,
            "processo": self.processo,
            "score": self.score,
            "valores": self.valores,
            "evidencia": self.evidencia,
            "explicacao_inocente": self.explicacao_inocente,
            "refutada": self.refutada,
            "motivo_refutacao": self.motivo_refutacao,
            "status": self.status,
        }

    def to_json(self, **kw) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kw)


# ───────────────────────────── Rubrica fechada (spec §1.3, regras de ouro) ─────────────────────────────
def avaliar_rubrica(resposta: dict | None, escala: dict[str, str]) -> tuple[str | None, float, str]:
    """Avalia uma resposta de LLM contra uma RUBRICA FECHADA (escala nomeada 3-4 níveis → nível de âncora).

    `escala`: {nivel_da_rubrica: nivel_de_ancora}, ex.: {"ausente": "critico", "generica": "medio",
    "robusta": "ausente"}. `resposta` esperada: {"nivel": <chave da escala>, "trecho": "<citação literal>"}.

    REGRA DE OURO (spec §1.3): citação obrigatória — resposta SEM `trecho` é DESCARTADA (retorna nao_avaliavel,
    score 0, motivo). `nao_avaliavel` é resposta válida e preferível a chute. Honesto: nunca pontua sem citação.

    Retorna (nivel_ancora | None, score, motivo). `None` + score 0 = descartado/sem juízo."""
    if not isinstance(resposta, dict):
        return None, 0.0, "rubrica: resposta ausente/inválida — nao_avaliavel"
    nivel = str(resposta.get("nivel") or resposta.get("classificacao") or "").strip().lower()
    if nivel in ("nao_avaliavel", "não_avaliavel", "nao avaliavel", "indeterminado", ""):
        return None, 0.0, "rubrica: LLM absteve-se (nao_avaliavel) — sem juízo"
    if nivel not in escala:
        return None, 0.0, f"rubrica: nível {nivel!r} fora da escala {tuple(escala)} — descartado"
    trecho = (resposta.get("trecho") or resposta.get("citacao") or "").strip()
    if not trecho:
        # citação obrigatória: sem trecho, a classificação é descartada (não pontua)
        return None, 0.0, "rubrica: classificação SEM citação literal (trecho) — descartada (regra de ouro §1.3)"
    nivel_ancora = escala[nivel]
    return nivel_ancora, ancora(nivel_ancora), f"rubrica: {nivel} → âncora {nivel_ancora}"


# ───────────────────────────── Verificador adversarial (spec §1.3) ─────────────────────────────
_SYS_ADVERSARIAL = (
    "Você é AUDITOR ADVERSARIAL de controle externo. Recebe uma EVIDÊNCIA e um ACHADO preliminar de indício de "
    "irregularidade em licitação. Sua tarefa é a CHECAGEM INVERSA: escreva a MELHOR explicação INOCENTE possível "
    "para a evidência (presunção de legitimidade dos atos administrativos) e diga se os dados, como apresentados, "
    "REFUTAM o achado. NUNCA invente fatos não presentes na evidência. Se a evidência for insuficiente para julgar, "
    "diga isso. Responda SOMENTE com um objeto JSON: "
    '{"explicacao_inocente":"<a melhor hipótese lícita>","refuta":true|false,'
    '"motivo":"<por que refuta ou por que o achado sobrevive — cite o dado>"}'
)


def verificar_adversarial(
    evidencia_list: Sequence[dict],
    achado: str,
    *,
    gerar: Callable[[str, str], str] | None = None,
) -> tuple[bool, str, str]:
    """Passo exculpatório adversarial (spec §1.3): uma segunda chamada INDEPENDENTE recebe a evidência + a
    instrução inversa ('escreva a melhor explicação inocente e diga se os dados a refutam'). Só sobrevive o que
    passa.

    LLM-OPCIONAL e DEGRADA HONESTO (cláusula JFN): se nenhum LLM responde (ou a resposta é inparseável), NÃO
    refuta automaticamente — retorna (refutada=False, motivo='nao_avaliavel: LLM indisponível', explicacao='').
    Indisponível ≠ refutado e ≠ confirmado: marca-se a ausência de juízo no campo de refutação, e NUNCA quebra.

    `gerar`: callable SÍNCRONO (prompt, sistema)->str. Default = `direcionamento_cerebro.gerar_sync` (Gemini→Groq→
    Cerebras). Em teste, injete um fake (sem rede).

    Retorna (refutada: bool, motivo_refutacao: str, explicacao_inocente: str)."""
    if gerar is None:
        try:
            from compliance_agent.direcionamento_cerebro import gerar_sync as gerar  # type: ignore
        except Exception as e:  # noqa: BLE001 — sem motor LLM disponível
            return False, f"nao_avaliavel: motor LLM não importável ({str(e)[:60]})", ""

    ev_txt = json.dumps(list(evidencia_list or []), ensure_ascii=False)[:6000]
    prompt = (
        f"ACHADO PRELIMINAR (indício a refutar): {achado}\n\n"
        f"EVIDÊNCIA (lista de {{fonte,trecho,hash,capturado_em}}):\n{ev_txt}\n\n"
        "Faça a checagem inversa e responda SOMENTE com o JSON pedido."
    )
    try:
        raw = gerar(prompt, _SYS_ADVERSARIAL)
    except Exception as e:  # noqa: BLE001 — LLM caiu: honesto, não refuta nem confirma
        return False, f"nao_avaliavel: LLM indisponível ({str(e)[:60]}) — exculpatória não realizada", ""

    dados = _parse_json(raw)
    if not isinstance(dados, dict):
        return False, "nao_avaliavel: resposta adversarial não-parseável — exculpatória descartada (honesto)", ""

    refuta = bool(dados.get("refuta"))
    motivo = str(dados.get("motivo") or "").strip()
    explicacao = str(dados.get("explicacao_inocente") or "").strip()
    if refuta:
        return True, motivo or "refutada pela checagem inversa", explicacao
    return False, motivo or "achado sobreviveu à checagem inversa", explicacao


def _parse_json(raw: str | None):
    """Extrai o 1º objeto JSON do texto do LLM (tolera cercas markdown/lixo ao redor)."""
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        import re
        s = re.sub(r"^```[a-z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        import re
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            return None


def aplicar_exculpatoria(res: ResultadoDetector, achado: str, *, gerar=None) -> ResultadoDetector:
    """Roda o verificador adversarial sobre um ResultadoDetector e ATUALIZA seus campos `refutada`,
    `motivo_refutacao`, `explicacao_inocente`. Se refutado → status vira `descartado`. Honesto: se a exculpatória
    é nao_avaliavel (LLM offline), NÃO muda o status (o achado objetivo do código permanece)."""
    refutada, motivo, explicacao = verificar_adversarial(res.evidencia, achado, gerar=gerar)
    res.refutada = refutada
    res.motivo_refutacao = motivo
    if explicacao and not res.explicacao_inocente:
        res.explicacao_inocente = explicacao
    if refutada:
        res.status = "descartado"
    return res


# ───────────────────────────── Detector base ─────────────────────────────
class Detector(ABC):
    """Base de todo detector. Subclasses definem `id`, `nome`, `familia` e implementam `avaliar(contexto)`.

    A `familia` deve ser uma chave de `PESOS_FAMILIA` (para a convergência §7.2). `avaliar` recebe um dicionário
    de CONTEXTO (já extraído — camada 1) e devolve um `ResultadoDetector` no schema fixo. Regra de papéis: o
    código aplica limiares; o LLM (quando usado) só classifica rubrica fechada + cita trecho."""

    id: str = "?"
    nome: str = "detector"
    familia: str = "desenho_certame"

    @abstractmethod
    def avaliar(self, contexto: dict) -> ResultadoDetector:  # pragma: no cover - interface
        ...

    # helpers de conveniência para as subclasses
    def _novo(self, processo: str, **kw) -> ResultadoDetector:
        return ResultadoDetector(detector=self.id, processo=processo, **kw)

    def peso(self) -> float:
        return PESOS_FAMILIA.get(self.familia, 0.6)


# ───────────────────────────── Pipeline + convergência (spec §7) ─────────────────────────────
def pipeline(detectores: Sequence[Detector], contexto: dict, *, exculpatoria=False, gerar=None) -> list[ResultadoDetector]:
    """Roda VÁRIOS detectores sobre o mesmo contexto e devolve a lista de resultados. Cada detector falho é
    isolado (um detector que levanta exceção NÃO derruba os outros — vira um resultado `nao_avaliavel` honesto).

    `exculpatoria=True` roda o verificador adversarial em cada achado confirmado (LLM-opcional, degrada)."""
    resultados: list[ResultadoDetector] = []
    proc = str(contexto.get("processo") or contexto.get("id") or "?")
    for det in detectores:
        try:
            res = det.avaliar(contexto)
        except Exception as e:  # noqa: BLE001 — um detector quebrado não derruba o pipeline
            res = ResultadoDetector(
                detector=getattr(det, "id", "?"), processo=proc, status="nao_avaliavel",
                motivo_refutacao=f"detector levantou exceção: {str(e)[:80]}",
            )
        if exculpatoria and res.status == "confirmado":
            achado = f"{res.detector} ({getattr(det, 'nome', '')}) score={res.score}: {res.explicacao_inocente or 'indício objetivo'}"
            aplicar_exculpatoria(res, achado, gerar=gerar)
        resultados.append(res)
    return resultados


def score_processo(resultados: Sequence[ResultadoDetector], pesos: dict[str, float] | None = None) -> float:
    """Convergência multiplicativa (spec §7.2): `score = 1 − Π(1 − w_d·s_d)` sobre detectores CONFIRMADOS e
    NÃO refutados. Premia convergência sem deixar dezenas de sinais fracos somarem um alarme artificial.

    O peso `w_d` vem da família do detector. Como o `ResultadoDetector` não carrega a família, passe um mapa
    {detector_id: peso} em `pesos`; na ausência, usa 0.6 (desenho de certame, o mais conservador)."""
    pesos = pesos or {}
    prod = 1.0
    for r in resultados:
        if r.status != "confirmado" or r.refutada:
            continue
        w = pesos.get(r.detector, 0.6)
        prod *= (1.0 - w * r.score)
    return round(1.0 - prod, 4)
