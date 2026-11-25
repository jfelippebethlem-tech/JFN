# -*- coding: utf-8 -*-
"""O8.5 — ensaio ponta a ponta EM SEQUÊNCIA sobre o snapshot da parada (plano mestre v2 §1.1, §3.2, §11, §19).

Dono, 24/11/2026: "pra tudo ficar perfeito e em fluxo, um não deveria ser feito depois do outro?" e "não queremos no
final sobreposição de esforços e leitura das mesmas informações e documentos várias vezes como acontecia".

O QUE O ENSAIO PROVA. E1 → E18 rodam UM DEPOIS DO OUTRO; cada estágio consome a SAÍDA REAL do anterior — os EVENTOS
que o estágio anterior gravou no outbox (`eventos` do esquema de fluxo do ensaio) viram os jobs do seguinte — e não
fixture. Cada job passa pelo motor real (`fluxo.fila`: enfileirar idempotente pela chave → reservar → processo-filho
`fluxo.executar rodar` → filho `conferir` → `concluir`/`falhar`), com o handler REAL de `aplicacao/estagios/`. Cada
passagem grava `data/ensaio_o85/<run>/passagem_Ek.json`: entradas (eventos consumidos por fonte/tipo), jobs criados,
juntados pela chave e já existentes, estado final de cada job (feito = efeito CONFERIDO noutro processo;
falhou_efeito; quarentena; ABSTEVE), eventos emitidos, leituras, tempo. Contagens: o que sai de Ek = o que Ek+1
recebeu, ou a diferença com o motivo gravado (`SEM_ROTA`).

ISOLAMENTO (o banco vivo nunca é escrito). PG `jfn_evidencias` da VM-2, esquemas próprios `ensaio_o85_<run>_*`
(fluxo, captura/texto, fatos, domínio E9, sombra E10/E11/E14) — o código recusa qualquer outro nome; o `fluxo` de
produção e o `public` não são tocados. A coleta do ensaio é um SQLite próprio (`<run>/compliance.db`), que o E1
monta a partir do extrato do snapshot (`entrada/replay_fonte.db`, md5 conferido); o `compliance.db` vivo da VM-1 não
é aberto. Visões, laterais de texto, cópias "arquivadas", trace e cache de LLM: tudo dentro de `<run>/`.

SEM REDE NO E1/E2/E3 (portão de egress + parada de obras). Modo REPLAY:
  · E1 `coletar:replay` — copia o extrato do snapshot para a coleta do ensaio (INSERT OR IGNORE pela chave da linha):
    aceitos / já presentes / quarentena (OB sem chave), efeito = recontagem + sha256 das linhas; não existe handler de
    E1 nativo (o `legado:<coletor>` iria à rede) — este replay é do orquestrador e está declarado assim;
  · E2/E3 — os handlers reais com o navegador trocado por `NavegadorReplay` (a árvore e os PDFs do acervo já
    capturado, `entrada/acervo/integra_<pasta>`); "baixar" = copiar para `<run>/sei_cache` (conta como download);
  · E7 — o destino da porta única (rclone/Drive) trocado por `DestinoEnsaio` (pasta local `<run>/frio`, md5 no
    índice próprio); a fila legada de OCR da VM não entra no universo (vazia).

LLM. Créditos pagos proibidos sem o dono (livro `config/llm_autorizacoes_pagas.yaml` vazio — não é tocado) e a
assinatura contida até sáb 28/11/2026 19h. SEM `--com-llm`: o gateway é trocado por uma recusa (`SemProvedor`) e os
backends por sentinelas; E8 fatos, E11 perícia e E12 conferência usam só o que já existe para a mesma chave (o E8 recebe
`docs_lidos` do piloto pelo sha do texto) e o resto vira `ABSTEVE(sem_llm_no_ensaio)` contado — nunca "feito".
`--com-llm` recusa antes de 28/11/2026 19h (BRT), como `tools/ocr_ouro_revisao_ia.py`.

LEITURA ÚNICA. O filho roda com `JFN_LEITURAS_REGISTRAR=1` (`compliance_agent/fluxo/leituras.py`): download, PDF
aberto, texto do acervo, página de OCR e chamada de LLM concluída ficam no `leitura_registro` do esquema de fluxo do
ensaio, com a etiqueta `<run>:p<passada>`. Aceite: (a) cada (estágio, tipo, sha, versão) lido por no máximo 1 job;
(b) a 2ª passada seguida = 0 leitura, 0 download, 0 LLM; (c) o sensor E18 `leitura.repetida_pct` (SLO 0) mede.

ONDE RODA. `obpaga` e `extrair` leem o snapshot na VM-1 (só leitura, `immutable=1`, com nice/ionice); `candidatos`,
`triagem`, `sortear` e `rodar` na VM-2 (PG + 2 vCPU; um pesado por vez). O DSN vem do ambiente
(`python -m compliance_agent.credenciais com JFN_EVIDENCIAS_DSN -- …`), nunca de arquivo copiado.

CLI:
    python -m tools.ensaio_o85 obpaga                                                                # VM-1
    python -m tools.ensaio_o85 candidatos [--sei-cache DIR ...]                                      # VM-2
    python -m tools.ensaio_o85 triagem    --entrada data/ensaio_o85/entrada                          # VM-2
    python -m tools.ensaio_o85 sortear    --entrada data/ensaio_o85/entrada [--n 30] [--semente 85]  # VM-2
    python -m tools.ensaio_o85 extrair    --entrada data/ensaio_o85/entrada                          # VM-1
    python -m tools.ensaio_o85 rodar      --run r1 --passada 1 [--forcar] [--com-llm]                # VM-2
    python -m tools.ensaio_o85 relatorio  --run r1                                                   # VM-2
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

BASE = RAIZ / "data" / "ensaio_o85"
SNAPSHOT = Path.home() / "snapshot-20261124" / "compliance.db"
SNAPSHOT_MD5 = "b20799beee1cb0a130689ccec1665ca2"            # ~/snapshot-20261124/MD5SUMS
PREFIXO = "ensaio_o85"
SEMENTE = 85
NO = "vm2"
BRT = timezone(timedelta(hours=-3))
LIBERADO_LLM_EM = datetime(2026, 11, 28, 19, 0, tzinfo=BRT)  # virada do ritmo semanal da assinatura
OCR_SITE = Path.home() / "ocr-reserva" / ".venv" / "lib" / "python3.12" / "site-packages"   # RapidOCR da VM-2
LIVRES = {r: 99 for r in ("cpu_leve", "cpu_pesado", "navegador", "disco", "llm", "materializar", "gpu")}
TIMEOUT_FILHO_S = 4 * 3600
ESTAGIOS_LLM = ("fatos", "periciar", "conferir")

# ══ 0. universo: amostra estratificada e extrato do snapshot (só leitura) ══════════════════════════════════════════
MAX_DOCS = 85
MAX_MB = 130.0


def _ro(caminho: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{caminho}?mode=ro&immutable=1", uri=True)


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _data_iso(dmy: str | None) -> str | None:
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", str(dmy or ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def pastas_completas(sei_cache: Path, max_docs: int = MAX_DOCS, max_mb: float = MAX_MB) -> list[dict]:
    """Capturas do acervo com manifesto `completo`, TODO documento com arquivo no disco, até `max_docs` e `max_mb`."""
    out = []
    for d in sorted(sei_cache.glob("integra_*")):
        try:
            man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(man, dict) or not man.get("completo"):
            continue
        docs = [x for x in man.get("docs") or [] if isinstance(x, dict)]
        if not docs or len(docs) > max_docs:
            continue
        arqs = [d / str(x.get("arquivo") or "_") for x in docs]
        if not all(x.get("ok") and a.is_file() for x, a in zip(docs, arqs)):
            continue
        mb = sum(a.stat().st_size for a in arqs) / 1e6
        if mb <= max_mb:
            out.append({"pasta": d.name, "processo_manifesto": man.get("processo"), "docs": len(docs),
                        "mb": round(mb, 2)})
    return out


def ob_paga_por_processo(fonte: sqlite3.Connection, processos: set[str]) -> dict[str, dict]:
    """OB PAGA (régua `_ob_paga`) por processo canônico: n, R$, e se há OB emitida no período Couto."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    from compliance_agent.dominio import processo_id as PI
    from compliance_agent.governo_couto import INICIO
    out: dict[str, dict] = {}
    for proc, valor, emissao in fonte.execute(
            f"SELECT processo, valor, data_emissao FROM ob_orcamentaria_siafe WHERE {_ob_paga(fonte)}"):
        k = PI.chave_processo(proc or "")
        if k not in processos:
            continue
        o = out.setdefault(k, {"n_ob": 0, "pago": 0.0, "couto": False})
        o["n_ob"] += 1
        o["pago"] += float(valor or 0)
        o["couto"] = o["couto"] or (_data_iso(emissao) or "") >= INICIO
    return out


def cmd_obpaga(a) -> int:
    """VM-1: OB PAGA por processo canônico do snapshot inteiro (só leitura) → `entrada/ob_paga.json`."""
    if _md5(Path(a.snapshot)) != SNAPSHOT_MD5:
        print("md5 do snapshot NÃO confere com ~/snapshot-20261124/MD5SUMS — recuso", file=sys.stderr)
        return 3

    class Todos(set):
        def __contains__(self, k):
            return bool(k) and not str(k).startswith("PCRJ")
    con = _ro(Path(a.snapshot))
    try:
        obs = ob_paga_por_processo(con, Todos())
    finally:
        con.close()
    Path(a.saida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.saida).write_text(json.dumps({"snapshot_md5": SNAPSHOT_MD5, "processos": obs}), encoding="utf-8")
    print(json.dumps({"processos_com_ob_paga": len(obs), "com_ob_no_periodo_couto": sum(o["couto"] for o in
                                                                                         obs.values())}))
    return 0


