#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inventário HONESTO da captura do SEI: o que temos, o que falta e o que está SOB SIGILO.

Responde três perguntas que o projeto não sabia responder:

  1. **O sweep está capturando tudo o que é possível?** Reconcilia o que o pipeline de análise
     conhece (`sei_arvore`) com o que existe em texto no disco (`data/sei_arquivo/`) e com o
     cache de varredura (`data/sei_cache/`). O que é conhecido e não tem texto é fila de captura.

  2. **Quais processos estão sob sigilo?** O detector já existia em `sei/navegador.py` e
     `collectors/sei_cdp.py` (cadeado, `n_docs_restritos`) — mas o resultado nunca foi PERSISTIDO:
     `processos_sei.nivel_acesso` está vazio. Este módulo recupera o sinal dos 5.663 caches já
     gravados, sem recrawl, e materializa a tabela `sei_sigilo`.

  3. **A árvore de documentos carregou?** `arvore_carregou=False` significa que vimos a capa do
     processo mas não a lista de documentos — captura estruturalmente incompleta, e nada no
     sistema distinguia isso de "processo com poucos documentos".

Por que sigilo importa aqui: processo administrativo de contratação é PÚBLICO (art. 5º, XXXIII,
CF; Lei 12.527/2011, art. 7º, §3º; art. 13 da Lei 14.133/2021). Restrição de acesso em processo
com pagamento já efetuado é ela mesma um achado — e, para o gabinete, a lista serve para
requisição FORMAL (CF art. 50, §2º; requerimento de informação / CPI), que não depende de portal.

    .venv/bin/python tools/sei_inventario_captura.py [--gravar]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
from datetime import datetime

CACHE = pathlib.Path(os.environ.get("JFN_SEI_CACHE", "data/sei_cache"))
ACERVO = pathlib.Path(os.environ.get("JFN_SEI_ARQUIVO", "data/sei_arquivo"))
DB = os.environ.get("JFN_DB", "data/compliance.db")


