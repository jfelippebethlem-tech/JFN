"""sentinela_integridade — vigia a QUALIDADE do que os pipelines produzem, não o prazo.

Irmã de `pipelines_slo` (que vigia FRESCOR: a etapa produziu dentro do SLO?). Aqui o sinal é
outro: **produziu CERTO?** Toda falha da madrugada de 2026-08-02 passou verde no SLO porque
produziu no prazo — só que o conteúdo estava corrompido, e ninguém soube por semanas:

  · texto de documento cortado em 20.000 chars (a CONCLUSÃO do parecer ficava fora, e o juízo
    por IA condenava quem havia concluído);
  · `anexo_bytes` serializado no cache: PDF virava repr `b'%PDF…'` e inflava o JSON ~400×
    (127 MB de anexo para 302 KB de texto);
  · leitura devolvendo 0 documentos por CORRIDA (frame da árvore ainda vazio) — processo
    legível marcado INDISPONÍVEL.

Nenhuma delas gritou. Esta sentinela transforma cada uma numa INVARIANTE medida, e o que ela
mede é o dado no disco/banco — não a intenção do código. Barata de propósito (stat + amostra +
SQL com índice): roda de hora em hora ao lado do SLO, na VM de 2 vCPU.

    .venv/bin/python -m tools.sentinela_integridade            # relatório (exit 1 se violado)
    .venv/bin/python -m tools.sentinela_integridade --alerta   # + Telegram na TRANSIÇÃO ok->violado
    .venv/bin/python -m tools.sentinela_integridade --json     # para o painel/API
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = RAIZ / "data" / "sei_arquivo"
CACHE = RAIZ / "data" / "sei_cache"
DB = RAIZ / "data" / "compliance.db"
ESTADO = RAIZ / "data" / "sentinela_integridade_estado.json"

# teto de texto por documento (o mesmo do reader) — a invariante "corte no teto" olha para ele
TETO_CHARS = int(os.environ.get("SEI_MAX_CHARS_DOC", "60000"))
# um cache legítimo é TEXTO: 40 docs × teto ≈ 2,4 MB. 12 MB dá folga de 5× antes de gritar.
TETO_CACHE_MB = float(os.environ.get("JFN_TETO_CACHE_MB", "12"))
AMOSTRA_MANIFESTS = int(os.environ.get("JFN_SENTINELA_AMOSTRA", "200"))


def _recentes(padrao: str, base: Path, n: int) -> list[Path]:
    """Os `n` arquivos mais recentes — amostra por mtime, sem varrer o acervo inteiro."""
    if not base.is_dir():
        return []
    itens = [(p.stat().st_mtime, p) for p in base.glob(padrao) if p.is_file()]
    itens.sort(reverse=True)
    return [p for _, p in itens[:n]]


def inv_cache_obeso() -> dict:
    """Nenhum cache de processo deve passar de TETO_CACHE_MB — cache é TEXTO.

    Assinatura do bug do `anexo_bytes`: binário serializado com `default=str`.
    """
    gordos = []
    for p in _recentes("cdp_*.json", CACHE, 400):
        mb = p.stat().st_size / 1e6
        if mb > TETO_CACHE_MB:
            gordos.append({"arquivo": p.name, "mb": round(mb, 1)})
    return {
        "invariante": "cache_obeso",
        "descricao": f"cache de processo acima de {TETO_CACHE_MB:g} MB (binário serializado?)",
        "medida": len(gordos), "limite": 0,
        "estado": "violado" if gordos else "ok",
        "evidencia": sorted(gordos, key=lambda g: -g["mb"])[:5],
    }


def inv_corte_no_teto() -> dict:
    """Documento com chars EXATAMENTE no teto é texto amputado, não documento curto.

    Um punhado é normal (documento gigante existe); passar de 5% da amostra é assinatura de
    cap ativo cortando o acervo — foi assim que 1.660 documentos perderam a conclusão.
    """
    docs = cortados = 0
    exemplos = []
    for man in _recentes("*/manifest.json", ARQUIVO, AMOSTRA_MANIFESTS):
        try:
            m = json.loads(man.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for d in m.get("docs") or []:
            try:
                c = int(d.get("chars") or 0)
            except (TypeError, ValueError):
                continue
            if c <= 0:
                continue
            docs += 1
            if TETO_CHARS * 0.999 <= c <= TETO_CHARS:
                cortados += 1
                if len(exemplos) < 5:
                    exemplos.append({"processo": man.parent.name, "doc": d.get("i"), "chars": c})
    pct = round(100 * cortados / docs, 2) if docs else 0.0
    return {
        "invariante": "corte_no_teto",
        "descricao": f"documentos com texto parado no teto de {TETO_CHARS} chars (amputação)",
        "medida": pct, "limite": 5.0,
        "estado": "violado" if pct > 5.0 else "ok",
        "evidencia": exemplos, "amostra_docs": docs,
    }


def inv_arquivo_vazio() -> dict:
    """Processo ARQUIVADO sem nenhum documento com texto = captura vazia gravada como sucesso.

    É a marca do falso INDISPONÍVEL (corrida da árvore) chegando ao acervo.
    """
    vazios = []
    for man in _recentes("*/manifest.json", ARQUIVO, AMOSTRA_MANIFESTS):
        try:
            m = json.loads(man.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        docs = m.get("docs") or []
        com_texto = sum(1 for d in docs if int(d.get("chars") or 0) > 50)
        if not com_texto and not m.get("captura_vazia"):
            vazios.append(man.parent.name)
    return {
        "invariante": "arquivo_sem_texto",
        "descricao": "processo arquivado sem nenhum documento com texto (captura vazia silenciosa)",
        "medida": len(vazios), "limite": 0,
        "estado": "violado" if vazios else "ok",
        "evidencia": vazios[:5],
    }


def inv_veredito_sem_prova() -> dict:
    """Veredito com escala mas SEM trecho literal — o schema proíbe; se aparecer, a validação furou."""
    if not DB.exists():
        return {"invariante": "veredito_sem_prova", "descricao": "veredito com escala e sem trecho",
                "medida": 0, "limite": 0, "estado": "indisponivel", "evidencia": ["compliance.db ausente"]}
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            n = con.execute("select count(*) from doc_veredito where escala is not null "
                            "and (trecho_literal is null or trim(trecho_literal)='')").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error as e:
        return {"invariante": "veredito_sem_prova", "descricao": "veredito com escala e sem trecho",
                "medida": 0, "limite": 0, "estado": "indisponivel", "evidencia": [str(e)[:80]]}
    return {
        "invariante": "veredito_sem_prova",
        "descricao": "veredito com escala mas sem trecho literal (prova ausente)",
        "medida": n, "limite": 0,
        "estado": "violado" if n else "ok", "evidencia": [],
    }


def inv_ciclo_chega_ao_fim() -> dict:
    """Ciclo de sweep que nunca imprime o próprio `fim` morreu NO MEIO — e morreu calado.

    O caso que criou esta invariante (2026-08-08): um passo de `sweep_sei.sh` usava `$REPO` sem
    definir a variável; com `set -u` o shell morre na expansão, o erro vai ao stderr do cron que
    ninguém lê, e TODO passo depois da linha — cpf, refichar, depurar, árvore, direcionamento,
    lex — ficou um dia e meio sem rodar. `rc` não existe para mentir: o processo simplesmente
    acaba. O único rastro auditável era a AUSÊNCIA do `say "fim"` no log, e ninguém olhava.

    A régua: dos últimos ciclos INICIADOS há mais de 6 h (folga para ciclo legítimo em curso, que
    ainda vai terminar), TODOS os N mais recentes sem `fim` = violado. Um ciclo isolado pode
    morrer por reboot ou kill de OOM; TRÊS seguidos é estrutural.
    """
    import re as _re

    logs = {"sweep_sei": RAIZ / "data" / "sweep_sei.log",
            "sweep_dados": RAIZ / "data" / "sweep_dados.log",
            "sweep_360": RAIZ / "data" / "sweep_360.log"}
    mortos = []
    for nome, lg in logs.items():
        if not lg.exists():
            continue
        # só o rabo do log — a sentinela é barata de propósito
        linhas = lg.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
        ciclos = []          # [(inicio_ts, chegou_ao_fim)]
        atual = None
        for ln in linhas:
            m = _re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (?:\[[^]]+\] )?(.*)", ln)
            if not m:
                continue
            ts, resto = m.group(1), m.group(2)
            if resto.startswith("início"):
                if atual is not None:
                    ciclos.append(atual)
                atual = [ts, False]
            elif resto.startswith("fim") and atual is not None:
                atual[1] = True
        if atual is not None:
            ciclos.append(atual)
        # ciclos velhos o bastante para já deverem ter terminado
        corte = time.time() - 6 * 3600
        velhos = [c for c in ciclos
                  if time.mktime(time.strptime(c[0], "%Y-%m-%d %H:%M:%S")) < corte]
        ult = velhos[-3:]
        if len(ult) >= 3 and not any(fim for _, fim in ult):
            mortos.append(f"{nome}: 3 ciclos iniciados (último {ult[-1][0]}) sem chegar ao fim")
    return {
        "invariante": "ciclo_chega_ao_fim",
        "descricao": "sweep que inicia e nunca imprime o próprio fim (morte silenciosa no meio)",
        "medida": len(mortos), "limite": 0,
        "estado": "violado" if mortos else "ok",
        "evidencia": mortos,
    }


def inv_colunas_deslocadas() -> dict:
    """Campo de NOME contendo VALOR = coleta gravada por posição numa tela de outra ordem.

    Medido em 2026-08-10: a coleta de junho do SIAFE 1 (19 colunas) foi gravada com o layout do
    SIAFE 2 (23 colunas). O valor foi parar em `nome_credor`, o nome do credor em `nl`, e `valor`
    ficou 0,00 — **12.073 linhas escondendo R$ 3.414.630.870,53**, e nada gritou: a chave primária
    (`numero_ob`) é a 1ª coluna e foi gravada CERTO, então a cobertura dava 100%.

    A varredura cobre TODA coluna de nome do banco (97 delas medidas na estreia); só o SIAFE
    aparecia. Barata: um COUNT com GLOB por coluna, sem regex e sem carregar linha.
    """
    from compliance_agent.reporting.intel_base import _DB

    sig = "{c} GLOB '*[0-9],[0-9][0-9]' AND {c} NOT GLOB '*[A-Za-z]*'"
    chaves = ("nome", "razao", "credor", "fornecedor", "favorecido", "socio")
    achados = []
    try:
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=60)
    except sqlite3.Error as exc:
        return {"invariante": "colunas_deslocadas", "estado": "erro", "medida": 0, "limite": 0,
                "descricao": "banco indisponível", "evidencia": [str(exc)[:120]]}
    try:
        for (t,) in con.execute(
                "select name from sqlite_master where type='table' "
                "and name not like 'sqlite_%' and name not like 'fts_%'"):
            try:
                cols = [r[1] for r in con.execute(f"pragma table_info({t})")]  # noqa: S608
            except sqlite3.Error:
                continue
            for c in cols:
                if not any(k in c.lower() for k in chaves):
                    continue
                try:
                    n = con.execute(f"select count(*) from {t} where " + sig.format(c=c)).fetchone()[0]  # noqa: S608,E501
                    tot = con.execute(f"select count(*) from {t} where coalesce({c},'') <> ''").fetchone()[0]  # noqa: S608,E501
                except sqlite3.Error:
                    continue
                # 1% de piso: nome de empresa que é só número é raro mas existe; deslocamento de
                # coluna vem em BLOCO, não pingado.
                if n and tot and n / tot > 0.01:
                    achados.append(f"{t}.{c}: {n}/{tot}")
    finally:
        con.close()
    return {
        "invariante": "colunas_deslocadas",
        "descricao": "campo de nome contendo valor monetário (coleta gravada por posição errada)",
        "medida": len(achados), "limite": 0,
        "estado": "violado" if achados else "ok",
        "evidencia": achados[:5],
    }


INVARIANTES = (inv_cache_obeso, inv_corte_no_teto, inv_arquivo_vazio, inv_veredito_sem_prova,
               inv_ciclo_chega_ao_fim, inv_colunas_deslocadas)


def checar() -> list[dict]:
    saida = []
    for fn in INVARIANTES:
        try:
            saida.append(fn())
        except Exception as e:  # noqa: BLE001 — sentinela nunca derruba o cron
            saida.append({"invariante": fn.__name__, "estado": "erro", "medida": 0,
                          "limite": 0, "descricao": "falha ao medir", "evidencia": [str(e)[:120]]})
    return saida


def _estado_prev() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _salvar_estado(res: list[dict]) -> None:
    ESTADO.write_text(json.dumps({r["invariante"]: r["estado"] for r in res},
                                 ensure_ascii=False), encoding="utf-8")


def _alertar(novos: list[dict]) -> None:
    """Telegram só na TRANSIÇÃO ok→violado (debounce por estado) — alarme repetido é alarme desligado."""
    if not novos:
        return
    linhas = ["🚨 <b>Integridade do acervo</b> — invariante violada:"]
    for r in novos:
        linhas.append(f"• <b>{r['invariante']}</b>: {r['descricao']} — medida {r['medida']} "
                      f"(limite {r['limite']})")
        if r.get("evidencia"):
            linhas.append(f"   ex.: {json.dumps(r['evidencia'][:2], ensure_ascii=False)[:180]}")
    try:
        sys.path.insert(0, str(RAIZ))
        from tools.ronda import notificar        # mesmo canal do pipelines_slo (HTML, 1 dono)
        notificar("\n".join(linhas))
    except Exception as e:  # noqa: BLE001
        print(f"[sentinela] alerta não enviado: {str(e)[:100]}", file=sys.stderr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--alerta", action="store_true", help="Telegram na transição ok→violado")
    ap.add_argument("--json", action="store_true", help="saída JSON (painel/API)")
    a = ap.parse_args(argv)

    res = checar()
    if a.json:
        print(json.dumps({"em": time.strftime("%Y-%m-%dT%H:%M:%S"), "invariantes": res},
                         ensure_ascii=False, indent=1))
    else:
        for r in res:
            marca = {"ok": "✓", "violado": "✗", "erro": "!", "indisponivel": "—"}.get(r["estado"], "?")
            print(f"{marca} {r['invariante']:22s} medida={r['medida']:<8} limite={r['limite']:<6} {r['descricao']}")
            if r["estado"] == "violado" and r.get("evidencia"):
                print(f"    evidência: {json.dumps(r['evidencia'][:3], ensure_ascii=False)[:200]}")

    prev = _estado_prev()
    novos = [r for r in res if r["estado"] == "violado" and prev.get(r["invariante"]) != "violado"]
    if a.alerta:
        _alertar(novos)
    _salvar_estado(res)
    return 1 if any(r["estado"] == "violado" for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
