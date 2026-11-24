# -*- coding: utf-8 -*-
"""Lote de ingestão e quarentena (O4.11; doc 2 §40.1–40.2).

Registro inválido NÃO some e NÃO derruba a ingestão: vai para `ingestao_quarentena` com o PAYLOAD
ORIGINAL (JSON canônico + sha256), o lote, o motivo e a ação necessária. Cada lote deixa as contagens em
`ingestao_lote`. As duas tabelas nascem pela migração Alembic `0003_ingestao_quarentena`.

Contagens de um lote (invariante conferida em `ContagemLote.fecha`):

    recebidos = aceitos + rejeitados + duplicados + conflitos
    quarentena = rejeitados + conflitos

  • rejeitado  — falhou o contrato (tipo/regex/faixa/domínio/obrigatório) → quarentena, ação `corrigir_parser`
                 (ou `revisar_fonte` quando o defeito é do dado publicado — decisão humana, não do código);
  • duplicado  — mesma chave natural E mesmo conteúdo já visto (no lote ou no banco) → descartado sem perda:
                 o original já está guardado;
  • conflito   — mesma chave natural com conteúdo DIFERENTE → quarentena, ação `reconciliar` (a fonte
                 corrigiu o registro? duas linhas homônimas? — a PK que apagava a OB de outra UG foi isso).

Tudo puro, exceto `gravar_lote` (escreve só nas duas tabelas novas). Reexecutar o mesmo lote é idempotente:
a quarentena tem UNIQUE (fonte, lote, payload_sha256) e o lote é chave primária.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Iterable

from compliance_agent.ingestao.contrato import Fonte, extensoes, validar_registro

ACOES = ("corrigir_parser", "revisar_fonte", "reconciliar")

# Mesmo DDL da migração 0003 (o teste confere que os dois não divergem): usado só em banco de teste.
DDL = """
CREATE TABLE IF NOT EXISTS ingestao_lote (
    lote TEXT PRIMARY KEY,
    fonte TEXT NOT NULL,
    contrato_versao INTEGER NOT NULL,
    parser_versao TEXT,
    iniciado_em TEXT NOT NULL,
    terminado_em TEXT,
    recebidos INTEGER NOT NULL DEFAULT 0,
    aceitos INTEGER NOT NULL DEFAULT 0,
    rejeitados INTEGER NOT NULL DEFAULT 0,
    duplicados INTEGER NOT NULL DEFAULT 0,
    conflitos INTEGER NOT NULL DEFAULT 0,
    quarentena INTEGER NOT NULL DEFAULT 0,
    origem_declarada INTEGER,
    hash_lote TEXT,
    fim_paginacao TEXT,
    extensoes TEXT,
    observacao TEXT
);
CREATE INDEX IF NOT EXISTS ix_ingestao_lote_fonte ON ingestao_lote (fonte, iniciado_em);
CREATE TABLE IF NOT EXISTS ingestao_quarentena (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fonte TEXT NOT NULL,
    lote TEXT NOT NULL,
    chave TEXT,
    payload TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    motivo TEXT NOT NULL,
    acao TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    resolvido_em TEXT,
    resolucao TEXT,
    UNIQUE (fonte, lote, payload_sha256)
);
CREATE INDEX IF NOT EXISTS ix_ingestao_quarentena_aberta ON ingestao_quarentena (fonte, resolvido_em);
"""


def payload_canonico(registro: dict) -> str:
    """JSON canônico do registro como veio (chaves ordenadas, sem ASCII-escape): é o que se guarda."""
    return json.dumps(registro, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def chave_de(fonte: Fonte, registro: dict) -> str | None:
    """Chave natural como texto ('a|b|c'); None se algum componente está vazio (não identifica o registro)."""
    partes = [registro.get(c) for c in fonte.chave_natural]
    if not partes or any(p is None or str(p).strip() == "" for p in partes):
        return None
    return "|".join(str(p).strip() for p in partes)


@dataclass
class ContagemLote:
    recebidos: int = 0
    aceitos: int = 0
    rejeitados: int = 0
    duplicados: int = 0
    conflitos: int = 0
    origem_declarada: int | None = None
    extensoes: set = field(default_factory=set)

    @property
    def quarentena(self) -> int:
        return self.rejeitados + self.conflitos

    @property
    def fecha(self) -> bool:
        return self.recebidos == self.aceitos + self.rejeitados + self.duplicados + self.conflitos

    def como_dict(self) -> dict:
        d = asdict(self)
        d["extensoes"] = sorted(self.extensoes)
        d["quarentena"] = self.quarentena
        return d


@dataclass
class ItemQuarentena:
    chave: str | None
    payload: str
    payload_sha256: str
    motivo: str
    acao: str


@dataclass
class ResultadoLote:
    lote: str
    fonte: str
    contagem: ContagemLote
    aceitos: list[dict]
    quarentena: list[ItemQuarentena]


def processar_lote(fonte_id: str, fonte: Fonte, registros: Iterable[dict], *,
                   ja_existentes: dict[str, str] | None = None, lote: str | None = None,
                   origem_declarada: int | None = None, motivo_da_fonte=None) -> ResultadoLote:
    """Classifica cada registro (puro). `ja_existentes`: chave natural → sha256 do payload já no banco.
    `motivo_da_fonte(motivos) -> bool`: True quando o defeito é do dado publicado (ação `revisar_fonte`)."""
    lote = lote or uuid.uuid4().hex
    existentes = dict(ja_existentes or {})
    cont = ContagemLote(origem_declarada=origem_declarada)
    aceitos: list[dict] = []
    quar: list[ItemQuarentena] = []
    for reg in registros:
        cont.recebidos += 1
        cont.extensoes |= extensoes(fonte, reg)
        bruto = payload_canonico(reg)
        h = sha256(bruto)
        chave = chave_de(fonte, reg)
        motivos = validar_registro(fonte, reg)
        if chave is None:
            motivos = [f"chave natural incompleta ({', '.join(fonte.chave_natural)})"] + motivos
        if motivos:
            cont.rejeitados += 1
            acao = "revisar_fonte" if motivo_da_fonte and motivo_da_fonte(motivos) else "corrigir_parser"
            quar.append(ItemQuarentena(chave, bruto, h, "; ".join(motivos)[:2000], acao))
            continue
        anterior = existentes.get(chave)
        if anterior == h:
            cont.duplicados += 1
            continue
        if anterior is not None:
            cont.conflitos += 1
            quar.append(ItemQuarentena(chave, bruto, h, "mesma chave natural, conteúdo diferente", "reconciliar"))
            continue
        existentes[chave] = h
        cont.aceitos += 1
        aceitos.append(reg)
    return ResultadoLote(lote, fonte_id, cont, aceitos, quar)


def gravar_lote(con: sqlite3.Connection, r: ResultadoLote, *, contrato_versao: int, parser_versao: str = "",
                iniciado_em: str | None = None, fim_paginacao: str | None = None,
                observacao: str | None = None) -> None:
    """Escreve o lote e a quarentena numa transação. Idempotente (lote PK; quarentena UNIQUE)."""
    agora = datetime.now().isoformat(timespec="seconds")
    c = r.contagem
    hash_lote = sha256("".join(sorted(q.payload_sha256 for q in r.quarentena))
                       + "".join(sorted(sha256(payload_canonico(a)) for a in r.aceitos)))
    with con:
        con.execute(
            "INSERT OR REPLACE INTO ingestao_lote (lote, fonte, contrato_versao, parser_versao, iniciado_em, "
            "terminado_em, recebidos, aceitos, rejeitados, duplicados, conflitos, quarentena, origem_declarada, "
            "hash_lote, fim_paginacao, extensoes, observacao) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r.lote, r.fonte, contrato_versao, parser_versao, iniciado_em or agora, agora, c.recebidos, c.aceitos,
             c.rejeitados, c.duplicados, c.conflitos, c.quarentena, c.origem_declarada, hash_lote, fim_paginacao,
             json.dumps(sorted(c.extensoes), ensure_ascii=False), observacao))
        con.executemany(
            "INSERT OR IGNORE INTO ingestao_quarentena (fonte, lote, chave, payload, payload_sha256, motivo, acao, "
            "criado_em) VALUES (?,?,?,?,?,?,?,?)",
            [(r.fonte, r.lote, q.chave, q.payload, q.payload_sha256, q.motivo, q.acao, agora) for q in r.quarentena])


def resolver(con: sqlite3.Connection, item_id: int, resolucao: str) -> bool:
    """Fecha um item da quarentena (reprocessado, descartado com motivo, fonte corrigiu). Nunca apaga."""
    with con:
        n = con.execute("UPDATE ingestao_quarentena SET resolvido_em=?, resolucao=? WHERE id=? AND resolvido_em IS NULL",
                        (datetime.now().isoformat(timespec="seconds"), resolucao, item_id)).rowcount
    return n == 1
