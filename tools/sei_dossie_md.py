#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera o dossiê .md de um processo SEI, fracionando só quando ele não cabe no modelo.

    .venv/bin/python tools/sei_dossie_md.py 030001_004946_2026 [--vault] [--plano]
    .venv/bin/python tools/sei_dossie_md.py --maiores 5 --plano

`--plano` mostra a decisão de leitura e NÃO chama IA — use sempre antes de gastar chamada num
processo grande. `--vault` grava também no segundo cérebro (`~/vault/processos/`), que é onde o
conhecimento fica pesquisável entre sessões.

Escolha de modelo: perfil `documento` do catálogo vivo (`openrouter_catalogo`), que exige um
piso de capacidade — ler peça processual com modelo pequeno produz leitura errada com aparência
de leitura certa. Se o catálogo estiver fora do ar, cai para `best_free_chat`, e o dossiê
registra no cabeçalho qual modelo de fato respondeu.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

ACERVO = pathlib.Path(os.environ.get("JFN_SEI_ARQUIVO", "data/sei_arquivo"))
SAIDA = pathlib.Path("output/dossies")
VAULT = pathlib.Path(os.path.expanduser("~/vault/processos"))


def _contexto_do_modelo(model_id: str, padrao: int = 128_000) -> int:
    from compliance_agent.llm.openrouter_catalogo import catalogo
    for m in catalogo():
        if m["id"] == model_id:
            return int(m.get("ctx") or padrao)
    return padrao


def _chamar(model_id: str, sistema: str, prompt: str) -> str:
    """Modelo escolhido primeiro; a cadeia grátis como rede. Vazio = não deu, e quem chama declara."""
    if model_id:
        try:
            import httpx
            r = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                json={"model": model_id,
                      "messages": [{"role": "system", "content": sistema},
                                   {"role": "user", "content": prompt}],
                      "max_tokens": 4000, "temperature": 0.1},
                timeout=300)
            r.raise_for_status()
            return (r.json()["choices"][0]["message"].get("content") or "").strip()
        except Exception as e:  # noqa: BLE001 — cai para a cadeia, mas diz o porquê
            print(f"    modelo {model_id} falhou ({type(e).__name__}) — usando a cadeia grátis")
    try:
        from compliance_agent.llm.free_llm import best_free_chat
        return best_free_chat(prompt, system=sistema, smart=True, fallback="")
    except Exception as e:  # noqa: BLE001
        print(f"    cadeia grátis indisponível ({type(e).__name__})")
        return ""


def gerar(nome_pasta: str, *, so_plano: bool = False, vault: bool = False) -> pathlib.Path | None:
    from compliance_agent.sei.dossie_fracionado import (
        cabecalho_md, planejar, prompt_map, prompt_reduce,
    )
    from compliance_agent.llm.openrouter_catalogo import escolher

    pasta = ACERVO / nome_pasta
    if not pasta.is_dir():
        print(f"processo não encontrado no acervo: {pasta}")
        return None

    modelo = escolher("documento") or ""
    ctx = _contexto_do_modelo(modelo) if modelo else 128_000
    plano = planejar(nome_pasta, pasta, contexto_modelo=ctx)

    print(f"{nome_pasta}: {plano.n_docs} doc(s) com texto · {plano.tokens_total:,} tokens est. "
          f"· modelo {modelo or '(cadeia grátis)'} ctx={ctx:,}".replace(",", "."))
    print(f"  → {'cabe inteiro' if plano.cabe_inteiro else f'fracionado em {len(plano.lotes)} lote(s)'}"
          f" · orçamento por lote {plano.orcamento:,} tokens".replace(",", "."))
    if plano.docs_vazios:
        print(f"  ⚠️  {plano.docs_vazios} documento(s) sem texto — não serão lidos")
    if so_plano:
        return None

    blocos: list[str] = []
    for lote in plano.lotes:
        sistema, prompt = prompt_map(lote)
        t0 = time.monotonic()
        saida = _chamar(modelo, sistema, prompt)
        print(f"  lote {lote.indice}/{len(plano.lotes)}: {len(lote.docs)} doc(s) · "
              f"{lote.tokens:,} tk · {time.monotonic() - t0:.0f}s · "
              f"{'ok' if saida else 'SEM RESPOSTA'}".replace(",", "."))
        blocos.append(saida or f"_(lote {lote.indice} não pôde ser lido — nenhum provedor "
                               "respondeu; os documentos deste lote NÃO entraram no dossiê)_")

    if len(blocos) == 1:
        corpo = blocos[0]
    else:
        sistema, prompt = prompt_reduce(nome_pasta, blocos)
        corpo = _chamar(modelo, sistema, prompt) or "\n\n".join(blocos)

    md = cabecalho_md(plano, modelo or "cadeia grátis") + "\n" + corpo + "\n"
    try:
        from compliance_agent.reporting.neutralidade import garantir_neutro
        md = garantir_neutro(md, contexto=f"dossiê {nome_pasta}")
    except Exception as e:  # noqa: BLE001 — o gate não pode impedir a entrega do trabalho
        print(f"  gate de neutralidade não rodou ({type(e).__name__})")

    SAIDA.mkdir(parents=True, exist_ok=True)
    destino = SAIDA / f"{nome_pasta}.md"
    destino.write_text(md)
    print(f"  gravado: {destino}")
    if vault:
        VAULT.mkdir(parents=True, exist_ok=True)
        (VAULT / f"{nome_pasta}.md").write_text(md)
        print(f"  segundo cérebro: {VAULT / f'{nome_pasta}.md'}")
    return destino


def _maiores(n: int) -> list[str]:
    tam = []
    for p in ACERVO.iterdir():
        td = p / "texto"
        if td.is_dir():
            b = sum(f.stat().st_size for f in td.glob("*.txt"))
            if b:
                tam.append((b, p.name))
    return [nome for _, nome in sorted(tam, reverse=True)[:n]]


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("processo", nargs="*")
    ap.add_argument("--maiores", type=int, help="usa os N maiores processos do acervo")
    ap.add_argument("--plano", action="store_true", help="só decide a leitura; não chama IA")
    ap.add_argument("--vault", action="store_true", help="grava também em ~/vault/processos/")
    a = ap.parse_args()

    alvos = list(a.processo) + (_maiores(a.maiores) if a.maiores else [])
    if not alvos:
        ap.error("informe ao menos um processo ou --maiores N")
    for nome in alvos:
        gerar(nome, so_plano=a.plano, vault=a.vault)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
