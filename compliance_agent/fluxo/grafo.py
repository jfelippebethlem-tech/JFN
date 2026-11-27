# -*- coding: utf-8 -*-
"""O grafo da Esteira Única: `config/fluxo.yaml` validado por Pydantic no carregamento (plano mestre v2 §3.3, O2.1).

O yaml declara três coisas, e só elas:
  · `estagios` — os 18 tipos de job (E1–E18) com recursos, nós, volta (máquina alternativa), timeout, efeito
    verificável, prioridade, concorrência por fonte/provedor e dependência entre estágios;
  · `fontes` — os nomes de evento que sujam rotinas (vindos de config/propagacao.yaml; a sonda continua lá até a O3);
  · `rotinas` — o que rodava antes da parada, cada uma apontando para o comando legado ATUAL (estágio `legado`,
    compliance_agent/aplicacao/estagios/legado.py), disparada por `agenda` (cron de 5 campos, hora de Brasília) e/ou
    por `evento` (dependências, debounce, intervalo mínimo).

Carregar falha (ErroGrafo/ValidationError) — e o deploy não segue — quando: falta estágio, recurso não existe no
governador, cron inválido, dependência aponta para o nada, rotina sem efeito declarado, ou há CICLO (entre estágios
ou entre rotinas). Sem topologia sensível no yaml (ADR-011): nós são só vm1/vm2/itcampo, comandos relativos à raiz.

Consumidores: o planejador recebe `grafo_planejador()` e `contrato()`; a agenda do PG nasce de `agenda_linhas()`.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from compliance_agent.fluxo.governador import SLOTS_INICIAIS
from compliance_agent.fluxo.planejador import Cron
from compliance_agent.fluxo import fonte_coleta as _fonte_coleta

RAIZ = Path(__file__).resolve().parents[2]
CAMINHO = RAIZ / "config" / "fluxo.yaml"
PREFIXO_LEGADO = "legado:"
ESTAGIOS = tuple(f"E{i}" for i in range(1, 19))
# vagas do governador + capacidades de PRESENÇA do nó (fonte_coleta: o arquivo da coleta está aqui — 26/11/2026)
RECURSOS = frozenset(r for slots in SLOTS_INICIAIS.values() for r in slots) | _fonte_coleta.CAPACIDADES
NOS = frozenset(SLOTS_INICIAIS)
LOG_SEM_PADRAO = r"Traceback \(most recent call last\)"
_RX_ID = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


class ErroGrafo(ValueError):
    """O grafo é inválido (ciclo, referência quebrada): o deploy não segue."""


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Concorrencia(_Base):
    max: int = Field(ge=0)
    motivo: str


class Volta(_Base):
    nos: list[str] = Field(default_factory=list)
    nota: str | None = None
    # recursos que o job pede QUANDO roda num nó da volta (§3.5: GPU do it-campo → CPU da VM-2, mais lento, nunca
    # parado). Sem isto, a volta pede os mesmos recursos do estágio.
    recursos: list[str] | None = None

    @field_validator("nos")
    @classmethod
    def _nos(cls, v):
        fora = sorted(set(v) - NOS)
        if fora:
            raise ValueError(f"nó desconhecido na volta: {fora}")
        return v

    @field_validator("recursos")
    @classmethod
    def _recursos(cls, v):
        return None if v is None else _checar_recursos(v)


class Estagio(_Base):
    tipo: str
    nome: str
    recursos: list[str]
    nos: list[str]
    volta: Volta
    timeout_s: int = Field(gt=0)
    prioridade: int = 100
    efeito: str = Field(min_length=10)
    concorrencia: list[str] = Field(default_factory=list)
    depende: list[str] = Field(default_factory=list)
    sem_itcampo: str | None = None
    ritmo: str | None = None                      # tarefa do guarda de ritmo da assinatura (estágio com LLM)
    # o job espera o estágio a montante (`depende`) que está rodando ou pronto: sem isto o E11 julgaria antes do E8
    # gravar os fatos e o `fatos/mudou` reabriria o laudo — duas chamadas do Opus para o mesmo processo
    espera_montante: bool = False

    @field_validator("recursos")
    @classmethod
    def _recursos(cls, v):
        return _checar_recursos(v)

    @field_validator("nos")
    @classmethod
    def _nos(cls, v):
        return _checar_nos(v)


class Efeito(_Base):
    """Conferência do estágio legado: rc==0 de todos os passos E o que está aqui. `arquivo` = regravado depois do
    início; `log_contem` = a saída DESTA execução casa o regex; `log_sem` = não casa (padrão: traceback). Sem
    `arquivo` nem `log_contem`, `so_rc` diz por que não há prova melhor (dívida declarada, não silêncio)."""
    descricao: str = Field(min_length=10)
    arquivo: str | None = None
    log_contem: str | None = None
    log_sem: str | None = LOG_SEM_PADRAO
    so_rc: str | None = None

    @model_validator(mode="after")
    def _prova(self):
        if not (self.arquivo or self.log_contem or self.so_rc):
            raise ValueError("efeito sem prova: declare arquivo, log_contem ou so_rc (motivo)")
        for rx in (self.log_contem, self.log_sem):
            if rx:
                re.compile(rx)
        if self.arquivo and (self.arquivo.startswith("/") or ".." in Path(self.arquivo).parts):
            raise ValueError(f"efeito.arquivo tem de ser relativo à raiz do repo: {self.arquivo}")
        return self


class AgendaItem(_Base):
    cron: str
    args: list[str] = Field(default_factory=list)

    @field_validator("cron")
    @classmethod
    def _cron(cls, v):
        Cron(v)                                   # levanta ValueError se não for 5 campos válidos
        return v


class Evento(_Base):
    depende: list[str] = Field(min_length=1)
    debounce_s: int = Field(default=0, ge=0)
    intervalo_min_s: int = Field(default=0, ge=0)
    agrupar: bool = True                          # recálculo da base inteira: UM job por rotina, não um por fonte


class Condicao(_Base):
    dia_semana_iso: int = Field(ge=1, le=7)       # 7 = domingo (o `[ "$(date +%u)" = 7 ]` do cron antigo)


class Rotina(_Base):
    estagio: str
    descricao: str = Field(min_length=5)
    comando: list[str] | None = None
    passos: list[list[str]] | None = None
    parar_no_erro: bool = False
    env: dict[str, str] = Field(default_factory=dict)
    carregar_env: bool = False
    path_extra: list[str] = Field(default_factory=list)
    recursos: list[str] | None = None
    nos: list[str] | None = None
    timeout_s: int | None = Field(default=None, gt=0)
    prioridade: int | None = None
    concorrencia: list[str] = Field(default_factory=list)
    ritmo: str | None = None                      # tarefa do guarda de ritmo da assinatura (llm/contingencia)
    volta: Volta | None = None                    # nós alternativos SÓ quando a rotina declara (legado é preso)
    trava: str | None = None
    condicao: Condicao | None = None
    agenda: list[AgendaItem] = Field(default_factory=list)
    evento: Evento | None = None
    efeito: Efeito
    ativa: bool = True
    bloqueio: str | None = None
    substituida_por: str | None = None            # O9.0: estágio NATIVO que faz o trabalho (a rotina fica desligada)
    origem: list[str] = Field(default_factory=list)
    nota: str | None = None

    @field_validator("estagio")
    @classmethod
    def _estagio(cls, v):
        if v not in ESTAGIOS:
            raise ValueError(f"estágio desconhecido: {v}")
        return v

    @field_validator("recursos")
    @classmethod
    def _recursos(cls, v):
        return None if v is None else _checar_recursos(v)

    @field_validator("nos")
    @classmethod
    def _nos(cls, v):
        return None if v is None else _checar_nos(v)

    @model_validator(mode="after")
    def _forma(self):
        if (self.comando is None) == (self.passos is None):
            raise ValueError("declare exatamente um de `comando` ou `passos`")
        for argv in self.argvs():
            if not argv or not all(isinstance(a, str) and a for a in argv):
                raise ValueError("argv vazio")
            if any(a.startswith("/home/") or a.startswith("~/") for a in argv):
                raise ValueError(f"caminho de casa no comando (topologia fora do yaml): {argv}")
        if not self.agenda and self.evento is None:
            raise ValueError("rotina sem gatilho: declare `agenda` e/ou `evento`")
        if not self.ativa and not self.bloqueio:
            raise ValueError("rotina inativa precisa de `bloqueio` (por que não religa)")
        if self.substituida_por is not None and (self.substituida_por not in ESTAGIOS or self.ativa):
            raise ValueError("`substituida_por` = estágio nativo E1–E18, e a rotina substituída fica `ativa: false`")
        if self.trava and (self.trava.startswith("/") or ".." in Path(self.trava).parts):
            raise ValueError("trava tem de ser relativa à raiz do repo")
        return self

    def argvs(self) -> list[list[str]]:
        return [self.comando] if self.comando is not None else list(self.passos or [])


class Duplicacao(_Base):
    mantida: str
    descartadas: list[str]
    motivo: str


class Fora(_Base):
    origem: list[str]
    motivo: str


class Transitorio(_Base):
    """Slot TRANSITÓRIO (decisão D1 do dono, 24/11, antes da O9.0): `slots` de `recurso` num nó onde a §3.4 dá 0,
    SÓ para as `rotinas` listadas, até a onda `transitorio_ate`. A reserva (fila.reservar, `restritos`) recusa o
    slot a qualquer outro tipo; a catraca tests/test_fluxo_o23.py impede a lista de crescer."""
    maquina: str                                  # (não `no`: o YAML 1.1 lê `no:` como booleano)
    recurso: str
    slots: int = Field(ge=1)
    transitorio_ate: str = Field(pattern=r"^O\d+\.\d+$")
    motivo: str = Field(min_length=10)
    rotinas: list[str] = Field(min_length=1)

    @field_validator("maquina")
    @classmethod
    def _no(cls, v):
        _checar_nos([v])
        return v

    @field_validator("recurso")
    @classmethod
    def _recurso(cls, v):
        _checar_recursos([v])
        return v


FORMAS = ("processo", "documento", "aquisicao", "unidade", "detectores", "laudo", "agrupado", "fixo", "citado",
          "achados", "casos")
# forma → estágio cujos N jobs um job `expandir:` cria (no filho: fluxo/expandir.py)
EXPANDE = {"aquisicao": "texto", "detectores": "detectar", "achados": "conferir", "casos": "caso"}
_RX_EVENTO = re.compile(r"^[a-z][a-z0-9_]*/[a-z][a-z0-9_]*$")


class RotaNativa(_Base):
    """Evento de estágio NATIVO (`fonte/tipo`) → job do estágio seguinte. A `forma` diz como o evento vira job
    (planejador.jobs_nativos): `processo` `<tipo>:<processo>` · `documento` `<tipo>:<proc>|<doc>|<sha16>` (sha256 do
    detalhe) · `aquisicao` um job `expandir:texto` que cria um `texto:` por versão binária (texto.jobs_da_aquisicao,
    no filho) · `unidade` `<tipo>:<unidade>:todos` · `detectores` um `expandir:detectar` (detectores da unidade) ·
    `laudo` `conferir:laudo:<processo>` · `agrupado` UM job do tipo (recálculo da base) · `fixo` `<tipo>:<chave>` com
    o `payload` da rota · `citado` `arvore:<processo citado>` até `max_profundidade` saltos de um processo com OB ·
    `achados` um `expandir:conferir` (um conferir por achado da rodada) · `casos` um `expandir:caso` (processos e
    CNPJs que os achados da rodada citam). `max_reaberturas`: a mesma chave do evento mais que N vezes em 24 h é laço
    (descartado, visível na saúde) — a recaptura de tela de WAF não gira para sempre."""
    evento: str
    estagio: str
    forma: str
    debounce_s: int = Field(default=0, ge=0)
    chave: str | None = None
    payload: dict = Field(default_factory=dict)
    max_reaberturas: int | None = Field(default=None, ge=1)
    max_profundidade: int | None = Field(default=None, ge=1)
    nota: str | None = None

    @model_validator(mode="after")
    def _campos(self):
        if (self.forma == "fixo") != bool(self.chave):
            raise ValueError(f"{self.evento}: `chave` é obrigatória na forma fixo (e só nela)")
        if (self.forma == "citado") != (self.max_profundidade is not None):
            raise ValueError(f"{self.evento}: `max_profundidade` é obrigatória na forma citado (e só nela)")
        return self


    @field_validator("evento")
    @classmethod
    def _evento(cls, v):
        if not _RX_EVENTO.match(v):
            raise ValueError(f"evento tem de ser 'fonte/tipo': {v!r}")
        return v

    @field_validator("forma")
    @classmethod
    def _forma(cls, v):
        if v not in FORMAS:
            raise ValueError(f"forma desconhecida {v!r} (válidas: {FORMAS})")
        return v


class AgendaNativa(_Base):
    """Horário de estágio nativo sem evento de entrada (E17 manter, E18 observar). Linha nova entra DESLIGADA na
    agenda do PG (sincronizar_agenda), como as rotinas: religar é a O9.0."""
    id: str
    estagio: str
    cron: str
    payload: dict = Field(default_factory=dict)
    nota: str | None = None

    @field_validator("cron")
    @classmethod
    def _cron(cls, v):
        Cron(v)
        return v

class Nativos(_Base):
    """Encadeamento dos estágios nativos (1.1 da revisão de 25/11): o que cada handler EMITE (a catraca
    tests/test_fluxo_encadeamento.py confere contra o código), as rotas, os terminais e a dívida declarada."""
    emite: dict[str, list[str]] = Field(default_factory=dict)       # Ek → ['fonte/tipo', …]
    rotas: list[RotaNativa] = Field(default_factory=list)
    terminais: dict[str, str] = Field(default_factory=dict)         # 'fonte/tipo' → por que ninguém consome
    sem_consumidor: dict[str, str] = Field(default_factory=dict)    # dívida: fica PENDENTE e a saúde diz BLOQUEADO
    agenda: list[AgendaNativa] = Field(default_factory=list)


class Grafo(_Base):
    versao: int
    nos: list[str]
    concorrencia: dict[str, Concorrencia]
    estagios: dict[str, Estagio]
    fontes: dict[str, str]
    rotinas: dict[str, Rotina]
    duplicacoes: list[Duplicacao] = Field(default_factory=list)
    fora: list[Fora] = Field(default_factory=list)
    transitorios: dict[str, Transitorio] = Field(default_factory=dict)
    nativos: Nativos = Field(default_factory=Nativos)

    @model_validator(mode="after")
    def _coerencia(self):
        erros: list[str] = self._coerencia_nativos()
        for tid, t in self.transitorios.items():
            if SLOTS_INICIAIS.get(t.maquina, {}).get(t.recurso):
                erros.append(f"transitório {tid}: {t.maquina} já tem {t.recurso} na §3.4 — transitório só onde o slot é 0")
            for rid in t.rotinas:
                r = self.rotinas.get(rid)
                if r is None:
                    erros.append(f"transitório {tid}: rotina {rid} não existe")
                    continue
                if r.estagio in self.estagios:
                    c = self.contrato_da_rotina(rid)
                    if t.recurso not in c["recursos"] or c["nos"] != [t.maquina]:
                        erros.append(f"transitório {tid}: {rid} não pede {t.recurso} presa a {t.maquina} (não precisa)")
        if len({t.maquina for t in self.transitorios.values()}) != len(self.transitorios):
            erros.append("um transitório por nó")
        falta = [e for e in ESTAGIOS if e not in self.estagios]
        sobra = [e for e in self.estagios if e not in ESTAGIOS]
        if falta or sobra:
            erros.append(f"estágios: faltam {falta}, sobram {sobra}")
        _checar_nos(self.nos)
        for eid, e in self.estagios.items():
            erros += [f"{eid}: depende de estágio inexistente {d}" for d in e.depende if d not in self.estagios]
            erros += [f"{eid}: concorrência {c} não declarada" for c in e.concorrencia if c not in self.concorrencia]
        for rid, r in self.rotinas.items():
            if not _RX_ID.match(rid):
                erros.append(f"id de rotina inválido: {rid!r}")
            erros += [f"{rid}: concorrência {c} não declarada" for c in r.concorrencia if c not in self.concorrencia]
            if r.evento:
                erros += [f"{rid}: depende de '{d}', que não é fonte nem rotina" for d in r.evento.depende
                          if d not in self.fontes and d not in self.rotinas]
        com_nativo = {r.estagio for r in self.nativos.rotas} | {a.estagio for a in self.nativos.agenda}
        erros += [f"{rid}: substituída por {r.substituida_por}, que não tem estágio nativo (rota ou agenda nativa)"
                  for rid, r in self.rotinas.items() if r.substituida_por and r.substituida_por not in com_nativo]
        for d in self.duplicacoes:
            if d.mantida not in self.rotinas:
                erros.append(f"duplicação: rotina mantida '{d.mantida}' não existe")
        if erros:
            raise ErroGrafo("; ".join(erros))
        ciclo = achar_ciclo({k: v.depende for k, v in self.estagios.items()})
        if ciclo:
            raise ErroGrafo("ciclo de dependência entre estágios: " + " → ".join(ciclo))
        ciclo = achar_ciclo({k: [d for d in (r.evento.depende if r.evento else []) if d in self.rotinas]
                             for k, r in self.rotinas.items()})
        if ciclo:
            raise ErroGrafo("ciclo de dependência entre rotinas: " + " → ".join(ciclo))
        return self

    def _coerencia_nativos(self) -> list[str]:
        """Portão do boot: todo evento que um estágio nativo emite tem consumidor (rota), é terminal declarado ou é
        dívida declarada (`sem_consumidor`) — nunca some calado. Rota aponta para estágio que existe."""
        n, erros = self.nativos, []
        rotas = {r.evento for r in n.rotas}
        for ek, evs in n.emite.items():
            if ek not in ESTAGIOS:
                erros.append(f"nativos.emite: estágio desconhecido {ek}")
            for ev in evs:
                if not _RX_EVENTO.match(ev):
                    erros.append(f"nativos.emite.{ek}: evento tem de ser 'fonte/tipo': {ev!r}")
                elif ev not in rotas and ev not in n.terminais and ev not in n.sem_consumidor:
                    erros.append(f"nativos: {ek} emite {ev}, que não tem consumidor nem é terminal/dívida declarada")
        for ev in sorted(rotas & (set(n.terminais) | set(n.sem_consumidor))):
            erros.append(f"nativos: {ev} tem rota E é terminal/dívida")
        for ev in sorted(set(n.terminais) & set(n.sem_consumidor)):
            erros.append(f"nativos: {ev} é terminal E dívida")
        for r in n.rotas:
            if r.estagio not in ESTAGIOS:
                erros.append(f"nativos: rota {r.evento} → estágio desconhecido {r.estagio}")
            elif r.forma in EXPANDE and self.estagios.get(r.estagio) and \
                    self.estagios[r.estagio].tipo != EXPANDE[r.forma]:
                erros.append(f"nativos: forma {r.forma} só serve ao estágio {EXPANDE[r.forma]} ({r.evento})")
        for a in n.agenda:
            if a.estagio not in ESTAGIOS:
                erros.append(f"nativos.agenda {a.id}: estágio desconhecido {a.estagio}")
            if not _RX_ID.match(a.id) or a.id in self.rotinas:
                erros.append(f"nativos.agenda: id inválido ou igual a rotina: {a.id!r}")
        if len({a.id for a in n.agenda}) != len(n.agenda):
            erros.append("nativos.agenda: id repetido")
        vistos: set[tuple[str, str]] = set()
        for r in n.rotas:
            if (r.evento, r.estagio) in vistos:
                erros.append(f"nativos: rota repetida {r.evento} → {r.estagio}")
            vistos.add((r.evento, r.estagio))
        return erros

    # ── consumidores ──
    def contrato_do_estagio(self, ek: str, *, expansao: bool = False) -> dict:
        """Contrato do job NATIVO do estágio (tipo = `estagios.<Ek>.tipo`). O job `expandir:` só lê o PG e
        enfileira: cpu_leve, em qualquer nó, com a prioridade do estágio que ele alimenta."""
        e = self.estagios[ek]
        if expansao:
            return {"recursos": ["cpu_leve"], "prioridade": e.prioridade, "volta": None, "nos": [],
                    "no_preferido": None, "timeout_s": 600}
        volta = {"nos": list(e.volta.nos), "estagio": ek} if e.volta.nos else None
        if volta and e.volta.recursos:
            volta["recursos"] = list(e.volta.recursos)
        return {"recursos": list(e.recursos), "prioridade": e.prioridade, "volta": volta,
                "nos": list(e.nos), "no_preferido": e.nos[0] if e.nos else None, "timeout_s": e.timeout_s}

    def payload_do_estagio(self, ek: str, *, expansao: bool = False) -> dict:
        """Base do payload do job nativo: `estagio` (portão da liberação, O9.0), `nos` (restrição dura da reserva),
        `concorrencia` (teto por fonte/provedor) e `timeout_s` (teto do subprocesso)."""
        c, e = self.contrato_do_estagio(ek, expansao=expansao), self.estagios[ek]
        p = {"estagio": ek, "timeout_s": c["timeout_s"] + 60}
        if c["nos"]:
            p["nos"] = c["nos"]
        conc = [f"por_fonte:{e.tipo}" if x == "por_fonte" else x for x in e.concorrencia]
        if conc and not expansao:
            p["concorrencia"] = conc
        if e.ritmo and not expansao:              # a reserva segura o job com a porta da assinatura fechada
            p["ritmo"] = e.ritmo
        if e.espera_montante and not expansao:
            p["montante"] = sorted({self.estagios[d].tipo for d in e.depende})
        return p

    def terminais(self, so_ativas: bool = True) -> dict[str, str]:
        """'fonte/tipo' (ou 'fonte/*') → motivo de NINGUÉM consumir, declarado: os terminais dos nativos, e no
        legado a rotina/fonte sem dependente ativo (o fim da cadeia legada, `<rotina>/concluido`)."""
        out = dict(self.nativos.terminais)
        g = self.grafo_planejador(so_ativas)
        for rid in self.rotinas:
            if rid not in g:
                out[f"{rid}/concluido"] = "rotina legada sem dependente ativo (fim da cadeia legada)"
                # o mesmo fim no vocabulário do despachante antigo, que a ponte retransmite do propagacao.db (26/11/2026)
                out[f"{rid}/mudou"] = "rotina legada sem dependente ativo (evento do despachante antigo via ponte)"
        for f in self.fontes:
            if f not in g:
                out[f"{f}/*"] = "fonte legada sem rotina ativa que dependa dela (bloqueio declarado na rotina)"
        return out

    def dividas(self) -> dict[str, str]:
        return dict(self.nativos.sem_consumidor)

    def contrato_da_rotina(self, rid: str) -> dict:
        """`nos` = restrição DURA da reserva; `volta` só existe quando a ROTINA a declara — a rotina legada roda no
        nó em que rodava (compliance.db mora na VM-1) e a volta do estágio só vale quando o estágio for portado (O2.2)."""
        r, e = self.rotinas[rid], self.estagios[self.rotinas[rid].estagio]
        nos = r.nos or e.nos
        # a rotina LEGADA lê o compliance.db vivo no seu nó: herda as vagas do estágio, não a capacidade de presença
        # da cópia só-leitura (fonte_coleta, 26/11/2026) — esta é só dos handlers nativos
        return {"recursos": list(r.recursos or [x for x in e.recursos if x not in _fonte_coleta.CAPACIDADES]),
                "prioridade": r.prioridade if r.prioridade is not None else e.prioridade,
                "volta": {"nos": list(r.volta.nos), "estagio": r.estagio} if r.volta else None,
                "nos": list(nos),
                "no_preferido": nos[0] if nos else None,
                "timeout_s": r.timeout_s or e.timeout_s}

    def concorrencia_da_rotina(self, rid: str) -> list[str]:
        """Etiquetas de teto da rotina (só as da ROTINA: as do estágio descrevem o estágio portado, não o comando
        legado). `por_fonte` vira `por_fonte:<rotina>` — o teto é por fonte, não um global para todas."""
        return [f"por_fonte:{rid}" if c == "por_fonte" else c for c in self.rotinas[rid].concorrencia]

    def montante(self, rid: str) -> list[str]:
        """Tipos de job das rotinas de que esta depende (as fontes ficam de fora: não são jobs)."""
        r = self.rotinas[rid]
        return [tipo_da_rotina(d) for d in (r.evento.depende if r.evento else []) if d in self.rotinas]

    def tetos(self) -> dict[str, int]:
        """Etiqueta de concorrência → máximo de jobs RESERVADOS ao mesmo tempo (todas as máquinas)."""
        return {k: c.max for k, c in self.concorrencia.items()}

    def ritmos(self, so_ativas: bool = True) -> set[str]:
        """Tarefas do guarda de ritmo que o supervisor mede a cada volta: as das rotinas e as dos estágios nativos."""
        return ({r.ritmo for r in self.rotinas.values() if r.ritmo and (r.ativa or not so_ativas)}
                | {e.ritmo for e in self.estagios.values() if e.ritmo})

    def slots_do_no(self, no: str) -> dict[str, int]:
        """Slots da §3.4 do nó MAIS o transitório declarado para ele (D1) — o supervisor sobe com isto."""
        out = dict(SLOTS_INICIAIS.get(no, {}))
        for t in self.transitorios.values():
            if t.maquina == no:
                out[t.recurso] = out.get(t.recurso, 0) + t.slots
        return out

    def restritos_do_no(self, no: str) -> dict[str, list[str]]:
        """recurso transitório do nó → tipos de job que podem usá-lo (fila.reservar recusa os outros)."""
        return {t.recurso: sorted(tipo_da_rotina(r) for r in t.rotinas)
                for t in self.transitorios.values() if t.maquina == no}

    def contrato(self) -> dict[str, dict]:
        """tipo de job → recursos/prioridade/volta/no_preferido (o que o planejador grava em cada job): as rotinas
        legadas, os estágios nativos (tipo do estágio) e os `expandir:<tipo>` das rotas que expandem."""
        out = {tipo_da_rotina(rid): self.contrato_da_rotina(rid) for rid in self.rotinas}
        for ek, e in self.estagios.items():
            out.setdefault(e.tipo, self.contrato_do_estagio(ek))
        for r in self.nativos.rotas:
            if r.forma in EXPANDE:
                out[f"expandir:{self.estagios[r.estagio].tipo}"] = self.contrato_do_estagio(r.estagio, expansao=True)
        return out

    def payload(self, rid: str, args: list[str] | None = None, *, evento: bool = False) -> dict:
        """Payload do job. Leva as restrições que `fila.reservar` aplica: `estagio` (portão da religação — só sai
        quando o estágio estiver em `liberacao`), `nos`, `concorrencia`, `montante` (o dependente espera o derivado a
        montante que está pronto) e `ritmo` — no job de EVENTO e, desde a decisão D2 do dono (24/11), também no da
        AGENDA: o guarda da assinatura vale para as 4 rotinas fundidas inteiras, não só para o lado evento.
        `evento` fica na assinatura para os chamadores (grafo_planejador/agenda_linhas) dizerem de onde vem."""
        c = self.contrato_da_rotina(rid)
        p = {"rotina": rid, "estagio": self.rotinas[rid].estagio, "timeout_s": c["timeout_s"] + 60}
        if args:
            p["args"] = list(args)
        if c["nos"]:
            p["nos"] = c["nos"]
        if conc := self.concorrencia_da_rotina(rid):
            p["concorrencia"] = conc
        if self.rotinas[rid].ritmo:
            p["ritmo"] = self.rotinas[rid].ritmo
        if mont := self.montante(rid):
            p["montante"] = mont
        return p

    def grafo_planejador(self, so_ativas: bool = True) -> dict[str, list[dict]]:
        """fonte do evento → dependentes, no formato de `planejador.propagar_eventos`. O `timeout_s` vai no payload
        porque é dele que o supervisor tira o teto do subprocesso."""
        g: dict[str, list[dict]] = {}
        for rid, r in self.rotinas.items():
            if not r.evento or (so_ativas and not r.ativa):
                continue
            dep = {"tipo": tipo_da_rotina(rid), "debounce_s": r.evento.debounce_s,
                   "intervalo_min_s": r.evento.intervalo_min_s, "agrupar": r.evento.agrupar,
                   "payload": self.payload(rid, evento=True)}
            for fonte in r.evento.depende:
                # evento de DERIVADO (fonte que é rotina) não abre janela de junção (propagacao._sujos)
                g.setdefault(fonte, []).append({**dep, "abre_janela": fonte not in self.rotinas})
        # estágios NATIVOS: a chave é 'fonte/tipo' (o handler emite a fonte curta, ex. arvore/documento_novo)
        for r in self.nativos.rotas:
            e = self.estagios[r.estagio]
            payload = self.payload_do_estagio(r.estagio)
            if r.forma in EXPANDE:                   # o job `expandir:` leva o contrato/payload dos N que ele cria
                payload = {**self.payload_do_estagio(r.estagio, expansao=True),
                           "alvo": {"tipo": e.tipo, "contrato": self.contrato_do_estagio(r.estagio),
                                    "payload": payload}}
            if r.payload:
                payload = {**payload, **r.payload}
            dep = {"tipo": e.tipo, "forma": r.forma, "estagio": r.estagio, "debounce_s": r.debounce_s,
                   "agrupar": r.forma == "agrupado", "abre_janela": True, "payload": payload}
            for k in ("chave", "max_reaberturas", "max_profundidade"):
                if getattr(r, k) is not None:
                    dep[k] = getattr(r, k)
            g.setdefault(r.evento, []).append(dep)
        return g

    def agenda_linhas(self, so_ativas: bool = True) -> list[dict]:
        """Linhas de `fluxo.agenda` (id estável: `<rotina>` ou `<rotina>#<n>` quando há mais de um horário)."""
        out = []
        for rid, r in self.rotinas.items():
            if so_ativas and not r.ativa:
                continue
            for i, item in enumerate(r.agenda):
                out.append({"id": rid if len(r.agenda) == 1 else f"{rid}#{i + 1}", "cron_expr": item.cron,
                            "tipo_job": tipo_da_rotina(rid), "payload": self.payload(rid, item.args)})
        return out

    def agenda_nativa(self) -> list[dict]:
        """Linhas de `fluxo.agenda` dos estágios NATIVOS sem evento de entrada (E17 manter, E18 observar): tipo do
        estágio, payload do estágio + o da linha. `agenda sincronizar` grava as duas listas (linha nova DESLIGADA)."""
        return [{"id": a.id, "cron_expr": a.cron, "tipo_job": self.estagios[a.estagio].tipo,
                 "payload": {**self.payload_do_estagio(a.estagio), **a.payload}} for a in self.nativos.agenda]


def rotinas_sem_slot(g: "Grafo") -> list[tuple[str, list[str], list[str]]]:
    """Rotinas ATIVAS que pedem recurso que nenhum dos seus nós (nos + volta) tem nos slots do governador: com o nó
    como restrição dura na reserva (O2.2) elas nunca rodariam (o planejador as mostraria BLOQUEADO). A rotina coberta
    por um slot TRANSITÓRIO declarado (`transitorios`, decisão D1) tem slot; a catraca tests/test_fluxo_o23.py exige
    a lista vazia e trava o transitório (só as 15 rotinas de navegador legado da VM-1, até a O3.3)."""
    out = []
    for rid, r in g.rotinas.items():
        if not r.ativa or r.estagio not in g.estagios:
            continue
        c = g.contrato_da_rotina(rid)
        nos = list(c["nos"]) + list((c["volta"] or {}).get("nos") or [])
        trans = {(t.maquina, t.recurso) for t in g.transitorios.values() if rid in t.rotinas}
        falta = [x for x in c["recursos"] if x not in _fonte_coleta.CAPACIDADES     # presença: decidida ao vivo
                 and not any(SLOTS_INICIAIS.get(n, {}).get(x) or (n, x) in trans for n in nos)]
        if falta:
            out.append((rid, falta, nos))
    return out


def tipo_da_rotina(rid: str) -> str:
    return f"{PREFIXO_LEGADO}{rid}"


def _checar_recursos(v: list[str]) -> list[str]:
    fora = sorted(set(v) - RECURSOS)
    if not v or fora:
        raise ValueError(f"recurso inexistente no governador: {fora or 'lista vazia'} (válidos: {sorted(RECURSOS)})")
    return v


def _checar_nos(v: list[str]) -> list[str]:
    fora = sorted(set(v) - NOS)
    if fora:
        raise ValueError(f"nó desconhecido: {fora}")
    return v


def achar_ciclo(arestas: dict[str, list[str]]) -> list[str] | None:
    """DFS em três cores; devolve o caminho do primeiro ciclo achado (ex.: ['a', 'b', 'a']) ou None."""
    cor: dict[str, int] = {}

    def visita(n: str, trilha: list[str]) -> list[str] | None:
        if cor.get(n) == 1:
            return trilha[trilha.index(n):] + [n]
        if cor.get(n) == 2:
            return None
        cor[n] = 1
        for d in arestas.get(n, []):
            achado = visita(d, trilha + [n])
            if achado:
                return achado
        cor[n] = 2
        return None

    for n in sorted(arestas):
        achado = visita(n, [])
        if achado:
            return achado
    return None


def validar_dict(dados: dict) -> Grafo:
    return Grafo.model_validate(dados)


class _CarregadorSemDuplicata(yaml.SafeLoader):
    """safe_load que recusa chave repetida no mesmo mapa (25/11/2026: um `timeout_s` acrescentado sobre outro mais
    abaixo ficou calado — valia o último, e o conserto não teve efeito)."""


def _mapa_sem_duplicata(loader, node, deep=False):
    vistas = set()
    for k, _ in node.value:
        chave = loader.construct_object(k, deep=deep)
        if chave in vistas:
            raise ErroGrafo(f"chave duplicada {chave!r} na linha {k.start_mark.line + 1} do yaml")
        vistas.add(chave)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_CarregadorSemDuplicata.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapa_sem_duplicata)


def carregar(caminho: Path | str | None = None) -> Grafo:
    """Lê e valida o yaml. Levanta ErroGrafo/ValidationError — nunca devolve grafo pela metade."""
    dados = yaml.load(Path(caminho or CAMINHO).read_text(encoding="utf-8"), Loader=_CarregadorSemDuplicata) or {}
    return validar_dict(dados)


@lru_cache(maxsize=4)
def carregar_grafo_cache(caminho: str | None = None) -> Grafo:
    return carregar(caminho)


def main(argv: list[str] | None = None) -> int:
    """`python -m compliance_agent.fluxo.grafo [caminho]` — valida e resume (o portão do deploy)."""
    import json
    import sys
    args = argv if argv is not None else sys.argv[1:]
    g = carregar(args[0] if args else None)
    fracos = sorted(rid for rid, r in g.rotinas.items() if not (r.efeito.arquivo or r.efeito.log_contem))
    print(json.dumps({"ok": True, "estagios": len(g.estagios), "rotinas": len(g.rotinas),
                      "ativas": sum(r.ativa for r in g.rotinas.values()),
                      "agenda": len(g.agenda_linhas()), "fontes_com_dependentes": len(g.grafo_planejador()),
                      "sem_slot": [rid for rid, _f, _n in rotinas_sem_slot(g)],
                      "efeito_so_rc": len(fracos), "rotas_nativas": len(g.nativos.rotas),
                      "eventos_sem_consumidor": sorted(g.dividas())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
