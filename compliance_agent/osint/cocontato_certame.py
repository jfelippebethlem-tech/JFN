# -*- coding: utf-8 -*-
"""Dois participantes do MESMO certame atendendo pelo mesmo telefone ou e-mail.

É o teste clássico de bid rigging, e a diferença para tudo o que esta casa já tinha é que aqui não
há hipótese sobre "empresas ligadas": é o **mesmo certame**, com os dois nomes na mesma ata.

MEDIDO EM 2026-08-07: dos 16.509 certames com resultado, **4.517 têm dois ou mais fornecedores
distintos** — 25.562 pares a testar, 5.624 CNPJs. Desses, **33 pares dividem contato** (0,7% dos
certames), e é a taxa que separa: um detector que acendesse em 30% mediria a base, não o alvo.

TRÊS GUARDAS, todas medidas, e nenhuma delas esconde o par — elas o CLASSIFICAM:

  · **filial não é outra empresa** — mesma raiz de CNPJ sai fora, sempre;
  · **contato de serviço não liga ninguém** — telefone ou e-mail usado por mais de 5 empresas do
    conjunto é central de atendimento ou escritório de contabilidade. `burgarellicontabilidade@
    outlook.com` uniu LUGOM e AVANTTE: é `mesmo_contador` (força 0,30), não `mesmo_email` (0,80);
  · **grupo econômico é lícito** — MERCK e SIGMA ALDRICH são o mesmo grupo, e o e-mail é de um
    funcionário da Merck. Isso NÃO absolve: grupo econômico pode existir, o que ele não pode é
    disputar o mesmo certame fingindo concorrência (art. 337-F do Código Penal; Lei 12.529/2011).
    Por isso o par fica, marcado.

O que sobra sem nenhuma explicação é o mais forte que este acervo produz: `SANETAM COMÉRCIO DE
TUBOS` × `HIDROTAM COMÉRCIO DE TUBOS` no mesmo telefone, disputando o mesmo item.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

from compliance_agent.osint.contato_compartilhado import _de_servico

__all__ = ["levantar", "TETO_USO_CONTATO"]

_ESTAB = Path(__file__).resolve().parents[2] / "data" / "receita_estab.db"

# Acima disto o contato é de serviço (central, contabilidade) e não liga ninguém em particular.
# Medido: com teto 5, sobram 33 pares em 4.517 certames; sem teto, o e-mail de uma contabilidade
# uniria todos os clientes dela num cartel imaginário.
TETO_USO_CONTATO = 5

_GENERICAS = frozenset({
    "COMERCIO", "COMERCIAL", "SERVICOS", "SERVICO", "INDUSTRIA", "DISTRIBUIDORA", "SOLUCOES",
    "LTDA", "EIRELI", "IMPORTACAO", "EXPORTACAO", "PRODUTOS", "EQUIPAMENTOS", "MATERIAIS",
})


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z ]", " ", s).upper()


def _marca(razao: str) -> str:
    for p in _norm(razao).split():
        if len(p) >= 4 and p not in _GENERICAS:
            return p
    return ""


def levantar(con: sqlite3.Connection, estab: Path = _ESTAB) -> dict:
    """Pares de participantes do mesmo certame que dividem contato, já classificados."""
    part: dict[str, set[str]] = defaultdict(set)
    nome: dict[str, str] = {}
    objeto: dict[str, str] = {}
    orgao: dict[str, str] = {}
    for cert, doc, nm, obj, org in con.execute(
            "SELECT certame, fornecedor_cnpj, fornecedor_nome, objeto, orgao_nome "
            "FROM pncp_resultado WHERE fornecedor_cnpj IS NOT NULL"):
        d = re.sub(r"\D", "", str(doc or ""))
        if len(d) == 14:
            part[str(cert)].add(d)
            nome[d] = str(nm or "")
            objeto.setdefault(str(cert), str(obj or ""))
            orgao.setdefault(str(cert), str(org or ""))

    multi = {k: v for k, v in part.items() if len(v) > 1}
    alvos = sorted({c for v in multi.values() for c in v})
    if not alvos or not estab.exists():
        return {"certames_com_disputa": len(multi), "pares": [], "erro": "base de contato ausente"}

    est = sqlite3.connect(f"file:{estab}?mode=ro", uri=True)
    tel: dict[str, set[str]] = {}
    mail: dict[str, str] = {}
    razao: dict[str, str] = {}
    try:
        for i in range(0, len(alvos), 900):
            lote = alvos[i:i + 900]
            ph = ",".join("?" * len(lote))
            for cnpj, t1, t2, em in est.execute(
                    f"SELECT cnpj, telefone1, telefone2, correio_eletronico FROM estabelecimentos "
                    f"WHERE cnpj IN ({ph})", lote):
                for t in (t1, t2):
                    t = re.sub(r"\D", "", str(t or ""))
                    if len(t) >= 10:
                        tel.setdefault(cnpj, set()).add(t)
                e = (em or "").strip().lower()
                if e and "@" in e:
                    mail[cnpj] = e
        if est.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='empresas'"
                       ).fetchone():
            raizes = sorted({c[:8] for c in alvos})
            for i in range(0, len(raizes), 900):
                lote = raizes[i:i + 900]
                ph = ",".join("?" * len(lote))
                for r in est.execute(
                        f"SELECT cnpj_basico, razao_social FROM empresas WHERE cnpj_basico IN ({ph})",
                        lote):
                    razao[r[0]] = str(r[1] or "")
    finally:
        est.close()

    uso_mail: dict[str, int] = defaultdict(int)
    for e in mail.values():
        uso_mail[e] += 1
    uso_tel: dict[str, int] = defaultdict(int)
    for s in tel.values():
        for t in s:
            uso_tel[t] += 1

    pares = []
    for cert, cnpjs in multi.items():
        ls = sorted(cnpjs)
        for i in range(len(ls)):
            for j in range(i + 1, len(ls)):
                a, b = ls[i], ls[j]
                if a[:8] == b[:8]:
                    continue                       # filial não é outra empresa
                via, tipo, servico = "", "", False
                if a in mail and b in mail and mail[a] == mail[b]:
                    via, tipo = f"e-mail {mail[a]}", "mesmo_email"
                    # DOIS testes independentes de "contato de serviço": quantas empresas o usam,
                    # e o que o próprio endereço diz. O segundo pegou o que o primeiro não via —
                    # `burgarellicontabilidade@outlook.com`, usado por poucas e ainda assim de um
                    # escritório de contabilidade.
                    servico = uso_mail[mail[a]] > TETO_USO_CONTATO or _de_servico(mail[a])
                else:
                    comum = sorted(tel.get(a, set()) & tel.get(b, set()))
                    if comum:
                        via, tipo = f"telefone {comum[0]}", "mesmo_telefone"
                        servico = uso_tel[comum[0]] > TETO_USO_CONTATO
                if not via:
                    continue
                ma, mb = _marca(razao.get(a[:8], nome.get(a, ""))), \
                    _marca(razao.get(b[:8], nome.get(b, "")))
                pares.append({
                    "certame": cert, "orgao": orgao.get(cert, ""), "objeto": objeto.get(cert, ""),
                    "cnpj_a": a, "nome_a": nome.get(a, ""),
                    "cnpj_b": b, "nome_b": nome.get(b, ""),
                    "via": via, "tipo": "mesmo_contador" if servico else tipo,
                    "contato_de_servico": servico,
                    "mesmo_grupo_aparente": bool(ma and ma == mb), "marca": ma if ma == mb else "",
                })
    pares.sort(key=lambda x: (x["contato_de_servico"], x["mesmo_grupo_aparente"]))
    return {
        "certames_com_disputa": len(multi),
        "cnpjs_participantes": len(alvos),
        "pares": pares,
        "sem_explicacao": sum(1 for p in pares
                              if not p["contato_de_servico"] and not p["mesmo_grupo_aparente"]),
        "contato_de_servico": sum(1 for p in pares if p["contato_de_servico"]),
        "mesmo_grupo_aparente": sum(1 for p in pares if p["mesmo_grupo_aparente"]),
    }
