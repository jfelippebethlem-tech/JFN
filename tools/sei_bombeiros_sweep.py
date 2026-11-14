#!/usr/bin/env python3
"""Coleta SEI dos contratos do FUNESBOM (CBMERJ) 2024+, na ORDEM DE SUSPEITA (score de triagem).
Reusa 100% o pipeline canônico (tools.sei_sweep.run): browser_lock_async, login itkava único, retry,
_ficha_e_storage, checkpoint resumível. Só TROCA a fonte da fila (contratos_tcerj, não ordens_bancarias),
porque as OBs dos bombeiros não trazem nº SEI. Bounded + resumível: relançar drena em ordem de prioridade.

Uso:  PYTHONPATH=. .venv/bin/python -m tools.sei_bombeiros_sweep --max 12
Sem Gemini (GEMINI_DISABLED=1 global; ficha usa stepfun:free/nous). Honestidade: indício != acusação."""
import asyncio
import argparse
import json
import os
import pathlib
import tools.sei_sweep as S

FILA = pathlib.Path("data/bombeiros_sei_fila.json")

PISO_VALOR = 1000.0


def _valor(x: dict) -> float:
    try:
        return float(x.get("valor") or 0)
    except (TypeError, ValueError):
        return 0.0


def _cascata(x: dict, tipo: dict) -> bool:
    """Item de 2ª geração ou mais: "licitação" enfileirada por ter sido CITADA num processo que já era
    ele próprio uma "licitação" enfileirada (`bombeiros_achar_edital`), não por um contrato."""
    if x.get("tipo") != "LICITACAO":
        return False
    pais = [f.split(":", 1)[1] for f in (x.get("flags") or []) if str(f).startswith("LICITACAO_DE:")]
    return any(tipo.get(p) == "LICITACAO" for p in pais)


def _carregar_fila():
    itens = json.loads(FILA.read_text(encoding="utf-8"))
    # CONTRATOS ANTES DA CASCATA (13/11/2026): 7.105 de 9.659 itens eram "licitação de licitação" no
    # topo do arquivo, herdando o valor de quem os citou (3.202 com o mesmo "R$ 617"), e 1.051
    # contratos — o alvo desta lane — nunca tinham sido lidos. Rebaixa, não exclui; ordem do arquivo
    # preservada dentro de cada grupo (sort estável). Dentro do grupo, valor abaixo de PISO_VALOR vai
    # para o fim (laudo dos motores: < 20% das leituras abaixo de R$ 1.000,00) — também rebaixado, não
    # excluído; item sem valor (0) é INDISPONÍVEL, não ínfimo, e não é rebaixado por isso.
    tipo = {x.get("sei"): x.get("tipo") for x in itens}
    if os.environ.get("BBM_INCLUIR_CASCATA", "").strip() in ("1", "true", "sim"):
        itens = sorted(itens, key=lambda x: (_cascata(x, tipo), 0 < _valor(x) < PISO_VALOR))
    else:
        # SÓ CONTRATOS (decisão do dono, 13/11/2026 noite): a cascata sai da lane — 7.108 itens (74% da fila)
        # enquanto 1.037 contratos nunca tinham sido lidos. Contrato (LICITADO/DIRETA/CONTRATO) primeiro, a
        # licitação de 1ª geração (citada por um contrato) depois. `BBM_INCLUIR_CASCATA=1` desfaz.
        itens = sorted((x for x in itens if not _cascata(x, tipo)),
                       key=lambda x: (x.get("tipo") == "LICITACAO", 0 < _valor(x) < PISO_VALOR))
    # (proc, nob, tot) — nob fica 1 (só p/ log); tot=valor do contrato (ordena o log, prioridade já no arquivo)
    return [(x["sei"], 1, float(x.get("valor") or 0)) for x in itens]

def main():
    ap = argparse.ArgumentParser(description="SEI sweep priorizado dos contratos do FUNESBOM")
    ap.add_argument("--max", type=int, default=12)
    a = ap.parse_args()
    fila_bombeiros = _carregar_fila()
    # pausa INDEPENDENTE: não obedece o .pause_sei_sweep do sweep principal (controle próprio).
    S.PAUSE = pathlib.Path("data/.pause_bombeiros")
    # injeta a fila dos bombeiros no run() canônico (ignora o LIMIT do SQL original; run() filtra _pular
    # e fatia [:max_n], então devolvemos a lista inteira já priorizada e a coleta drena em prioridade).
    S._fila = lambda ug, limite, cnpj=None: fila_bombeiros
    S._log(f"[bombeiros] fila priorizada: {len(fila_bombeiros)} contratos; lote --max {a.max} (árvore prof.=6)")
    # segue a árvore de relacionados mais fundo: a licitação/contrato costuma estar no processo-pai,
    # não no nº de pagamento/registro (achado do teste paralelo Link Card).
    asyncio.run(S.run(max_n=a.max, ug=None, diario=False, max_rel_arvore=6))

if __name__ == "__main__":
    main()
