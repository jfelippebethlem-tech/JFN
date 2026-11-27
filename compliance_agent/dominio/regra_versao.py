# -*- coding: utf-8 -*-
"""Versão TEMPORAL da regra — `RegraVersao` (plano mestre v2 §4 item 8, O4.8, SOMBRA ⚖️).

O achado registra a versão da regra vigente NA DATA DO FATO (não a de hoje) e a esfera. Nunca crime nem dolo: a
esfera de um achado do JFN é sempre a do controle externo (responsabilização administrativa), e o texto do achado
não qualifica conduta penal nem elemento subjetivo — a catraca `tests/test_o48_regra_temporal.py` confere.

    RegraVersao(rule_id, base_legal, valid_from, valid_until, fonte_sha256, revisado_por, lei, trecho)
    versao_na_data(rule_id, inicio, fim=None, *, lei=None) -> Vigencia

Intervalo de vigência semiaberto: [valid_from, valid_until) — `valid_until` é o primeiro dia em que a versão já
não vale (a 8.666 foi revogada "em 30 de dezembro de 2023", art. 193, II, na redação da LC 198/2023).

O fato pode ter data exata ou só o EXERCÍCIO (o espelho de dispensas do TCE-RJ não tem data): `inicio`/`fim` dão o
intervalo do fato. Só há versão se UMA única versão cobre o intervalo inteiro; se duas leis coexistem no intervalo
(transição 8.666 × 14.133, 01/04/2021 a 29/12/2023) e o regime do contrato não foi informado (`lei=`), a resposta
é INDETERMINADA, com motivo — nunca se escolhe a lei pelo ano corrente.

`fonte_sha256` é o sha256 da cópia da norma em `~/vault/fontes/juridicas/` (md5 do INDICE.md conferido em 24/11);
`trecho` é o texto conferido VERBATIM nessa cópia (o teste refaz a conferência quando a cópia está na máquina).
Regra sem norma específica (sinal estatístico do sistema) tem `lei = "SEM_NORMA"` e `fonte_sha256 = None`: é dito,
não inventado. `revisado_por = "pendente_dono"` até o ✅ ⚖️ do relatório O4.10.

Puro: sem I/O (contrato `dominio-sem-io`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from compliance_agent.dominio.regime import REVOGACAO_8666, VIGENCIA_14133

PENDENTE = "pendente_dono"
ESFERA_RESPONSABILIZACAO = "controle_externo"      # administrativa; nunca penal
SEM_NORMA = "SEM_NORMA"
LEIS_LICITACAO = ("8666", "14133")      # códigos de `dominio.regime.lei_declarada` que a transição separa

SHA_L14133 = "566bf5c12a3cab4191acac4e4f0f8f5d8dd1c62c7ac313a32623783fe61c0ba1"     # L14133.htm (md5 5107e213…)
SHA_L8666 = "3e10a75d2990564215d9f7ddcafdeeab10029c6c84b68c408d776304b7b65b10"      # L8666cons.htm (md5 26a00846…)
SHA_L4320 = "72a25fb14683d0fc0b33e5f84c6e040a1ef7bf81571e8efd325a25558b5b5dff"      # L4320.htm (md5 c8dc41db…)
FONTES = {SHA_L14133: "L14133.htm", SHA_L8666: "L8666cons.htm", SHA_L4320: "L4320.htm"}

VIGENCIA_8666 = date(1993, 6, 22)        # art. 125 "entra em vigor na data de sua publicação" + DOU de 22.6.1993
EXECUCAO_4320 = date(1965, 1, 1)         # art. 114: efeitos "a partir de 1º de janeiro de 1965, quanto às demais
#                                          atividades" (execução da despesa)

# Termos que um achado do JFN nunca usa para qualificar conduta (esfera penal / elemento subjetivo).
_RE_PENAL = re.compile(r"\b(crimes?|criminos[oa]s?|dolos[oa]?|dolo|dolosamente|il[íi]cito\s+penal|"
                       r"peculato|corrup[çc][ãa]o\s+(?:ativa|passiva)|fraude\s+dolosa)\b", re.I)


@dataclass(frozen=True)
class RegraVersao:
    rule_id: str
    base_legal: str
    valid_from: date
    valid_until: date | None
    fonte_sha256: str | None
    revisado_por: str
    lei: str
    trecho: str = ""

    def __post_init__(self) -> None:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError(f"{self.rule_id}: valid_until deve ser posterior a valid_from")
        if (self.lei == SEM_NORMA) != (self.fonte_sha256 is None):
            raise ValueError(f"{self.rule_id}: só regra SEM_NORMA dispensa fonte_sha256 (e ela não tem fonte)")
        if self.fonte_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", self.fonte_sha256):
            raise ValueError(f"{self.rule_id}: fonte_sha256 inválido")
        if not self.revisado_por.strip():
            raise ValueError(f"{self.rule_id}: revisado_por em branco")

    @property
    def versao(self) -> str:
        return f"{self.rule_id}@{self.lei}:{self.valid_from.isoformat()}"

    def cobre(self, inicio: date, fim: date) -> bool:
        return self.valid_from <= inicio and (self.valid_until is None or fim < self.valid_until)

    def toca(self, inicio: date, fim: date) -> bool:
        return self.valid_from <= fim and (self.valid_until is None or inicio < self.valid_until)

    def como_dict(self) -> dict:
        return {"versao": self.versao, "rule_id": self.rule_id, "base_legal": self.base_legal, "lei": self.lei,
                "valid_from": self.valid_from.isoformat(),
                "valid_until": self.valid_until.isoformat() if self.valid_until else None,
                "fonte_sha256": self.fonte_sha256, "revisado_por": self.revisado_por}


@dataclass(frozen=True)
class Vigencia:
    """Resposta de `versao_na_data`: a versão (ou None) + o estado e o motivo — sempre com o intervalo do fato."""
    versao: RegraVersao | None
    estado: str              # 'DETERMINADA' | 'INDETERMINADA' | 'SEM_REGISTRO'
    motivo: str
    inicio: date | None
    fim: date | None

    def como_dict(self) -> dict:
        return {"estado": self.estado, "motivo": self.motivo,
                "data_fato_inicio": self.inicio.isoformat() if self.inicio else None,
                "data_fato_fim": self.fim.isoformat() if self.fim else None,
                **({"regra": self.versao.como_dict()} if self.versao else {})}


def _v(rule_id, base_legal, de, ate, sha, lei, trecho="") -> RegraVersao:
    return RegraVersao(rule_id, base_legal, de, ate, sha, PENDENTE, lei, trecho)


_P4_8666 = ("Lei 8.666/1993, art. 24, I e II (dispensa por valor \"desde que não se refiram a parcelas de uma mesma "
            "obra ou serviço\" / \"de um mesmo serviço, compra ou alienação de maior vulto\")")
_P4_14133 = ("Lei 14.133/2021, art. 75, §1º, I e II (somatório no exercício pela unidade gestora e por objetos de mesma "
             "natureza — mesmo ramo de atividade) e §7º (manutenção de veículos até o valor atualizado fora da soma)")
_TRECHO_75_P1 = ("o somatório da despesa realizada com objetos de mesma natureza, entendidos como tais aqueles relativos "
                 "a contratações no mesmo ramo de atividade")
_TRECHO_24_II = "desde que não se refiram a parcelas de um mesmo serviço, compra ou alienação de maior vulto"
_TRECHO_62 = "O pagamento da despesa só será efetuado quando ordenado após sua regular liquidação"
_SINAL = "sem norma específica — sinal estatístico do sistema (parâmetro do detector; não é enquadramento legal)"


def _fracionamento(rid: str) -> tuple[RegraVersao, ...]:
    return (_v(rid, _P4_8666, VIGENCIA_8666, REVOGACAO_8666, SHA_L8666, "8666", _TRECHO_24_II),
            _v(rid, _P4_14133, VIGENCIA_14133, None, SHA_L14133, "14133", _TRECHO_75_P1))


def _sinal(rid: str) -> tuple[RegraVersao, ...]:
    return (_v(rid, _SINAL, date(2021, 1, 1), None, None, SEM_NORMA),)


# Registro dos detectores do E10 (aplicacao/detectores.MODULOS). Um teste exige uma entrada por detector.
VERSOES: dict[str, tuple[RegraVersao, ...]] = {
    "e10.p4_fracionamento_objeto": _fracionamento("e10.p4_fracionamento_objeto"),
    "e10.candidato_p4_siafe": _fracionamento("e10.candidato_p4_siafe"),
    "e10.p5_emergencia_recorrente": (
        _v("e10.p5_emergencia_recorrente", "Lei 8.666/1993, art. 24, IV (emergência ou calamidade pública)",
           VIGENCIA_8666, REVOGACAO_8666, SHA_L8666, "8666",
           "IV - nos casos de emergência ou de calamidade pública, quando caracterizada urgência de atendimento"),
        _v("e10.p5_emergencia_recorrente", "Lei 14.133/2021, art. 75, VIII (emergência; vedadas a prorrogação e a "
           "recontratação de empresa já contratada com base no inciso)", VIGENCIA_14133, None, SHA_L14133, "14133",
           "vedadas a prorrogação dos respectivos contratos e a recontratação de empresa já contratada com base no "
           "disposto neste inciso")),
    "e10.ob_paga_acima_liquidado": (
        _v("e10.ob_paga_acima_liquidado", "Lei 4.320/1964, arts. 62 e 63 (pagamento só após a regular liquidação, que "
           "verifica o direito adquirido pelo credor)", EXECUCAO_4320, None, SHA_L4320, "4320", _TRECHO_62),),
    "e10.ob_antes_da_liquidacao": (
        _v("e10.ob_antes_da_liquidacao", "Lei 4.320/1964, art. 62 (pagamento só quando ordenado após a regular "
           "liquidação)", EXECUCAO_4320, None, SHA_L4320, "4320", _TRECHO_62),),
    **{rid: _sinal(rid) for rid in (
        "e10.tg_direta_salto", "e10.tg_emergencial_incumbente", "e10.tg_concentracao", "e10.tg_pico_vespera",
        "e10.tg_credor_estreante", "e10.tg_ob_anulada", "e10.tg_tac_aceleracao", "e10.c_sede_fachada",
        "e10.c_concentracao_nicho")},
}


def versao_na_data(rule_id: str, inicio: date | None, fim: date | None = None, *, lei: str | None = None,
                   versoes: dict[str, tuple[RegraVersao, ...]] | None = None) -> Vigencia:
    """A versão de `rule_id` vigente no intervalo do fato [inicio, fim] (fim None = só o dia `inicio`).

    `lei` ('8666', '14133', …) é o regime DO CONTRATO (`dominio.regime`), quando conhecido: desempata a transição.
    Sem data do fato → INDETERMINADA (nunca a data de hoje)."""
    regs = (versoes or VERSOES).get(rule_id)
    if not regs:
        return Vigencia(None, "SEM_REGISTRO", f"{rule_id} sem RegraVersao registrada", inicio, fim)
    if inicio is None:
        return Vigencia(None, "INDETERMINADA", "sem data do fato (não se usa a data de hoje)", None, fim)
    fim = fim or inicio
    if fim < inicio:
        inicio, fim = fim, inicio
    cands = [r for r in regs if r.toca(inicio, fim) and (lei is None or r.lei in (lei, SEM_NORMA))]
    inteiras = [r for r in cands if r.cobre(inicio, fim)]
    if len(inteiras) == 1 and len(cands) == 1:
        return Vigencia(inteiras[0], "DETERMINADA", f"vigente em todo o intervalo do fato ({inteiras[0].lei})",
                        inicio, fim)
    if not cands:
        return Vigencia(None, "INDETERMINADA", "nenhuma versão vigente na data do fato"
                        + (f" para o regime {lei}" if lei else ""), inicio, fim)
    leis = ", ".join(sorted({r.lei for r in cands}))
    return Vigencia(None, "INDETERMINADA", f"mais de uma versão no intervalo do fato ({leis}) e regime do contrato "
                    "não informado — decide-se por contrato (dominio.regime), nunca pelo ano corrente"
                    if lei is None else f"a versão do regime {lei} não cobre o intervalo inteiro do fato", inicio, fim)


def intervalo_do_exercicio(exercicio: int | None) -> tuple[date | None, date | None]:
    """Fato conhecido só pelo exercício: [01/01, 31/12] do ano (precisão declarada no achado)."""
    if not exercicio:
        return None, None
    return date(int(exercicio), 1, 1), date(int(exercicio), 12, 31)


def texto_penal(texto: str | None) -> list[str]:
    """Termos de esfera penal ou de elemento subjetivo no texto (deve ser vazio em todo achado)."""
    return sorted({m.group(0).lower() for m in _RE_PENAL.finditer(texto or "")})