def cmd_candidatos(a) -> int:
    """Capturas COMPLETAS do acervo do ensaio (todo PDF no disco) cujo processo tem OB paga no snapshot."""
    from compliance_agent.dominio import processo_id as PI
    ob = json.loads(Path(a.ob_paga).read_text(encoding="utf-8"))
    if ob.get("snapshot_md5") != SNAPSHOT_MD5:
        print("ob_paga.json não é do snapshot da parada — recuso", file=sys.stderr)
        return 3
    cands = []
    for raiz in a.sei_cache:
        cands += pastas_completas(Path(raiz))
    for c in cands:
        c["processo"] = PI.chave_processo(c["processo_manifesto"] or c["pasta"].replace("integra_", ""))
    cands = [c for c in cands if c["processo"] and not c["processo"].startswith(PI.PREFIXO_PCRJ)]
    obs = ob["processos"]
    for c in cands:
        c.update(obs.get(c["processo"]) or {"n_ob": 0, "pago": 0.0, "couto": False})
    com_ob = [c for c in cands if c["n_ob"] > 0]
    saida = Path(a.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps({"snapshot_md5": SNAPSHOT_MD5, "criterio": {"max_docs": MAX_DOCS, "max_mb": MAX_MB,
                                 "completo": True, "ob_paga_siafe": True}, "total_pastas": len(cands),
                                 "candidatos": com_ob}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"pastas_completas": len(cands), "com_ob_paga": len(com_ob),
                      "couto": sum(c["couto"] for c in com_ob)}, ensure_ascii=False))
    return 0


def paginas_escaneadas(pdf: Path) -> tuple[int, int]:
    """(páginas, páginas que o E4 mandaria ao OCR) — o MESMO critério do E4 (`texto.extrair`)."""
    from compliance_agent.aplicacao.estagios import texto as T
    ex = T.extrair(pdf)
    return len(ex["paginas"]), sum(1 for p in ex["paginas"] if p["perfil"] == T.ESCANEADA)


def cmd_triagem(a) -> int:
    """Conta páginas e páginas escaneadas por candidato (só para o custo do OCR caber na VM-2; fora do registro de
    leituras do ensaio — é a preparação do universo, declarada no relatório)."""
    ent = Path(a.entrada)
    arq = ent / "candidatos.json"
    d = json.loads(arq.read_text(encoding="utf-8"))
    for c in d["candidatos"]:
        pasta = ent / "acervo" / c["pasta"]
        man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
        pags = esc = 0
        for x in man["docs"]:
            p, e = paginas_escaneadas(pasta / x["arquivo"])
            pags, esc = pags + p, esc + e
        c["paginas"], c["escaneadas"] = pags, esc
    arq.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"candidatos": len(d["candidatos"]), "paginas": sum(c["paginas"] for c in d["candidatos"]),
                      "escaneadas": sum(c["escaneadas"] for c in d["candidatos"])}))
    return 0


def sortear(cands: list[dict], n: int, semente: int = SEMENTE, max_escaneadas: int = 40) -> list[dict]:
    """Amostra ESTRATIFICADA e reprodutível: metade com OB paga no período Couto, metade sem; ordem = sha256(semente |
    processo) (não depende da ordem de entrada); teto de páginas escaneadas no total (o OCR na CPU da VM-2 faz ~1,6
    pág/min). Pura."""
    def ordem(c):
        return hashlib.sha256(f"{semente}|{c['processo']}".encode()).hexdigest()
    alvo = {True: (n + 1) // 2, False: n // 2}
    filas = {e: sorted((c for c in cands if bool(c.get("couto")) is e), key=ordem) for e in (True, False)}
    escolhidos: list[dict] = []
    k = {True: 0, False: 0}
    esc = 0
    while any(filas.values()):                     # um de cada estrato por vez: o teto de OCR não fica só num deles
        for estrato in (True, False):
            if not filas[estrato] or k[estrato] >= alvo[estrato]:
                filas[estrato] = [] if k[estrato] >= alvo[estrato] else filas[estrato]
                continue
            c = filas[estrato].pop(0)
            if esc + int(c.get("escaneadas") or 0) > max_escaneadas:
                continue
            escolhidos.append({**c, "estrato": "couto" if estrato else "antes_couto"})
            esc += int(c.get("escaneadas") or 0)
            k[estrato] += 1
    return escolhidos


def cmd_sortear(a) -> int:
    ent = Path(a.entrada)
    d = json.loads((ent / "candidatos.json").read_text(encoding="utf-8"))
    am = sortear(d["candidatos"], a.n, a.semente, a.max_escaneadas)
    corpo = {"semente": a.semente, "n_pedido": a.n, "max_escaneadas": a.max_escaneadas, "n": len(am),
             "por_estrato": {e: sum(1 for x in am if x["estrato"] == e) for e in ("couto", "antes_couto")},
             "documentos": sum(x["docs"] for x in am), "paginas": sum(x.get("paginas", 0) for x in am),
             "escaneadas": sum(x.get("escaneadas", 0) for x in am), "amostra": am}
    (ent / "amostra.json").write_text(json.dumps(corpo, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in corpo.items() if k != "amostra"}, ensure_ascii=False))
    return 0


# Tabelas do extrato: (tabela, filtro). Filtro = como a linha entra no recorte da amostra. Tudo o mais fica de fora
# (e o relatório diz que ficou): o E9/E10/E13/E16 rodam sobre o RECORTE, não sobre o Estado inteiro.
TETO_POR_CREDOR = 20_000
EXTRATO = (
    ("ob_orcamentaria_siafe", "processo_ou_credor"), ("ob_reemitida", "tudo"), ("nl_siafe", "nl_das_obs"),
    ("ne_siafe", "ne_das_nls"), ("vinculo_ob_contrato", "ob_das_obs"), ("empresas_cadastro", "cnpj_basico"),
    ("contratos_tcerj", "cnpj"), ("compras_diretas_tcerj", "processo"), ("siga_contratos", "cnpj"),
    ("contratos", "tudo"), ("contrato_aditivo", "processo"), ("ordens_bancarias", "favorecido"),
    ("doerj_tac", "cnpj"), ("verificacao_sede", "cnpj"), ("verificacao_sede_real", "cnpj"),
    ("endereco_verificacao", "cnpj"), ("fachada_veredito", "tudo"), ("alertas_triagem", "conferidos"),
    ("alertas", "alertas_conferidos"), ("despesa_execucao", "ug_das_obs"), ("siafe_fracionamento", "credor"),
    ("favorecido_resumo", "favorecido"), ("pcrj_contratos", "nada"),
)


def _dig(x) -> str:
    return re.sub(r"\D", "", str(x or ""))


