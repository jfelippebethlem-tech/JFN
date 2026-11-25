# -*- coding: utf-8 -*-
"""RBAC da Esteira Única — papéis, permissões e justificativa (plano mestre v2 §3.11 "RBAC e trilha"; O7.4).

Papéis: `dono`, `analista`, `leitura`, `servico`. A decisão é PURA (sem I/O, contrato `dominio-sem-io`); quem grava a
trilha append-only (`acesso_log`) é `aplicacao/estagios/caso.autorizar`, que registra TODA tentativa — permitida ou
negada — antes de devolver.

REGRA DO DONO: o RBAC NÃO cria usuário nem senha. Os papéis se aplicam às identidades que JÁ existem:
  · sessão do painel (cookie HMAC `jfn_session`, senha única do dono)     → `dono`
  · processo local sem proxy (Yoda/fluxo em 127.0.0.1 — a mesma régua do `server._auth_jfn`) → `servico`
  · terminal interativo do dono na VM (sessão SSH dele)                   → `dono`
  · job da esteira (processo-filho `fluxo.executar`)                       → `servico`
`analista` e `leitura` estão na matriz e nos testes, mas NENHUMA identidade existente mapeia para eles: dar esses
papéis a alguém exige credencial nova ⇒ BLOQUEADO pela regra do dono (ver `PAPEIS_SEM_IDENTIDADE`).

Justificativa obrigatória (§3.11): exportar dossiê e abrir restrito. Ler caso de classe `pessoal`, `restrito` ou
`segredo` É abrir restrito. `segredo` só o dono abre.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Papel(str, Enum):
    DONO = "dono"
    ANALISTA = "analista"
    LEITURA = "leitura"
    SERVICO = "servico"


class Acao(str, Enum):
    LER_CASO = "ler_caso"
    ABRIR_RESTRITO = "abrir_restrito"
    MONTAR_CASO = "montar_caso"
    CONTESTAR = "contestar"
    REVISAR_CONTESTACAO = "revisar_contestacao"
    EXPORTAR_DOSSIE = "exportar_dossie"
    ADMINISTRAR = "administrar"          # ex.: pausar/retomar agenda do fluxo (só dono, §10 do plano)


PERMISSOES: dict[Papel, frozenset[Acao]] = {
    Papel.DONO: frozenset(Acao),
    Papel.ANALISTA: frozenset({Acao.LER_CASO, Acao.ABRIR_RESTRITO, Acao.MONTAR_CASO, Acao.CONTESTAR,
                               Acao.REVISAR_CONTESTACAO, Acao.EXPORTAR_DOSSIE}),
    Papel.LEITURA: frozenset({Acao.LER_CASO}),
    # o serviço monta caso e gera/entrega o dossiê que o dono pediu (com a justificativa do pedido); não contesta,
    # não revisa e não abre restrito — quem decide é pessoa (doc 2 §35.1).
    Papel.SERVICO: frozenset({Acao.LER_CASO, Acao.MONTAR_CASO, Acao.EXPORTAR_DOSSIE}),
}
EXIGE_JUSTIFICATIVA = frozenset({Acao.ABRIR_RESTRITO, Acao.EXPORTAR_DOSSIE})
JUSTIFICATIVA_MIN = 15                     # caracteres úteis: "ok", "teste" ou "." não justificam nada
CLASSES = ("publico", "interno", "pessoal", "restrito", "segredo")
CLASSES_RESTRITAS = frozenset({"pessoal", "restrito", "segredo"})
PAPEIS_SEM_IDENTIDADE = (Papel.ANALISTA, Papel.LEITURA)   # BLOQUEADO: exigiriam usuário/senha novos


@dataclass(frozen=True)
class Principal:
    id: str                                # 'dono:sessao_painel', 'dono:terminal@vm1', 'servico:fluxo@vm2', …
    papel: Papel

    def __post_init__(self):
        if not str(self.id or "").strip():
            raise ValueError("principal sem identificação")
        if not isinstance(self.papel, Papel):
            raise ValueError(f"papel inválido: {self.papel!r}")


@dataclass(frozen=True)
class Decisao:
    permitido: bool
    motivo: str
    exigidas: tuple[str, ...] = field(default_factory=tuple)   # ações efetivamente exigidas (ex.: abrir_restrito)


class AcessoNegado(PermissionError):
    def __init__(self, decisao: Decisao):
        super().__init__(decisao.motivo)
        self.decisao = decisao


def justificativa_valida(texto: str | None) -> bool:
    return len("".join(str(texto or "").split())) >= JUSTIFICATIVA_MIN


def decidir(principal: Principal, acao: Acao, *, justificativa: str | None = "", classe: str = "interno") -> Decisao:
    """Pode? Ler caso de classe restrita vira ABRIR_RESTRITO (com justificativa); `segredo` só o dono."""
    if classe not in CLASSES:
        return Decisao(False, f"classe de dado desconhecida: {classe!r} (falha fechada)")
    exigidas = [acao]
    if acao is Acao.LER_CASO and classe in CLASSES_RESTRITAS:
        exigidas.append(Acao.ABRIR_RESTRITO)
    if classe == "segredo" and principal.papel is not Papel.DONO:
        return Decisao(False, "classe segredo: só o dono abre", tuple(a.value for a in exigidas))
    faltam = [a.value for a in exigidas if a not in PERMISSOES[principal.papel]]
    if faltam:
        return Decisao(False, f"papel {principal.papel.value} não pode: {', '.join(faltam)}",
                       tuple(a.value for a in exigidas))
    if any(a in EXIGE_JUSTIFICATIVA for a in exigidas) and not justificativa_valida(justificativa):
        return Decisao(False, f"{'/'.join(a.value for a in exigidas if a in EXIGE_JUSTIFICATIVA)} exige justificativa "
                              f"(≥ {JUSTIFICATIVA_MIN} caracteres)", tuple(a.value for a in exigidas))
    return Decisao(True, "permitido", tuple(a.value for a in exigidas))


def principal_da_sessao(*, cookie_valido: bool, local_sem_proxy: bool, no: str = "") -> Principal | None:
    """A identidade que a requisição JÁ tem no painel (mesma régua do `server._auth_jfn`): cookie do dono → dono;
    local sem cabeçalho de proxy → serviço; nada → None (o painel já respondeu 401 antes de chegar aqui)."""
    if cookie_valido:
        return Principal("dono:sessao_painel", Papel.DONO)
    if local_sem_proxy:
        return Principal(f"servico:local{'@' + no if no else ''}", Papel.SERVICO)
    return None


def principal_do_processo(*, interativo: bool, dono_do_repo: bool, no: str) -> Principal:
    """CLI/job: terminal interativo do dono (sessão SSH dele) → dono; o resto (fluxo, cron, ssh não interativo) →
    serviço. Nenhuma variável de ambiente promove papel (não há credencial nova a forjar)."""
    if interativo and dono_do_repo:
        return Principal(f"dono:terminal@{no}", Papel.DONO)
    return Principal(f"servico:processo@{no}", Papel.SERVICO)