def so_digitos(s) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS sei_sigilo (
            numero_sei TEXT PRIMARY KEY,
            sei_norm TEXT,
            cadeado INTEGER,          -- processo marcado como restrito
            n_docs_restritos INTEGER, -- documentos individualmente restritos
            arvore_carregou INTEGER,  -- 1 carregou · 0 não carregou · NULL não aferível (via cracked)
            n_docs INTEGER,
            tem_texto_local INTEGER,  -- há pasta em data/sei_arquivo com texto
            fonte TEXT,
            visto_em TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_sigilo_cadeado ON sei_sigilo(cadeado);
        CREATE INDEX IF NOT EXISTS ix_sigilo_norm ON sei_sigilo(sei_norm);
        CREATE TABLE IF NOT EXISTS sei_fila_captura (
            numero_sei TEXT PRIMARY KEY, sei_norm TEXT, motivo TEXT,
            total_pago REAL, n_docs INTEGER, visto_em TEXT
        );
    """)
    con.commit()


def _arvore_carregou(d: dict) -> int | None:
    """1 = carregou · 0 = NÃO carregou (medido) · None = não aferível neste caminho de leitura.

    O leitor tem dois caminhos: o normal, que carrega a árvore lazy-load e SETA o campo, e o
    `cracked`, que lê direto e nunca o toca — deixando o `False` do dicionário inicial. Tratar
    esse default como medição gerou dois alarmes falsos em 2026-07-27: "2.579 capturas
    estruturalmente incompletas" e, na investigação seguinte, "falha de captcha em massa" (mesma
    causa — `captcha_resolvido` também nasce False). Dos caches com o campo False, 200 de 200
    amostrados eram `via='cracked'` e TINHAM documentos: leitura bem-sucedida.
    """
    via = (d.get("via") or "").strip().lower()
    valor = d.get("arvore_carregou")
    if via == "cracked":
        return None                       # este caminho não afere a árvore; o False é default
    if valor is False:
        # False com documentos na mão é contraditório: a leitura trouxe conteúdo.
        return None if (d.get("documentos") or []) else 0
    return 1


def ler_caches() -> dict[str, dict]:
    """Um registro por processo, a partir do cache de varredura já gravado (sem rede)."""
    out: dict[str, dict] = {}
    if not CACHE.is_dir():
        return out
    for f in sorted(CACHE.glob("cdp_SEI_*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        num = d.get("numero") or f.stem.replace("cdp_SEI_", "").replace("_", "/")
        docs = d.get("documentos") or []
        out[so_digitos(num)] = {
            "numero_sei": num,
            "cadeado": 1 if d.get("cadeado") else 0,
            "n_docs_restritos": int(d.get("n_docs_restritos") or 0),
            # `arvore_carregou` SÓ é confiável no caminho de leitura que a preenche. O leitor
            # tem dois caminhos: o normal (que carrega a árvore lazy-load e seta o campo) e o
            # `cracked` (que lê direto e NUNCA toca no campo, deixando-o no default False do
            # dicionário inicial). Medido em 2026-07-27: dos caches com o campo False, 200 de 200
            # amostrados eram `via='cracked'` E TINHAM documentos — leitura bem-sucedida.
            # Tratar esse default como "árvore não carregou" produziu um alarme falso de 2.579
            # capturas incompletas, e depois um segundo alarme falso de "falha de captcha em
            # massa" (mesma causa: `captcha_resolvido` também nasce False e o caminho cracked não
            # o atualiza). É o erro que a casa combate — INDISPONÍVEL ≠ 0 — do nosso lado.
            "arvore_carregou": _arvore_carregou(d),
            "via": (d.get("via") or "") or None,
            "n_docs": len(docs) if isinstance(docs, list) else 0,
            "fonte": f.name,
        }
    return out


def textos_locais() -> set[str]:
    """Processos com pelo menos um .txt capturado."""
    if not ACERVO.is_dir():
        return set()
    return {so_digitos(p.name) for p in ACERVO.iterdir()
            if p.is_dir() and (p / "texto").is_dir() and any((p / "texto").glob("*.txt"))}


def conhecidos(con: sqlite3.Connection) -> dict[str, dict]:
    """O que o pipeline de análise já sabe existir (com valor pago, quando houver)."""
    out: dict[str, dict] = {}
    try:
        rows = con.execute("SELECT numero_sei, total_pago, n_docs FROM sei_arvore").fetchall()
    except sqlite3.OperationalError:
        return out
    for num, pago, nd in rows:
        out[so_digitos(num)] = {"numero_sei": num, "total_pago": pago or 0.0,
                                "n_docs": nd or 0}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gravar", action="store_true", help="materializa sei_sigilo e sei_fila_captura")
    args = ap.parse_args()

    con = sqlite3.connect(DB, timeout=60)
    cache = ler_caches()
    locais = textos_locais()
    conh = conhecidos(con)
    agora = datetime.now().isoformat(timespec="seconds")

    print("=" * 74)
    print("COBERTURA DA CAPTURA")
    print("=" * 74)
    print(f"  conhecidos pelo pipeline (sei_arvore) : {len(conh):>6}")
    print(f"  com texto capturado no disco          : {len(locais):>6}")
    print(f"  com cache de varredura                : {len(cache):>6}")
    universo = set(conh) | set(locais) | set(cache)
    print(f"  UNIVERSO (união)                      : {len(universo):>6}")
    sem_texto = universo - locais
    print(f"  sem texto algum                       : {len(sem_texto):>6}"
          f"  ({len(sem_texto)*100//max(1,len(universo))}% do universo)")
    conh_sem_texto = set(conh) - locais
    print(f"  conhecidos E sem texto (fila real)    : {len(conh_sem_texto):>6}")
    valor_na_fila = sum(conh[k]["total_pago"] for k in conh_sem_texto)
    print(f"  valor pago represado nessa fila        : R$ {valor_na_fila:>18,.2f}")

    print()
    print("=" * 74)
    print("SIGILO / RESTRIÇÃO DE ACESSO")
    print("=" * 74)
    restritos = {k: v for k, v in cache.items() if v["cadeado"] or v["n_docs_restritos"]}
    # FORÇA DA EVIDÊNCIA — testada, não presumida.
    #
    # A suspeita inicial era de que o cadeado fosse artefato: o seletor em
    # `sei_cdp._JS_LE_ARVORE_E_TEXTO` inclui `[class*="restrit" i]`, que casa qualquer elemento
    # com "restrit" na classe, e `n_docs_restritos` vem 0 em 100% dos casos. Dois testes de
    # correlação REFUTARAM a suspeita (medido em 5.663 caches, 2026-07-27):
    #
    #   · taxa de cadeado entre caches SEM documentos : 76/339  = 22,42%
    #   · taxa de cadeado entre caches COM documentos :  1/5324 =  0,02%
    #     → mil vezes de diferença. Artefato de CSS apareceria em proporção parecida nos dois.
    #   · distribuição por órgão: 20 UGs distintas, taxas de 1,3% a 28,6%
    #     → não é template de um órgão (seria ~100% dentro dele).
    #
    # Conclusão: o cadeado é SINAL REAL de restrição de acesso. A assinatura canônica é
    # "árvore reportou carregamento, zero documentos visíveis, cadeado presente" — que é
    # exatamente o que um processo restrito produz. Os 263 caches com 0 documentos e SEM
    # cadeado são o grupo de falha técnica / processo vazio, e ficam fora desta lista.
    com_lista = {k: v for k, v in restritos.items()
                 if v["n_docs_restritos"] > 0 or v["n_docs"] > 0}
    sem_lista = {k: v for k, v in restritos.items() if k not in com_lista}
    print(f"  com marcador de restrição (cadeado)         : {len(restritos):>5}")
    print(f"    · restrição com lista parcialmente visível: {len(com_lista):>5}")
    print(f"    · restrição que ZERA a lista de documentos: {len(sem_lista):>5}"
          "   <- assinatura canônica de sigilo")
    com_pago = [(k, v) for k, v in restritos.items() if conh.get(k, {}).get("total_pago", 0) > 0]
    print(f"  destes, JÁ COM PAGAMENTO registrado         : {len(com_pago):>5}"
          "   <- se confirmado, achado autônomo: contratação paga é pública")
    nao_carregou = sum(1 for v in cache.values() if v["arvore_carregou"] == 0)
    nao_afericao = sum(1 for v in cache.values() if v["arvore_carregou"] is None)
    print(f"  árvore de documentos NÃO carregou           : {nao_carregou:>5}"
          "   <- captura de fato incompleta")
    print(f"  árvore NÃO AFERÍVEL (lido por outro caminho): {nao_afericao:>5}"
          "   <- leitura OK; o campo não se aplica")

    for rot, grupo in (("RESTRIÇÃO COM LISTA VISÍVEL", com_lista),
                       ("RESTRIÇÃO QUE ZERA A LISTA", sem_lista)):
        if not grupo:
            continue
        print(f"\n  --- {rot} ({len(grupo)}) — candidatos a requisição FORMAL ---")
        ordenado = sorted(grupo.items(),
                          key=lambda kv: -conh.get(kv[0], {}).get("total_pago", 0))
        for k, v in ordenado[:30]:
            pago = conh.get(k, {}).get("total_pago", 0)
            marca = "TEM TEXTO" if k in locais else "SEM TEXTO"
            print(f"    {v['numero_sei']:28} docs={v['n_docs']:>3} restr={v['n_docs_restritos']:>2}"
                  f"  pago=R$ {pago:>14,.2f}  {marca}")
        if len(ordenado) > 30:
            print(f"    ... e mais {len(ordenado)-30} (lista completa em sei_sigilo)")

    if args.gravar:
        init_schema(con)
        con.executemany(
            "INSERT OR REPLACE INTO sei_sigilo VALUES (?,?,?,?,?,?,?,?,?)",
            [(v["numero_sei"], k, v["cadeado"], v["n_docs_restritos"], v["arvore_carregou"],
              v["n_docs"], 1 if k in locais else 0, v["fonte"], agora)
             for k, v in cache.items()])
        con.executemany(
            "INSERT OR REPLACE INTO sei_fila_captura VALUES (?,?,?,?,?,?)",
            [(conh[k]["numero_sei"], k,
              "restrito" if k in restritos else
              ("arvore_nao_carregou" if cache.get(k, {}).get("arvore_carregou") == 0
               else "nunca_capturado"),
              conh[k]["total_pago"], conh[k]["n_docs"], agora)
             for k in sorted(conh_sem_texto)])
        con.commit()
        print(f"\ngravado: sei_sigilo ({len(cache)}) · sei_fila_captura ({len(conh_sem_texto)})")
    else:
        print("\n(somente leitura — use --gravar para materializar as tabelas)")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