def extrair_fonte(src: sqlite3.Connection, destino: Path, processos: set[str]) -> dict:
    """Recorte do snapshot para a amostra → SQLite novo com o MESMO esquema (CREATE TABLE/INDEX do snapshot)."""
    from compliance_agent.dominio import processo_id as PI
    if destino.exists():
        destino.unlink()
    dst = sqlite3.connect(destino)
    rel: dict = {}
    obs_rowids: list[int] = []
    # ob-qualquer-status: replay do E1 copia a coleta BRUTA; o filtro de OB paga vem depois, nos estágios
    for rowid, proc in src.execute("SELECT rowid, processo FROM ob_orcamentaria_siafe"):
        if PI.chave_processo(proc or "") in processos:
            obs_rowids.append(rowid)
    credores: set[str] = set()
    # ob-qualquer-status: só seleciona os credores da amostra (nenhuma soma de valor)
    for (cr,) in src.execute(f"SELECT DISTINCT credor FROM ob_orcamentaria_siafe WHERE rowid IN "
                             f"({','.join(map(str, obs_rowids)) or 'NULL'})"):
        if _dig(cr):
            credores.add(_dig(cr))
    por_credor: list[int] = []
    for cr in sorted(credores):
        # ob-qualquer-status: cópia bruta para o replay; ORDER BY rowid = a mesma amostra em toda execução
        por_credor += [r for (r,) in src.execute("SELECT rowid FROM ob_orcamentaria_siafe WHERE credor = ? AND "
                                                 "exercicio >= 2025 ORDER BY rowid LIMIT ?", (cr, TETO_POR_CREDOR))]
    ob_ids = sorted(set(obs_rowids) | set(por_credor))
    ctx: dict = {"credores": credores, "basicos": {c[:8] for c in credores if len(c) == 14}}

    def cria(t: str) -> list[str]:
        sql = src.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (t,)).fetchone()
        if not sql:
            return []
        dst.execute(sql[0])
        for (ix,) in src.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS "
                                 "NOT NULL", (t,)):
            dst.execute(ix)
        return [r[1] for r in src.execute(f'PRAGMA table_info("{t}")')]

    def copia(t: str, cols: list[str], linhas) -> int:
        q = f'INSERT INTO "{t}"({",".join(chr(34) + c + chr(34) for c in cols)}) VALUES ({",".join("?" * len(cols))})'
        n = 0
        lote = []
        for r in linhas:
            lote.append(r)
            if len(lote) >= 5000:
                dst.executemany(q, lote)
                n += len(lote)
                lote = []
        if lote:
            dst.executemany(q, lote)
            n += len(lote)
        return n

    for t, filtro in EXTRATO:
        cols = cria(t)
        if not cols:
            rel[t] = {"filtro": filtro, "linhas": None, "motivo": "tabela ausente no snapshot"}
            continue
        sel = ",".join(f'"{c}"' for c in cols)
        if filtro == "nada":
            linhas = iter(())
        elif filtro == "tudo":
            linhas = src.execute(f'SELECT {sel} FROM "{t}"')
        elif filtro == "processo_ou_credor":
            linhas = (r for i in range(0, len(ob_ids), 900) for r in src.execute(
                f'SELECT {sel} FROM "{t}" WHERE rowid IN ({",".join(map(str, ob_ids[i:i + 900]))})'))
            linhas = list(linhas)
            ix = {c: k for k, c in enumerate(cols)}
            ctx["nls"] = {(str(r[ix["nl"]] or ""), str(r[ix["ug_emitente"]] or "")) for r in linhas if r[ix["nl"]]}
            ctx["obs"] = {str(r[ix["numero_ob"]] or "") for r in linhas}
            ctx["ugs"] = {str(r[ix["ug_emitente"]] or "") for r in linhas}
        elif filtro == "nl_das_obs":
            nums = {n for n, _ in ctx.get("nls", ())}
            linhas = [r for r in src.execute(f'SELECT {sel} FROM "{t}"') if str(r[cols.index("numero")]) in nums]
            ctx["nes"] = {str(r[cols.index("ne")] or "") for r in linhas if r[cols.index("ne")]}
        elif filtro == "ne_das_nls":
            linhas = [r for r in src.execute(f'SELECT {sel} FROM "{t}"') if str(r[cols.index("numero")]) in
                      ctx.get("nes", set())]
        elif filtro == "ob_das_obs":
            linhas = [r for r in src.execute(f'SELECT {sel} FROM "{t}"') if str(r[cols.index("ob")]) in
                      ctx.get("obs", set())]
        elif filtro == "ug_das_obs":
            linhas = [r for r in src.execute(f'SELECT {sel} FROM "{t}"') if str(r[cols.index("ug")]) in
                      ctx.get("ugs", set())]
        elif filtro == "cnpj_basico":
            linhas = [r for r in src.execute(f'SELECT {sel} FROM "{t}"') if _dig(r[cols.index("cnpj_basico")]) in
                      ctx["basicos"]]
        elif filtro in ("cnpj", "credor", "favorecido"):
            col = {"cnpj": "cnpj", "credor": "credor", "favorecido": "favorecido_cpf"}[filtro]
            if t == "ordens_bancarias":
                linhas = [r for cr in sorted(credores) for r in src.execute(
                    f'SELECT {sel} FROM "{t}" WHERE "{col}" = ? LIMIT ?', (cr, TETO_POR_CREDOR))]
            else:
                linhas = [r for r in src.execute(f'SELECT {sel} FROM "{t}"') if _dig(r[cols.index(col)]) in credores]
        elif filtro == "processo":
            pcol = "processo"
            linhas = [r for r in src.execute(f'SELECT {sel} FROM "{t}"')
                      if PI.chave_processo(str(r[cols.index(pcol)] or "")) in processos]
        elif filtro == "conferidos":
            linhas = list(src.execute(f'SELECT {sel} FROM "{t}" WHERE leitura_opus IS NOT NULL AND leitura_opus <> ""'))
            ctx["alertas"] = {r[cols.index("alerta_id")] for r in linhas}
        elif filtro == "alertas_conferidos":
            ids = sorted(ctx.get("alertas", ()))
            linhas = [r for i in range(0, len(ids), 900) for r in src.execute(
                f'SELECT {sel} FROM "{t}" WHERE id IN ({",".join("?" * len(ids[i:i + 900]))})', ids[i:i + 900])]
        else:
            raise ValueError(filtro)
        rel[t] = {"filtro": filtro, "linhas": copia(t, cols, linhas)}
    dst.commit()
    dst.close()
    rel["_recorte"] = {"processos": len(processos), "obs_dos_processos": len(obs_rowids), "credores": len(credores),
                       "obs_por_credor_desde_2025": len(set(por_credor) - set(obs_rowids)),
                       "teto_por_credor": TETO_POR_CREDOR}
    return rel


