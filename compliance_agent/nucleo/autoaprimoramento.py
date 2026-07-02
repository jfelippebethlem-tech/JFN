"""
Autoaprimoramento em loop — o sistema melhora a si mesmo, com prova.

O método é o de um bom engenheiro (hipótese → teste → mantém/reverte):

  1. MEDE o desempenho atual no conjunto-ouro (avaliacao.py) → placar base.
  2. GERA candidatos de mudança:
       a) sugestões do aprendizado (feedback do perito acumulado), e
       b) perturbações sistemáticas dos parâmetros calibráveis (±10%).
  3. TESTA cada candidato isoladamente: aplica o override, reavalia o
     conjunto-ouro, e SÓ MANTÉM se o placar global (F1) subir. Empatou ou
     piorou → reverte na hora. O conjunto-ouro é o freio de segurança:
     impossível o loop "se otimizar" para dentro de um buraco.
  4. REGISTRA tudo (tentado, mantido, revertido, placares antes/depois) num
     diário de evolução (``data/nucleo_evolucao.json``) — o autoaprimoramento
     é 100% auditável, exigência de um sistema de fiscalização.
  5. DESCOBRE padrões novos: minera os textos das perícias CONFIRMADAS pelo
     perito atrás de termos recorrentes que ainda não são red flags — e propõe
     (não impõe) a inclusão.

Parâmetros de fonte legal ("lei") nunca entram no loop — são travados em
``parametros.py``. Só os "orientativo"/"empirico"/"tcu" são calibráveis, e
sempre dentro da faixa sã declarada de cada um.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from compliance_agent.nucleo import aprendizado, parametros as P
from compliance_agent.nucleo.avaliacao import ResultadoAvaliacao, avaliar_sistema


def _arquivo_evolucao() -> Path:
    return Path(os.environ.get("NUCLEO_EVOLUCAO_FILE", "data/nucleo_evolucao.json"))


# ── Snapshot/rollback do estado de calibração ────────────────────────────────

def _snapshot_overrides() -> str | None:
    arq = P.ARQUIVO_OVERRIDES
    return arq.read_text(encoding="utf-8") if arq.exists() else None


def _restaurar_overrides(conteudo: str | None) -> None:
    arq = P.ARQUIVO_OVERRIDES
    if conteudo is None:
        if arq.exists():
            arq.unlink()
    else:
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(conteudo, encoding="utf-8")
    P.recarregar()


# ── Candidatos de calibração ─────────────────────────────────────────────────

@dataclass
class Candidato:
    parametro_id: str
    valor_novo: float
    origem: str            # "feedback" | "perturbacao"
    motivo: str = ""


def _gerar_candidatos(passo: float = 0.10) -> list[Candidato]:
    """Candidatos: sugestões do feedback do perito + perturbações ±passo."""
    candidatos: list[Candidato] = []
    # a) do aprendizado (feedback real do perito)
    for s in aprendizado.sugerir_calibracao():
        candidatos.append(Candidato(s.parametro_id, s.valor_sugerido,
                                    "feedback", s.justificativa))
    # b) perturbações sistemáticas dos calibráveis
    for p in P.listar():
        if p.fonte_valor.startswith("lei"):
            continue
        for fator in (1 - passo, 1 + passo):
            novo = round(p.valor * fator, 6)
            if p.minimo is not None:
                novo = max(p.minimo, novo)
            if p.maximo is not None:
                novo = min(p.maximo, novo)
            if novo != p.valor:
                candidatos.append(Candidato(p.id, novo, "perturbacao",
                                            f"varredura ±{passo:.0%}"))
    # dedup (mantém o primeiro — feedback tem prioridade)
    vistos: set[tuple[str, float]] = set()
    unicos: list[Candidato] = []
    for c in candidatos:
        chave = (c.parametro_id, c.valor_novo)
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(c)
    return unicos


# ── O loop de autoaprimoramento ──────────────────────────────────────────────

@dataclass
class RelatorioEvolucao:
    placar_inicial: ResultadoAvaliacao
    placar_final: ResultadoAvaliacao
    mantidos: list[dict] = field(default_factory=list)
    revertidos: int = 0
    red_flags_propostas: list[str] = field(default_factory=list)


def executar_loop(max_rodadas: int = 3, passo: float = 0.10) -> RelatorioEvolucao:
    """
    Roda o loop de autoaprimoramento até convergir (ou max_rodadas).

    Greedy e seguro: cada candidato é testado sozinho contra o conjunto-ouro;
    melhora estrita de F1 (desempate: menos falsos alarmes) → mantém; senão →
    reverte. Uma rodada sem nenhuma melhoria encerra o loop (convergiu).
    """
    inicial = avaliar_sistema()
    atual = inicial
    mantidos: list[dict] = []
    revertidos = 0

    for _rodada in range(max_rodadas):
        houve_melhora = False
        for cand in _gerar_candidatos(passo):
            antes = _snapshot_overrides()
            try:
                P.definir_override(cand.parametro_id, cand.valor_novo,
                                   motivo=f"auto:{cand.origem}")
            except (ValueError, KeyError):
                continue  # parâmetro travado/desconhecido: pula
            novo = avaliar_sistema()
            melhorou = (novo.f1_global > atual.f1_global
                        or (novo.f1_global == atual.f1_global
                            and novo.falsos_alarmes < atual.falsos_alarmes))
            if melhorou:
                mantidos.append({
                    "parametro": cand.parametro_id,
                    "valor_novo": cand.valor_novo,
                    "origem": cand.origem,
                    "f1_antes": atual.f1_global,
                    "f1_depois": novo.f1_global,
                })
                atual = novo
                houve_melhora = True
            else:
                _restaurar_overrides(antes)
                revertidos += 1
        if not houve_melhora:
            break  # convergiu: nada mais melhora o placar

    relatorio = RelatorioEvolucao(
        placar_inicial=inicial, placar_final=atual,
        mantidos=mantidos, revertidos=revertidos,
        red_flags_propostas=descobrir_red_flags(),
    )
    _registrar_evolucao(relatorio)
    return relatorio


# ── Descoberta de padrões novos (mineração das perícias confirmadas) ─────────

_STOPWORDS = {
    "de", "da", "do", "das", "dos", "para", "com", "sem", "por", "em", "no",
    "na", "nos", "nas", "e", "ou", "a", "o", "as", "os", "um", "uma", "ao",
    "à", "que", "se", "sua", "seu", "pelo", "pela", "ltda", "me", "epp",
    "servicos", "serviços", "servico", "serviço",
}


def descobrir_red_flags(minimo_ocorrencias: int = 3) -> list[str]:
    """
    Minera os objetos/órgãos das perícias CONFIRMADAS pelo perito atrás de
    bigramas recorrentes que ainda não constam como red flags na base de
    conhecimento. Devolve PROPOSTAS (a inclusão em fraudes_licitacao.py é
    decisão humana) — descoberta automática, adoção deliberada.
    """
    try:
        from compliance_agent.nucleo.memoria_pericial import _conectar
        con = _conectar()
        try:
            linhas = con.execute(
                "SELECT referencia, categoria, orgao FROM pericias"
                " WHERE veredito_perito='confirmado'").fetchall()
        finally:
            con.close()
    except Exception:
        return []
    try:
        from compliance_agent.knowledge.fraudes_licitacao import TODOS_RED_FLAGS
        ja_conhecidas = {flag for flag, _ in TODOS_RED_FLAGS}
    except Exception:
        ja_conhecidas = set()

    contagem: dict[str, int] = {}
    for ref, categoria, orgao in linhas:
        texto = f"{ref or ''} {categoria or ''} {orgao or ''}".lower()
        palavras = [w for w in re.findall(r"[a-záàâãéêíóôõúüç]{3,}", texto)
                    if w not in _STOPWORDS]
        for i in range(len(palavras) - 1):
            bigrama = f"{palavras[i]} {palavras[i+1]}"
            if bigrama not in ja_conhecidas:
                contagem[bigrama] = contagem.get(bigrama, 0) + 1
    return sorted((b for b, n in contagem.items() if n >= minimo_ocorrencias),
                  key=lambda b: -contagem[b])[:20]


# ── Diário de evolução (auditabilidade do loop) ──────────────────────────────

def _registrar_evolucao(rel: RelatorioEvolucao) -> None:
    arq = _arquivo_evolucao()
    arq.parent.mkdir(parents=True, exist_ok=True)
    historico: list = []
    if arq.exists():
        try:
            historico = json.loads(arq.read_text(encoding="utf-8"))
        except Exception:
            historico = []
    historico.append({
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "f1_inicial": rel.placar_inicial.f1_global,
        "f1_final": rel.placar_final.f1_global,
        "falsos_alarmes_inicial": rel.placar_inicial.falsos_alarmes,
        "falsos_alarmes_final": rel.placar_final.falsos_alarmes,
        "mantidos": rel.mantidos,
        "revertidos": rel.revertidos,
        "red_flags_propostas": rel.red_flags_propostas,
    })
    arq.write_text(json.dumps(historico[-100:], ensure_ascii=False, indent=2),
                   encoding="utf-8")


def historico_evolucao() -> list[dict]:
    """Diário completo do autoaprimoramento (para o painel/relatório)."""
    arq = _arquivo_evolucao()
    if not arq.exists():
        return []
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except Exception:
        return []