def cmd_extrair(a) -> int:
    ent = Path(a.entrada)
    am = json.loads((ent / "amostra.json").read_text(encoding="utf-8"))
    if _md5(Path(a.snapshot)) != SNAPSHOT_MD5:
        print("md5 do snapshot NÃO confere — recuso", file=sys.stderr)
        return 3
    src = _ro(Path(a.snapshot))
    try:
        rel = extrair_fonte(src, ent / "replay_fonte.db", {x["processo"] for x in am["amostra"]})
    finally:
        src.close()
    rel["_md5"] = _md5(ent / "replay_fonte.db")
    rel["_snapshot_md5"] = SNAPSHOT_MD5
    (ent / "replay_fonte.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rel, ensure_ascii=False))
    return 0


# ══ 1. replay: navegador do acervo e destino local (instalados SÓ no processo-filho do ensaio) ═════════════════════
ENV_CFG = "JFN_ENSAIO_O85"


class NavegadorReplay:
    """A árvore e a captura do acervo já capturado (sem rede). Mesmo contrato do `arvore.Navegador`."""

    def __init__(self, acervo: Path):
        self.acervo = Path(acervo)

    def _pasta(self, processo: str) -> Path:
        from compliance_agent.dominio import processo_id as PI
        return self.acervo / f"integra_{PI.pasta(processo)}"

    def _man(self, processo: str) -> dict:
        return json.loads((self._pasta(processo) / "manifest.json").read_text(encoding="utf-8"))

    def arvore(self, processo: str, pagina: int):
        from compliance_agent.aplicacao.estagios import arvore as A
        if pagina:
            raise ValueError("o replay devolve a árvore inteira na página 0")
        try:
            man = self._man(processo)
        except (OSError, ValueError):
            return A.PaginaArvore(docs=[], via="replay:sem_acervo", sem_resultado=True)
        docs = [{"t": d.get("titulo") or "", "u": d.get("url") or "", "restrito": False}
                for d in man.get("docs") or [] if isinstance(d, dict) and d.get("url")]
        return A.PaginaArvore(docs=docs, via="replay:acervo")

    def capturar(self, processo: str, guardados: dict, raiz: Path) -> Path:
        """Delta como o real: o MESMO encaixe do `sei_integra_completa` (`captura_delta.encaixe`) com a chave do E3
        (`JFN_E3_DELTA` → `modo_e3()`: desligada = sombra, copia tudo; `=1` só "baixa" (copia) o não guardado)."""
        from compliance_agent import captura_delta as CD
        from compliance_agent.dominio import processo_id as PI
        from compliance_agent.fluxo import leituras
        src = self._pasta(processo)
        man = self._man(processo)
        out = Path(raiz) / src.name
        out.mkdir(parents=True, exist_ok=True)
        ent = [e for e in man.get("docs") or [] if isinstance(e, dict)]
        gd = Path(raiz) / "_guardados_delta"      # onde o real grava (captura_delta.GUARDADOS_DIR), aqui no run
        gd.mkdir(parents=True, exist_ok=True)
        (gd / f"{PI.pasta(processo)}.json").write_text(json.dumps(guardados, ensure_ascii=False), encoding="utf-8")
        pular, _reg = CD.encaixe(PI.pasta(processo), [{"t": e.get("titulo", ""), "u": e.get("url", "")} for e in ent],
                                 env={"JFN_CAPTURA_DELTA": CD.modo_e3()}, pasta_exportados=gd, arquivo=gd / "_sem")
        baixados = mantidos = ligados = 0
        ja: dict[str, Path] = {}                 # sha256 → 1º destino NESTE job (anexo repetido em 2 documentos)
        for i, e in enumerate(ent):
            alvo = out / str(e.get("arquivo") or "")
            if i in pular:
                mantidos += 1
                continue
            if e.get("ok") and (src / str(e.get("arquivo") or "_")).is_file():
                sha = leituras.sha_arquivo(src / e["arquivo"])
                if sha in ja:                    # mesmos bytes: link do 1º (cada documento tem o seu arquivo), sem
                    alvo.unlink(missing_ok=True)  # 2º download — o E7 pode apagar um sem afetar o outro
                    os.link(ja[sha], alvo)
                    ligados += 1
                    continue
                shutil.copy2(src / e["arquivo"], alvo)
                leituras.anotar("download", sha, arquivo=alvo.name)
                ja[sha] = alvo
                baixados += 1
        man = dict(man, delta={"modo": "replay", "chave_e3": CD.modo_e3(), "baixados": baixados, "mantidos": mantidos,
                               "ligados": ligados})
        (out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
        return out


class DestinoEnsaio:
    """Destino do E7 no ensaio: cópia local com md5 conferido e índice próprio (nada vai ao Drive/rclone)."""
    nome = "ensaio_local"

    def __init__(self, pasta: Path):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.indice = self.pasta / "indice.json"

    def _ler(self) -> dict:
        try:
            return json.loads(self.indice.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _gravar(self, d: dict) -> None:
        tmp = self.indice.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.indice)

    def guardar(self, arquivo: Path) -> dict:
        md5 = _md5(arquivo)
        chave = f"ensaio:{md5}"
        shutil.copy2(arquivo, self.pasta / f"{md5}.pdf")
        d = self._ler()
        d[chave] = {"md5": md5, "origem": str(arquivo), "apagado_em": None}
        self._gravar(d)
        return {"chave": chave, "md5": _md5(self.pasta / f"{md5}.pdf"), "copias": {self.nome: "ok"}}

    def conferir(self, chave: str, md5: str) -> bool:
        u = self._ler().get(chave)
        f = self.pasta / f"{md5}.pdf"
        return bool(u) and u["md5"] == md5 and f.is_file() and _md5(f) == md5

    def registrar_apagado(self, chave: str, arquivo: Path) -> None:
        d = self._ler()
        if chave in d:
            d[chave]["apagado_em"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._gravar(d)


def bloquear_llm() -> None:
    """Sem LLM no ensaio: o gateway recusa (SemProvedor ⇒ o E8/E11 devolvem SemCota ⇒ ABSTEVE contado) e os backends
    viram sentinelas (chamada FORA do gateway quebra o job com a marca, nunca chega a provedor)."""
    from compliance_agent.adaptadores.llm import gateway as G

    def recusa(tarefa, mensagens, *a, **kw):
        raise G.SemProvedor(f"sem_llm_no_ensaio: {tarefa} recusada (O8.5 sem LLM até 28/11 19h)", ["ensaio_o85"])
    G.chamar = recusa

    def sentinela(*a, **kw):
        raise RuntimeError("sem_llm_no_ensaio: backend de LLM chamado FORA do gateway (achado do O8.5)")
    for mod, nome in (("compliance_agent.llm.claude_motor", "pensar"), ("compliance_agent.llm.claude_api", "pensar_api"),
                      ("compliance_agent.llm.free_llm", "best_free_chat")):
        try:
            m = __import__(mod, fromlist=[nome])
            setattr(m, nome, sentinela)
        except (ImportError, AttributeError) as e:               # módulo que não importa aqui não é chamado aqui
            print(f"ensaio: sentinela de LLM não instalada em {mod} — {type(e).__name__}", file=sys.stderr)


def cmd_filho(a) -> int:
    """O processo-filho do ensaio: instala o replay e chama o `fluxo.executar` REAL (handler e efeito reais)."""
    cfg = json.loads(os.environ[ENV_CFG])
    from compliance_agent import evidencias as EV
    from compliance_agent.aplicacao.estagios import arquivar as AQ
    from compliance_agent.aplicacao.estagios import arvore as A
    from compliance_agent.fluxo import executar
    A.obter_navegador = lambda: NavegadorReplay(Path(cfg["acervo_replay"]))
    AQ.obter_destino = lambda: DestinoEnsaio(Path(cfg["frio"]))
    AQ.obter_fila_legada = lambda: set()
    EV.ARQUIVO = Path(cfg["acervo_e8"])
    if cfg.get("estagios_extra"):                                # só os testes: estágios sintéticos no REGISTRO
        import importlib
        importlib.import_module(cfg["estagios_extra"])
    if not cfg.get("com_llm"):
        bloquear_llm()
    else:                                                        # com LLM: só a ASSINATURA, nunca a API paga
        from compliance_agent.llm import claude_api

        def sem_api_paga(*a, **kw):
            raise RuntimeError("ensaio O8.5: API paga recusada — a passada com LLM é só pela assinatura")
        claude_api.pensar_api = sem_api_paga
    return executar.main([a.modo, a.entrada, a.saida])


# ══ 2. o ensaio: esquemas, motor, roteamento e passagens ══════════════════════════════════════════════════════════
def esquemas(run: str) -> dict[str, str]:
    from compliance_agent.fluxo.schema import validar_esquema
    if not re.fullmatch(r"[a-z0-9]{1,12}", run):
        raise ValueError(f"run inválido: {run!r} (minúsculas/dígitos, até 12)")
    e = {k: validar_esquema(f"{PREFIXO}_{run}_{k}") for k in ("fluxo", "cap", "fatos", "dom", "sombra")}
    assert all(v.startswith(PREFIXO + "_") for v in e.values())            # nunca o `fluxo`/`public` de produção
    return e


from compliance_agent.aplicacao.estagios.conferir import (  # noqa: E402 — uma só regra com o E12
    AUTORIZACAO_DONO, autorizacao_dono, motivo_teto)

TETO_SEMANA_PADRAO = 80.0


def liberado_llm(agora: datetime | None = None, caminho: Path | None = None) -> bool:
    return (agora or datetime.now(BRT)) >= LIBERADO_LLM_EM or autorizacao_dono(caminho) is not None


@dataclass
class Ensaio:
    run: str
    passada: int
    forcar: bool = False
    com_llm: bool = False
    base: Path = BASE
    dsn: str = ""
    python: str = sys.executable
    esq: dict = field(default_factory=dict)
    amostra: list = field(default_factory=list)
    estagios_extra: str | None = None                            # só os testes (estágios sintéticos)

    def __post_init__(self):
        self.esq = self.esq or esquemas(self.run)
        self.dir = self.base / self.run
        self.entrada = self.base / "entrada"
        self.coleta = self.dir / "compliance.db"
        self.rotulo = f"{self.run}:p{self.passada}"

    # ── ambiente do filho ──
    def env(self) -> dict:
        from compliance_agent.evidencias import ENV_DSN
        e = self.esq
        f = str(self.coleta)
        env = dict(os.environ)
        env.update({
            ENV_DSN: self.dsn, "JFN_FLUXO_ESQUEMA": e["fluxo"], "JFN_CAPTURA_ESQUEMA": e["cap"],
            "JFN_FATOS_ESQUEMA": e["fatos"], "JFN_DOMINIO_ESQUEMA": e["dom"], "JFN_E10_ESQUEMA": e["sombra"],
            "JFN_E11_ESQUEMA": e["sombra"], "JFN_E14_ESQUEMA": e["sombra"],
            "JFN_CAPTURA_FONTE": f, "JFN_OCR_SIAFE_FONTE": f, "JFN_ELEGIBILIDADE_FONTE": f, "JFN_FATOS_FONTE": f,
            "JFN_DETECTAR_FONTE": f, "JFN_CALIBRAR_FONTE": f, "JFN_ENTREGAR_FONTE": f,
            "JFN_TEXTO_RAIZ": str(self.dir / "sei_texto"), "JFN_VISOES_DIR": str(self.dir / "visoes"),
            "JFN_DATA_DIR": str(self.dir), "JFN_NO": NO, "JFN_LLM_TRACE_DB": str(self.dir / "llm_trace.db"),
            "JFN_LLM_CACHE_DB": str(self.dir / "llm_cache.db"), "JFN_LEITURAS_REGISTRAR": "1",
            "JFN_LEITURAS_ROTULO": self.rotulo, "JFN_ASSINATURA_ESCOPO": "ensaio_o85",   # ritmo cede só aqui
            ENV_CFG: json.dumps({"acervo_replay": str(self.entrada / "acervo"), "frio": str(self.dir / "frio"),
                                 "acervo_e8": str(self.dir / "acervo_e8"), "com_llm": self.com_llm,
                                 "estagios_extra": self.estagios_extra}),
            "PYTHONPATH": os.pathsep.join(p for p in (str(RAIZ), os.environ.get("PYTHONPATH", ""),
                                                      str(OCR_SITE) if OCR_SITE.is_dir() else "") if p),
        })
        return env

    # ── PG ──
    def con(self, chave: str = "fluxo"):
        import psycopg
        c = psycopg.connect(self.dsn, autocommit=True)
        c.execute(f'SET search_path TO "{self.esq[chave]}"')
        return c

    def preparar_esquemas(self) -> dict:
        import psycopg

        from compliance_agent.aplicacao.estagios import fatos as F
        from compliance_agent.aplicacao.estagios import texto as T
        from compliance_agent.fluxo import schema as S
        with psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.esq["fluxo"]}"')
            S.aplicar(c, self.esq["fluxo"])
            ok = S.verificar(c, self.esq["fluxo"])
        T.aplicar_schema(self.dsn, self.esq["cap"])
        c = self.con("fatos")
        try:
            F.aplicar_schema(c, self.esq["fatos"])
        finally:
            c.close()
        from compliance_agent.aplicacao.estagios import periciar as P
        with psycopg.connect(self.dsn, autocommit=True) as c:      # laudos_v2 do E11 (no r2 o E11 não tinha entrada)
            c.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.esq["sombra"]}"')
            P.aplicar_schema(c, self.esq["sombra"])
        return {"fluxo_ok": ok["ok"], "esquemas": self.esq}

    # ── motor: um job pelo caminho real ──
    def rodar_jobs(self, tipo: str) -> list[dict]:
        from compliance_agent.fluxo import fila
        from compliance_agent.fluxo.fila import Resultado
        out = []
        con = self.con()
        try:
            while True:
                job = fila.reservar(con, NO, LIVRES, prazo_s=TIMEOUT_FILHO_S + 600, tipos=[tipo])
                if job is None:
                    break
                t0 = time.monotonic()
                teto = self.teto_llm(job.tipo)
                if teto:                                         # para limpo: o job não roda, nunca "feito"
                    erro = f"ABSTEVE(teto_assinatura): {teto}"
                    out.append({"chave": job.chave, "ficha": job.ficha, "conferido": None, "erro": erro,
                                "estado": fila.falhar(con, job.ficha, erro, True, "teto_assinatura"),
                                "classe": "ABSTEVE(teto_assinatura)", "efeito": None, "eventos": 0, "segundos": 0.0})
                    continue
                pasta = self.dir / "jobs" / re.sub(r"[^A-Za-z0-9_.-]", "_", job.chave)[:150] / str(job.ficha)
                pasta.mkdir(parents=True, exist_ok=True)
                base = {"tipo": job.tipo, "chave": job.chave, "ficha": job.ficha, "no": NO,
                        "tentativa": job.tentativas, "correlation_id": job.correlation_id, "payload": job.payload}
                rc, dados, err = self._filho("rodar", pasta, base)
                estado, erro, efeito, conferido = None, None, None, None
                if rc == 0:
                    rc2, conf, err2 = self._filho("conferir", pasta, {**base, "resultado": dados})
                    if rc2 == 0:
                        conferido = bool(conf.get("conferido"))
                        estado = fila.concluir(con, job.ficha, Resultado(efeito=dados.get("efeito") or {},
                                                                         efeito_conferido=conferido,
                                                                         eventos=dados.get("eventos") or []))
                        efeito = dados.get("efeito")
                    else:
                        erro = f"conferir rc={rc2}: {conf.get('erro') or err2[-600:]}"
                        estado = fila.falhar(con, job.ficha, erro, True, "conferencia")
                elif rc == 3:
                    erro = dados.get("erro") or err[-600:]
                    estado = fila.falhar(con, job.ficha, erro, False, "permanente")
                else:
                    erro = f"rc={rc}: {err[-900:]}"
                    estado = fila.falhar(con, job.ficha, erro, True, "erro")
                out.append({"chave": job.chave, "ficha": job.ficha, "estado": estado, "conferido": conferido,
                            "classe": classificar(job.tipo, estado, erro, self.com_llm), "erro": (erro or "")[-500:],
                            "efeito": _resumo_efeito(efeito), "eventos": len((dados or {}).get("eventos") or []),
                            "segundos": round(time.monotonic() - t0, 2)})
        finally:
            con.close()
        return out

    def teto_llm(self, tipo: str, nivel=None) -> str | None:
        """Só na passada com LLM e só para estágio de LLM: o ritmo da assinatura (`ritmo_assinatura.nivel()`) lido
        ANTES de cada job contra o teto da autorização do dono (padrão 80% da semana)."""
        if not self.com_llm or tipo.split(":", 1)[0] not in ESTAGIOS_LLM:
            return None
        from compliance_agent.llm import ritmo_assinatura
        teto = float((autorizacao_dono() or {}).get("teto_semana_pct") or TETO_SEMANA_PADRAO)
        return motivo_teto((nivel or ritmo_assinatura.nivel)(), teto)

    def _filho(self, modo: str, pasta: Path, entrada: dict) -> tuple[int, dict, str]:
        e, s = pasta / f"{modo}.entrada.json", pasta / f"{modo}.saida.json"
        e.write_text(json.dumps(entrada, ensure_ascii=False, default=str), encoding="utf-8")
        try:
            p = subprocess.run([self.python, "-m", "tools.ensaio_o85", "filho", modo, str(e), str(s)], cwd=RAIZ,
                               env=self.env(), capture_output=True, text=True, timeout=TIMEOUT_FILHO_S)
            rc, err = p.returncode, (p.stderr or "")
        except subprocess.TimeoutExpired:
            rc, err = 124, f"tempo estourado ({TIMEOUT_FILHO_S} s) na fase {modo}"
        (pasta / f"{modo}.stderr").write_text(err[-20000:], encoding="utf-8")
        try:
            dados = json.loads(s.read_text(encoding="utf-8")) if s.exists() else {}
        except ValueError:
            dados = {}
        return rc, dados, err


def classificar(tipo: str, estado: str | None, erro: str | None, com_llm: bool) -> str:
    """Classe do desfecho de um job no relatório. Pura."""
    if estado == "feito":
        return "feito"
    if estado == "falhou_efeito":
        return "falhou_efeito"
    if estado is None:
        return "recusado"
    e = erro or ""
    if tipo.split(":", 1)[0] in ESTAGIOS_LLM and not com_llm and ("SemCota" in e or "sem cota" in e
                                                                  or "sem_llm_no_ensaio" in e):
        return "ABSTEVE(sem_llm_no_ensaio)"
    m = re.search(r"ABSTEVE\(([a-z_]+)", e) if tipo.split(":", 1)[0] in ESTAGIOS_LLM else None
    return f"ABSTEVE({m[1]})" if m else "falhou"      # com LLM: a abstenção declarada (teto, recusa), não falha


def _resumo_efeito(ef: dict | None) -> dict | None:
    if not isinstance(ef, dict):
        return None
    out = {}
    for k, v in ef.items():
        if isinstance(v, (int, float, bool)) or (isinstance(v, str) and len(v) <= 120) or v is None:
            out[k] = v
        elif isinstance(v, list):
            out[k + "_n"] = len(v)
    conf = ef.get("conferencia")
    if isinstance(conf, dict):
        out["conferencia"] = {k: v for k, v in conf.items() if not isinstance(v, (list, dict))}
    return out


# ── roteamento: evento real do estágio anterior → job do seguinte ─────────────────────────────────────────────────
# (fonte, tipo) que nenhum estágio do ensaio consome, com o MOTIVO (a contagem fecha por ele, não por silêncio)
SEM_ROTA = {
    ("sei_relacionado", "citado"): "processo citado fora da amostra: a fila única do E2 decide (fora do recorte)",
    ("texto", "invalido"): "tela de WAF/menu do SEI: pede recaptura ao E3 (rede proibida no ensaio)",
    ("arquivar", "arquivado"): "terminal: original guardado com md5 conferido (nenhum estágio depende)",
    ("calibrar", "tier"): "terminal no ensaio: o registro de detectores não é gravado (sombra)",
    ("materializar", "visao"): "terminal: visão pronta para o painel (rota só lê)",
    ("entregar", "dossie"): "terminal: dossiê exportado (sem envio no ensaio)",
    ("observar", "metricas"): "consumido pela automelhoria (O8.4), fora do ensaio",
    ("coleta", "conferidos"): "consumido pelo E13 (calibrar) no mesmo ensaio",
}


# Um evento suja TODOS os estágios que dependem da fonte dele (como `planejador.propagar_eventos`): o consumo é por
# (evento, estágio) — `o85_consumo` no esquema de fluxo do ensaio; `processado_em` marca o 1º consumo.
DDL_CONSUMO = ("CREATE TABLE IF NOT EXISTS o85_consumo(evento_id BIGINT NOT NULL, estagio TEXT NOT NULL, "
               "em TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(evento_id, estagio))")


def eventos_pendentes(con, pares: list[tuple[str, str | None]], estagio: str) -> list[dict]:
    con.execute(DDL_CONSUMO)
    out = []
    for ev_id, fonte, tipo, chave, det in con.execute(
            "SELECT id, fonte, tipo, chave, detalhe FROM eventos e WHERE NOT EXISTS (SELECT 1 FROM o85_consumo c "
            "WHERE c.evento_id = e.id AND c.estagio = %s) ORDER BY id", (estagio,)):
        if any(fonte == f and (t is None or t == tipo) for f, t in pares):
            out.append({"id": ev_id, "fonte": fonte, "tipo": tipo, "chave": chave, "detalhe": det or {}})
    return out


def marcar_processados(con, ids: list[int], estagio: str) -> None:
    if ids:
        con.cursor().executemany("INSERT INTO o85_consumo(evento_id, estagio) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                                 [(i, estagio) for i in ids])
        con.execute("UPDATE eventos SET processado_em = now() WHERE id = ANY(%s) AND processado_em IS NULL", (ids,))


def enfileirar_jobs(con, jobs: list[dict], reabrir: bool) -> dict:
    """Enfileira pela fila real (idempotente pela chave). Conta criados, juntados (mesma chave nesta leva) e já
    existentes (a chave já tinha job — idempotência do motor)."""
    from compliance_agent.fluxo import fila
    vistos: set[str] = set()
    r = {"pedidos": len(jobs), "criados": 0, "juntados": 0, "ja_existentes": 0}
    for j in jobs:
        if j["chave"] in vistos:
            r["juntados"] += 1
            continue
        vistos.add(j["chave"])
        novo = fila.enfileirar(con, j["tipo"], j["chave"], j["payload"], max_tentativas=1, reabrir=reabrir)
        r["criados" if novo else "ja_existentes"] += 1
    return r


def processos_citados(con_sombra, amostra: set[str], eventos: list[dict]) -> set[str]:
    """Processos da AMOSTRA que os achados das rodadas dos eventos `detectar/achados` citam (igualdade de valor nos
    campos `processo`/`processos` do resultado, chave canônica)."""
    from compliance_agent.dominio import processo_id as PI
    achou: set[str] = set()

    def anda(v, k=None):
        if isinstance(v, dict):
            for kk, vv in v.items():
                anda(vv, kk)
        elif isinstance(v, list):
            for x in v:
                anda(x, k)
        elif k in ("processo", "processos", "processo_pagamento", "processo_contrato") and isinstance(v, str):
            c = PI.chave_processo(v)
            if c in amostra:
                achou.add(c)
    for ev in eventos:
        if not ev["chave"]:
            continue
        did, escopo = ev["chave"].rsplit(":", 1)
        for (res,) in con_sombra.execute("SELECT resultado FROM execucao_regra WHERE origem LIKE %s",
                                         (f"e10:{did}:{escopo}:%",)):
            anda(res)
    return achou


def cnpjs_citados(con_sombra, cnpjs: set[str], eventos: list[dict]) -> set[str]:
    """CNPJs (credores da amostra) que algum VALOR do resultado dos achados das rodadas iguala (14 dígitos ou
    formatado) — a mesma relação do E14 para a chave `cnpj:` (caso.relacionados), nunca substring do JSON cru."""
    achou: set[str] = set()

    def anda(v):
        if isinstance(v, dict):
            for vv in v.values():
                anda(vv)
        elif isinstance(v, list):
            for x in v:
                anda(x)
        elif isinstance(v, str):
            d = _dig(v)
            if len(d) == 14 and d in cnpjs and (v == d or re.fullmatch(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", v)):
                achou.add(d)
            for parte in v.split("|"):                           # chave composta "ug|cnpj" dos detectores tg_*
                if _dig(parte) == parte and parte in cnpjs:
                    achou.add(parte)
    for ev in eventos:
        if not ev["chave"]:
            continue
        did, escopo = ev["chave"].rsplit(":", 1)
        for (res,) in con_sombra.execute("SELECT resultado FROM execucao_regra WHERE origem LIKE %s",
                                         (f"e10:{did}:{escopo}:%",)):
            anda(res)
    return achou


def credores_da_amostra(ens) -> set[str]:
    from compliance_agent.dominio import processo_id as PI
    am = {x["processo"] for x in ens.amostra}
    con = sqlite3.connect(f"file:{ens.coleta}?mode=ro", uri=True)
    try:
        # ob-qualquer-status: mapa credor → processo da amostra (identidade, não soma)
        return {_dig(c) for c, p in con.execute("SELECT credor, processo FROM ob_orcamentaria_siafe")
                if PI.chave_processo(p or "") in am and len(_dig(c)) == 14}
    finally:
        con.close()


# ── E1 (replay do snapshot → coleta do ensaio) ────────────────────────────────────────────────────────────────────
UNIDADE_DA_TABELA = {"ob_orcamentaria_siafe": "ob_siafe", "ordens_bancarias": "ob_tfe",
                     "contratos_tcerj": "contrato_tcerj", "compras_diretas_tcerj": "compra_direta_tcerj",
                     "siga_contratos": "contrato_siga", "contratos": "contrato_rules"}


def _linhas_sha(con: sqlite3.Connection, t: str) -> tuple[int, str]:
    """(nº de linhas, sha256 do MULTICONJUNTO de linhas) — independe da ordem física."""
    ls = sorted(json.dumps(list(r), default=str) for r in con.execute(f'SELECT * FROM "{t}"'))
    return len(ls), hashlib.sha256("\n".join(ls).encode()).hexdigest()


def e1_replay(ens: Ensaio) -> dict:
    """Copia o extrato para a coleta do ensaio. Aceito = linha nova; já presente = idempotência (2ª passada);
    quarentena = OB sem chave (ug, número, exercício). Efeito conferido: recontagem e sha256 das linhas, tabela a
    tabela, iguais à fonte (o que foi aceito está lá, inteiro)."""
    from compliance_agent.dominio import processo_id as PI
    from compliance_agent.fluxo import fila
    fonte = ens.entrada / "replay_fonte.db"
    meta = json.loads((ens.entrada / "replay_fonte.json").read_text(encoding="utf-8"))
    md5 = _md5(fonte)
    if md5 != meta["_md5"]:
        raise RuntimeError(f"md5 do extrato {md5} ≠ {meta['_md5']} — não rodo sobre universo diferente")
    ens.dir.mkdir(parents=True, exist_ok=True)
    src = _ro(fonte)
    dst = sqlite3.connect(ens.coleta)
    por_tabela, amostra = {}, {x["processo"] for x in ens.amostra}
    novos_proc: set[str] = set()
    try:
        tabelas = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for t in tabelas:
            if not dst.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
                dst.execute(src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()[0])
                for (ix,) in src.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS "
                                         "NOT NULL", (t,)):
                    dst.execute(ix)
            cols = [c[1] for c in src.execute(f'PRAGMA table_info("{t}")')]
            try:
                src.execute(f'SELECT rowid FROM "{t}" LIMIT 1')
                com_rowid = True
            except sqlite3.OperationalError:                      # WITHOUT ROWID: a PK da tabela deduplica
                com_rowid = False
            antes = dst.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            aceitos = presentes = quarentena = 0
            ccols = (["rowid"] if com_rowid else []) + [chr(34) + c + chr(34) for c in cols]
            q = f'INSERT OR IGNORE INTO "{t}"({",".join(ccols)}) VALUES ({",".join("?" * len(ccols))})'
            for linha in src.execute(f'SELECT {",".join(ccols)} FROM "{t}"'):
                r = linha[1:] if com_rowid else linha
                if t == "ob_orcamentaria_siafe":
                    d = dict(zip(cols, r))
                    if not (d.get("numero_ob") and d.get("ug_emitente") and d.get("exercicio")):
                        quarentena += 1
                        continue
                cur = dst.execute(q, linha)
                if cur.rowcount:
                    aceitos += 1
                    if t == "ob_orcamentaria_siafe":
                        k = PI.chave_processo(dict(zip(cols, r)).get("processo") or "")
                        if k in amostra:
                            novos_proc.add(k)
                else:
                    presentes += 1
            dst.commit()
            depois = dst.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            por_tabela[t] = {"fonte": aceitos + presentes + quarentena, "aceitos": aceitos, "ja_presentes": presentes,
                             "quarentena": quarentena, "antes": antes, "depois": depois}
        # efeito conferido (outra leitura): recontagem e sha256 das linhas por tabela (sem a quarentena)
        conf = {}
        for t in tabelas:
            n_dst, h_dst = _linhas_sha(dst, t)
            if por_tabela[t]["quarentena"]:
                conf[t] = n_dst == por_tabela[t]["depois"] and n_dst == por_tabela[t]["fonte"] - por_tabela[t]["quarentena"]
            else:
                n_src, h_src = _linhas_sha(src, t)
                conf[t] = (n_dst, h_dst) == (n_src, h_src)
    finally:
        src.close()
        dst.close()
    # eventos que sujam os seguintes (só o que mudou: idempotente na 2ª passada)
    con = ens.con()
    eventos = []
    try:
        procs = sorted(amostra if ens.forcar else novos_proc)
        for p in procs:
            eventos.append(("coleta", "ob_nova", p))
        for t, u in UNIDADE_DA_TABELA.items():
            if t in por_tabela and (por_tabela[t]["aceitos"] or (ens.forcar and por_tabela[t]["depois"])):
                eventos.append(("coleta", "fonte_mudou", u))
        if por_tabela.get("alertas_triagem", {}).get("aceitos") or ens.forcar:
            eventos.append(("coleta", "conferidos", "alertas_triagem"))
        for f, t, k in eventos:
            fila.emitir(con, f, t, k, {"passada": ens.passada, "origem": "e1_replay"})
    finally:
        con.close()
    aceitos = sum(x["aceitos"] for x in por_tabela.values())
    return {"estagio": "E1", "tipo": "coletar:replay", "handler": "orquestrador (replay do snapshot; sem handler "
            "nativo de E1 sem rede)", "fonte": str(fonte), "fonte_md5": md5, "por_tabela": por_tabela,
            "aceitos": aceitos, "sem_novidade": aceitos == 0, "efeito_conferido": all(conf.values()),
            "conferencia": conf, "eventos_emitidos": _contar_ev(eventos)}


def _contar_ev(eventos) -> dict:
    out: dict = {}
    for f, t, _ in eventos:
        out[f"{f}/{t}"] = out.get(f"{f}/{t}", 0) + 1
    return out


# ── cache do E8: o que o piloto já leu, pelos shas do texto do estágio ─────────────────────────────────────────────
def semear_docs_lidos(ens: Ensaio, processos: set[str]) -> dict:
    """Cache do E8 por (sha do texto, prompt, modelo): o que o PILOTO já leu (`public.docs_lidos`, só leitura) entra
    no esquema de fatos do ensaio PARA OS SHAS QUE A AMOSTRA TEM. Os shas são os do TEXTO DO ESTÁGIO como o E8 o lê
    (`fatos.acervo_do_estagio`: E4/E5 conferidos no PG, porta pelo E6, fim de linha universal + `sem_etiqueta`) —
    processo barrado na porta não abre lateral e não entra. Mede quanto da leitura antiga sobrevive."""
    from compliance_agent.aplicacao.estagios import fatos as F
    shas: set[str] = set()
    con = ens.con("cap")
    try:
        for proc in sorted(processos):
            a = F.acervo_do_estagio(con, proc)
            if a is not None and a.fora_da_porta is None:
                shas |= {d["sha"] for d in a.docs}
    finally:
        con.close()
    versoes = F.versoes_lidas()
    import psycopg
    with psycopg.connect(ens.dsn, autocommit=True) as c:
        linhas = c.execute("SELECT sha, versao, processo, doc_id, lote, em FROM public.docs_lidos WHERE sha = ANY(%s) "
                           "AND versao = ANY(%s)", (sorted(shas), versoes)).fetchall() if shas else []
        c.execute(f'SET search_path TO "{ens.esq["fatos"]}"')
        c.cursor().executemany("INSERT INTO docs_lidos(sha, versao, processo, doc_id, lote, em) VALUES "
                               "(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", linhas)
    return {"shas_da_amostra": len(shas), "ja_lidos_pelo_piloto": len({r[0] for r in linhas}), "versoes": versoes}


# ── as passagens, em sequência ────────────────────────────────────────────────────────────────────────────────────
def _job(tipo: str, chave: str, payload: dict) -> dict:
    return {"tipo": tipo, "chave": chave, "payload": payload}


def passagem(ens: Ensaio, ek: str, consome: list[tuple[str, str | None]], gerar, tipo: str | None,
             nota: str = "", bloqueado: str | None = None) -> dict:
    """Uma passagem: consome os eventos pendentes (saída REAL do anterior), gera os jobs, roda pelo motor, conta."""
    t0 = time.monotonic()
    con = ens.con()
    try:
        evs = eventos_pendentes(con, consome, ek)
        entrada = _contar_ev((e["fonte"], e["tipo"], None) for e in evs)
        if bloqueado:
            marcar_processados(con, [e["id"] for e in evs], ek)
            return {"estagio": ek, "tipo": tipo, "estado": "BLOQUEADO", "motivo": bloqueado, "entrada": entrada,
                    "eventos_consumidos": len(evs), "jobs": [], "nota": nota,
                    "segundos": round(time.monotonic() - t0, 2)}
        jobs = gerar(evs)
        fila_r = enfileirar_jobs(con, jobs, reabrir=ens.forcar)
        marcar_processados(con, [e["id"] for e in evs], ek)
    finally:
        con.close()
    resultados = ens.rodar_jobs(tipo) if tipo else []
    classes = _contar_ev((r["classe"], "", None) for r in resultados)
    classes = {k.rstrip("/"): v for k, v in classes.items()}
    emitidos = sum(r["eventos"] for r in resultados)
    reprovada = any(r["classe"] in ("falhou_efeito", "falhou", "recusado") for r in resultados)
    return {"estagio": ek, "tipo": tipo, "estado": "REPROVADA" if reprovada else (
            "APROVADA_COM_ABSTENCAO" if any(r["classe"].startswith("ABSTEVE") for r in resultados) else
            ("SEM_ENTRADA" if not resultados else "APROVADA")),
            "entrada": entrada, "eventos_consumidos": len(evs), "fila": fila_r, "classes": classes,
            "efeito_conferido": sum(1 for r in resultados if r["estado"] == "feito"), "jobs_rodados": len(resultados),
            "eventos_emitidos": emitidos, "jobs": resultados, "nota": nota, "segundos": round(time.monotonic() - t0, 2)}


def detectores_da_unidade(unidade: str) -> list[str]:
    from compliance_agent.aplicacao import detectores as DM
    from compliance_agent.aplicacao.estagios import detectar as D
    out = []
    for did in sorted(DM.MODULOS):
        try:
            if D.exigencia(did)[0] == unidade:
                out.append(did)
        except D.ErroPermanente:                                  # detector sem exigência na E9 fica fora (declarado)
            continue
    return out


def roteiro(ens: Ensaio) -> list[tuple]:
    """E2..E18: (Ek, eventos consumidos, gerador de jobs, tipo, nota, bloqueio). A ORDEM é a do plano §3.2."""
    from compliance_agent.aplicacao.estagios import texto as T
    f = str(ens.coleta)
    amostra = {x["processo"] for x in ens.amostra}
    rt = str(ens.dir / "sei_texto")

    def k_doc(ev, tipo):
        proc, doc = ev["chave"].split("|", 1)
        sha = ev["detalhe"].get("sha256") or ""
        return _job(tipo, T.chave_job(tipo, proc, doc, sha), {"processo": proc, "doc_id": doc, "sha256": sha,
                                                                "raiz_texto": rt})

    def g_e2(evs):
        return [_job("arvore", f"arvore:{e['chave']}", {"processo": e["chave"]}) for e in evs]

    def g_e3(evs):
        return [_job("capturar", f"capturar:{e['chave']}", {"processo": e["chave"], "raiz": str(ens.dir / "sei_cache")})
                for e in evs]

    def g_e4(evs):
        con = ens.con("cap")
        try:
            return [dict(j, payload={**j["payload"], "raiz_texto": rt}) for e in evs
                    for j in T.jobs_da_aquisicao(con, e["detalhe"]["aquisicao_id"])]
        finally:
            con.close()

    def g_e8(evs):
        procs = {e["chave"].split("|", 1)[0] for e in evs}
        ens._cache_e8 = semear_docs_lidos(ens, procs)      # sem ponte: o E8 lê o E4/E5 + E6 do PG (frente B1)
        return [_job("fatos", f"fatos:{p}", {"processo": p}) for p in sorted(procs)]

    def g_e9(evs):
        return [_job("elegibilidade", f"elegibilidade:{e['chave']}:todos", {"unidade": e["chave"], "fonte": f,
                                                                           "amostra": 30})
                for e in evs if e["fonte"] == "coleta"]

    def g_e10(evs):
        jobs = []
        for e in evs:
            unidade = e["chave"].split(":", 1)[0]
            jobs += [_job("detectar", f"detectar:{d}:todos", {"detector": d, "fonte": f, "amostra": 5})
                     for d in detectores_da_unidade(unidade)]
        return jobs

    def procs_achados(evs):
        con = ens.con("sombra")
        try:
            achados = [e for e in evs if (e["fonte"], e["tipo"]) == ("detectar", "achados")]
            return processos_citados(con, amostra, achados)
        finally:
            con.close()

    def g_e11(evs):
        procs = procs_achados(evs) | {e["chave"] for e in evs if e["fonte"] == "fatos"}
        procs |= {e["chave"] for e in evs if e["tipo"] == "achado_processo" and e["chave"] in amostra}
        return [_job("periciar", f"periciar:{p}", {"processo": p, "fonte": f}) for p in sorted(procs)]

    def g_e12(evs):
        con = ens.con("sombra")
        try:
            ids = sorted({i for e in evs if e["fonte"] == "detectar" and e["chave"] for (i,) in con.execute(
                "SELECT a.id FROM achado a JOIN execucao_regra e ON e.id = a.execucao_regra_id WHERE e.origem LIKE %s",
                (f"e10:{e['chave']}:%",))})
        finally:
            con.close()
        return ([_job("conferir", f"conferir:achado:{i}", {"alvo": "achado", "ref": str(i)}) for i in ids]
                + [_job("conferir", f"conferir:laudo:{e['chave']}", {"alvo": "laudo", "ref": e["chave"]})
                   for e in evs if e["fonte"] == "periciar"])

    def g_e17(evs):
        return [_job("manter", f"manter:{r}:{ens.run}-p{ens.passada}", {"rotina": r, "simular": True,
                                                                       "db": f, "perfil": NO})
                for r in ("backup_compliance", "backup_evidencias_pg", "wal_checkpoint", "vacuum", "zelador")]

    def g_e13(evs):
        return [_job("calibrar", "calibrar:todos", {"detector": "todos", "fonte": f, "sombra": True,
                                                    "saida": str(ens.dir / "calibrar.json")})] if evs else []

    def g_e14(evs):
        con = ens.con("sombra")
        try:
            cnpjs = cnpjs_citados(con, credores_da_amostra(ens), [e for e in evs if e["fonte"] == "detectar"])
        finally:
            con.close()
        return ([_job("caso", f"caso:processo:{p}", {"chave": f"processo:{p}"}) for p in sorted(procs_achados(evs))]
                + [_job("caso", f"caso:cnpj:{c}", {"chave": f"cnpj:{c}"}) for c in sorted(cnpjs)])

    def g_e15(evs):
        return [_job("materializar", "materializar:siafe_stats", {"visao": "siafe_stats"})] if evs else []

    def g_e16(evs):
        casos = sorted({e["chave"] for e in evs if e["fonte"] == "caso"})
        if not evs:
            return []
        return [_job("entregar", "entregar:dossie_orgao:couto", {
            "produto": "dossie_orgao", "lente": "couto", "casos": casos, "fonte": f, "sem_pdf": True,
            "saida": str(ens.dir / "entregas"), "justificativa": "ensaio O8.5 (sem envio, coleta do ensaio)"})]

    def g_e18(evs):
        return [_job("observar", f"observar:ensaio-p{ens.passada}",
                     {"grupos": ["fila", "captura", "prova", "leitura"], "forcar": True})]

    return [
        ("E2", [("coleta", "ob_nova")], g_e2, "arvore", "navegador de replay (árvore do acervo)", None),
        ("E3", [("arvore", "documento_novo")], g_e3, "capturar", "delta por id_documento; 'baixar' = copiar", None),
        ("E4", [("capturar", "versao_nova")], g_e4, "texto", "um job por versão binária da aquisição", None),
        ("E5", [("texto", "pagina_escaneada")], lambda evs: [k_doc(e, "ocr") for e in evs], "ocr",
         "RapidOCR na CPU da VM-2 (volta declarada); 2º motor Tesseract", None),
        ("E6", [("ocr", "numero_ia")], lambda evs: [k_doc(e, "confirmar_ocr") for e in evs], "confirmar_ocr",
         "nível A: leitura independente, recorte, SIAFE da coleta do ensaio, barras (sem decodificador = INDISPONÍVEL)",
         None),
        ("E7", [("texto", "sem_ocr"), ("ocr", "terminado")], lambda evs: [k_doc(e, "arquivar") for e in evs],
         "arquivar", "destino local do ensaio (md5 duplo antes de apagar a CÓPIA do ensaio)", None),
        ("E8", [("texto", "texto_novo"), ("ocr", "texto_novo"), ("confirmar_ocr", None)], g_e8, "fatos",
         "texto do E4/E5 e porta pelo E6 no PG (frente B1, sem ponte) + cache docs_lidos do piloto pelo sha", None),
        ("E9", [("coleta", "fonte_mudou"), ("fatos", "mudou")], g_e9, "elegibilidade", "sobre a coleta do ensaio",
         None),
        ("E10", [("elegibilidade", "mudou")], g_e10, "detectar", "detectores cuja exigência é da unidade da E9", None),
        ("E11", [("detectar", "achados"), ("detectar", "achado_processo"), ("fatos", "mudou")], g_e11, "periciar",
         "processos da amostra citados pelos achados ou com fatos novos", None),
        ("E12", [("periciar", "laudo"), ("detectar", "achados")], g_e12, "conferir",
         "por risco (regra da O6.5); sem LLM até 28/11 19h: ABSTEVE(sem_llm) ou NÃO JULGADO, nunca veredito", None),
        ("E13", [("coleta", "conferidos"), ("conferir", "veredito")], g_e13, "calibrar", "sombra: JSON no run, registro intocado", None),
        ("E14", [("detectar", "achados")], g_e14, "caso",
         "caso por processo da amostra citado nos achados, ou por CNPJ de credor da amostra (os achados do E10 não "
         "trazem processo SEI: execucao_regra.processo é NULL)", None),
        ("E15", [("coleta", "fonte_mudou")], g_e15, "materializar", "visão siafe_stats sobre a coleta do ensaio",
         None),
        ("E16", [("caso", "versao"), ("coleta", "ob_nova")], g_e16, "entregar",
         "dossiê da lente couto sobre a coleta do ensaio, sem PDF e sem envio", None),
        ("E17", [], g_e17, "manter", "--simular: lista o que faria e confere as pré-condições; nada executa", None),
        ("E18", [], g_e18, "observar", "sensores fila/captura/prova/leitura no esquema do ensaio", None),
    ]


def resumo_leituras(ens: Ensaio, rotulo: str | None = None) -> dict:
    from compliance_agent.fluxo import leituras as LR
    con = ens.con()
    try:
        linhas = LR.ler_linhas(con, rotulo=rotulo)
    finally:
        con.close()
    if linhas is None:
        return {"leituras": 0, "nota": "registro de leituras ainda vazio (tabela não criada)"}
    r = LR.resumir(linhas)
    por_estagio: dict = {}
    for x in linhas:
        if x["modo"] == "rodar":
            k = f"{x['estagio']}/{x['tipo']}"
            por_estagio[k] = por_estagio.get(k, 0) + 1
    r["por_estagio_tipo"] = por_estagio
    return r


def sensor_e18(ens: Ensaio) -> dict | None:
    con = ens.con()
    try:
        r = con.execute("SELECT valor, rotulos FROM metricas WHERE nome = 'leitura.repetida_pct' ORDER BY quando DESC "
                        "LIMIT 1").fetchone()
    finally:
        con.close()
    if r is None:
        return None
    return {"valor": None if r[0] != r[0] else r[0], "estado": (r[1] or {}).get("estado"),
            "motivo": (r[1] or {}).get("motivo"), "leituras": (r[1] or {}).get("leituras")}


def cmd_rodar(a) -> int:
    from compliance_agent.evidencias import dsn_vigente
    if a.com_llm and not liberado_llm():
        print(f"recusado: o ensaio com LLM só roda depois de {LIBERADO_LLM_EM:%d/%m/%Y %Hh} (BRT) ou com a "
              f"autorização do dono em {AUTORIZACAO_DONO} — assinatura contida; API paga exige autorização do dono",
              file=sys.stderr)
        return 2
    dsn = dsn_vigente()
    if not dsn:
        print("sem JFN_EVIDENCIAS_DSN (use python -m compliance_agent.credenciais com JFN_EVIDENCIAS_DSN -- …)",
              file=sys.stderr)
        return 2
    base = Path(a.base) if a.base else BASE
    am = json.loads((base / "entrada" / "amostra.json").read_text(encoding="utf-8"))
    ens = Ensaio(run=a.run, passada=a.passada, forcar=a.forcar, com_llm=a.com_llm, base=base, dsn=dsn,
                 amostra=am["amostra"])
    ens.dir.mkdir(parents=True, exist_ok=True)
    if a.com_llm:
        from compliance_agent.fluxo import ritmo
        c = ens.con()
        try:
            ritmo.medir_e_publicar(c, NO)                         # o ritmo real da assinatura no esquema do ensaio
        finally:
            c.close()
    pasta = ens.dir / f"p{a.passada}"
    pasta.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    geral = {"run": a.run, "passada": a.passada, "forcar": a.forcar, "com_llm": a.com_llm, "inicio":
             datetime.now(BRT).isoformat(timespec="seconds"), "esquemas": ens.preparar_esquemas(),
             "amostra": {k: v for k, v in am.items() if k != "amostra"}, "passagens": []}

    def grava(ek: str, p: dict) -> None:
        p["leituras"] = resumo_leituras(ens, ens.rotulo)
        (pasta / f"passagem_{ek}.json").write_text(json.dumps(p, ensure_ascii=False, indent=1, default=str),
                                                    encoding="utf-8")
        geral["passagens"].append({k: p.get(k) for k in ("estagio", "tipo", "estado", "motivo", "entrada", "fila",
                                                        "classes", "eventos_consumidos", "jobs_rodados",
                                                        "efeito_conferido", "eventos_emitidos", "segundos")})
        print(f"[{ek}] {p.get('estado') or ('feito' if p.get('efeito_conferido') else '?')} "
              f"entrada={p.get('entrada')} jobs={p.get('jobs_rodados', '-')} classes={p.get('classes')} "
              f"{p.get('segundos')} s", flush=True)

    t1 = time.monotonic()
    p1 = e1_replay(ens)
    p1["segundos"] = round(time.monotonic() - t1, 2)
    p1["estado"] = "APROVADA" if p1["efeito_conferido"] else "REPROVADA"
    grava("E1", p1)
    for ek, consome, gerar, tipo, nota, bloq in roteiro(ens):
        p = passagem(ens, ek, consome, gerar, tipo, nota, bloq)
        if ek == "E8":
            p["cache_docs_lidos"] = getattr(ens, "_cache_e8", None)
        grava(ek, p)
    con = ens.con()
    try:
        con.execute(DDL_CONSUMO)
        sobra = [{"fonte": f, "tipo": t, "n": n, "motivo": SEM_ROTA.get((f, t), "SEM MOTIVO — a contagem não fecha")}
                 for f, t, n in con.execute("SELECT fonte, tipo, count(*) FROM eventos e WHERE NOT EXISTS (SELECT 1 "
                                            "FROM o85_consumo c WHERE c.evento_id = e.id) GROUP BY 1, 2 ORDER BY 1, 2")]
    finally:
        con.close()
    geral["eventos_sem_consumo"] = sobra
    geral["contagem_fecha"] = all(s["motivo"] != "SEM MOTIVO — a contagem não fecha" for s in sobra)
    geral["leituras_passada"] = resumo_leituras(ens, ens.rotulo)
    geral["leituras_run"] = resumo_leituras(ens)
    geral["sensor_e18"] = sensor_e18(ens)
    geral["segundos"] = round(time.monotonic() - t0, 1)
    geral["fim"] = datetime.now(BRT).isoformat(timespec="seconds")
    (pasta / "resumo.json").write_text(json.dumps(geral, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: geral[k] for k in ("contagem_fecha", "segundos", "sensor_e18")}, ensure_ascii=False,
                     default=str))
    lp = geral["leituras_passada"]
    print(json.dumps({"leituras": lp.get("leituras"), "downloads": lp.get("downloads"), "llm": lp.get("llm"),
                      "repetida_pct": lp.get("repetida_pct"), "releituras_no_job": lp.get("releituras_no_job")},
                     ensure_ascii=False))
    return 0


def cmd_relatorio(a) -> int:
    base = Path(a.base) if a.base else BASE
    out = {}
    for p in sorted((base / a.run).glob("p*/resumo.json")):
        out[p.parent.name] = json.loads(p.read_text(encoding="utf-8"))
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.ensaio_o85", description="O8.5 ensaio ponta a ponta")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("obpaga")
    o.add_argument("--snapshot", default=str(SNAPSHOT))
    o.add_argument("--saida", default=str(BASE / "entrada" / "ob_paga.json"))
    c = sub.add_parser("candidatos")
    c.add_argument("--sei-cache", action="append", default=None)
    c.add_argument("--ob-paga", default=str(BASE / "entrada" / "ob_paga.json"))
    c.add_argument("--saida", default=str(BASE / "entrada" / "candidatos.json"))
    t = sub.add_parser("triagem")
    t.add_argument("--entrada", default=str(BASE / "entrada"))
    s = sub.add_parser("sortear")
    s.add_argument("--entrada", default=str(BASE / "entrada"))
    s.add_argument("--n", type=int, default=30)
    s.add_argument("--semente", type=int, default=SEMENTE)
    s.add_argument("--max-escaneadas", type=int, default=40)
    e = sub.add_parser("extrair")
    e.add_argument("--entrada", default=str(BASE / "entrada"))
    e.add_argument("--snapshot", default=str(SNAPSHOT))
    r = sub.add_parser("rodar")
    r.add_argument("--run", required=True)
    r.add_argument("--passada", type=int, default=1)
    r.add_argument("--forcar", action="store_true", help="re-emite os gatilhos e reabre os jobs (prova de idempotência)")
    r.add_argument("--com-llm", action="store_true", help="só depois de 28/11/2026 19h (BRT)")
    r.add_argument("--base", default=None)
    rl = sub.add_parser("relatorio")
    rl.add_argument("--run", required=True)
    rl.add_argument("--base", default=None)
    fi = sub.add_parser("filho")
    fi.add_argument("modo", choices=("rodar", "conferir"))
    fi.add_argument("entrada")
    fi.add_argument("saida")
    a = ap.parse_args(argv)
    if a.cmd == "candidatos" and not a.sei_cache:
        a.sei_cache = [str(BASE / "entrada" / "acervo")]
    return {"obpaga": cmd_obpaga, "candidatos": cmd_candidatos, "triagem": cmd_triagem, "sortear": cmd_sortear, "extrair": cmd_extrair,
            "rodar": cmd_rodar, "relatorio": cmd_relatorio, "filho": cmd_filho}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
