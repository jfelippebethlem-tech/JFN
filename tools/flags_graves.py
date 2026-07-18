#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Registro-CONTROLE dos FLAGS VERMELHOS GRAVES da fiscalização (curado + acumulável).

Fonte estruturada dos indícios sérios já apurados, para o painel (/controle) e o digest diário no Yoda.
HONESTIDADE (regra da casa): indício ≠ acusação; EM TESE onde não provado; registrar absolvição quando houver.
Cada flag: {id, caso, titulo, gravidade(CRÍTICA/ALTA/MÉDIA), valor_r$, base_legal, status, fonte, quando}.

CLI:  .venv/bin/python tools/flags_graves.py            # tabela
      .venv/bin/python tools/flags_graves.py --seed     # (re)semeia os confirmados
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

REG = Path("/home/ubuntu/JFN/data/flags_graves.json")
_ORDEM = {"CRÍTICA": 0, "ALTA": 1, "MÉDIA": 2, "BAIXA": 3}

# Flags CONFIRMADOS da apuração Pampolha/Ambiente Jovem/Emendatio (curados à mão, honestos).
_SEED = [
    {"id": "contato-contrato-gestao", "caso": "ONG Con-tato / Ambiente Jovem", "gravidade": "CRÍTICA",
     "titulo": "Contrato de gestão 001/2021 sem licitação — chamamento 002/2021 com sessão 29/12 e "
               "assinatura 30/12/2021 (1 dia, fim de exercício); R$ 42,0→95,8 mi via 4 aditivos; FECAM.",
     "valor": 95811723.88, "base_legal": "Lei 14.133/21; Lei 6.470/13 (OS); improbidade art. 10/11 Lei 8.429/92",
     "status": "indício; Raphael Gonçalves preso na Operação Emendatio (PF 09/07/2026)",
     "fonte": "OCR dos instrumentos publicados pela ONG + SEI 070026/000705/2021"},
    {"id": "contato-troca-controle", "caso": "ONG Con-tato", "gravidade": "ALTA",
     "titulo": "Troca de controle no QSA (Tathyane Höfke, 14/05/2025) após ~71% do valor já pago "
               "(R$ 148,7 mi de R$ 208,5 mi).", "valor": 208468555.26,
     "base_legal": "indício de blindagem patrimonial", "status": "indício",
     "fonte": "QSA Receita + SIAFE/TFE (compliance.db)"},
    {"id": "lytoranea-aditivo-teto", "caso": "Lytoranea / INEA-Maxambomba", "gravidade": "ALTA",
     "titulo": "1º Termo Aditivo 110/2025 de acréscimo = 24,97% (colado no teto de 25%, art. 125 Lei "
               "14.133), assinado 19/12; contratada EM RECUPERAÇÃO JUDICIAL e impedida (sanção Fiocruz).",
     "valor": 17305130.73, "base_legal": "art. 124/125 Lei 14.133/21; art. 10 Lei 8.429/92 (dolo)",
     "status": "indício; preço/BDI com lastro EMOP (não abusivo na cara)",
     "fonte": "OCR do SEI 070002/004135/2025 (Contrato INEA 08/2025)"},
    {"id": "lytoranea-concentracao", "caso": "Lytoranea / INEA", "gravidade": "ALTA",
     "titulo": "Concentração ~R$ 321 mi do INEA (2021–2026) num único fornecedor de obras + "
               "recontratação de objeto inexecutado (Maxambomba 2022: pago R$ 398 mil de R$ 69,8 mi).",
     "valor": 321000000.0, "base_legal": "art. 11 / art. 10, VIII Lei 8.429/92 (a apurar direcionamento)",
     "status": "indício de competição restrita", "fonte": "contratos_tcerj + siafe_ob (compliance.db)"},
    {"id": "solazer-tce-esporte", "caso": "SOLAZER / Esporte RJ", "gravidade": "ALTA",
     "titulo": "TCE-RJ 107.485-1/2016 — Contrato de Gestão 002/2015, dano ~R$ 21 mi (núcleos fantasmas: "
               "5 de 31 ativos). Raphael Gonçalves presidia a SOLAZER.", "valor": 21000000.0,
     "base_legal": "dano ao erário", "status": "Pampolha e Brito ABSOLVIDOS (Plenário 26/03/2025); "
               "apuração segue contra Cabral/servidores/OS", "fonte": "Processo TCE-RJ (íntegra, Anexo B)"},
    {"id": "cedae-acordo-900mi", "caso": "CEDAE / Águas do Rio", "gravidade": "ALTA",
     "titulo": "Termo de Conciliação de ~R$ 900 mi (desconto 24,13% até 2056) NÃO deliberado pelo Conselho "
               "de Administração; voto decisivo do conselheiro-TCE Pampolha (4×3, 26/11/2025); nomeações de "
               "ex-SEAS (José Ricardo, Philipe Campello) dias após.", "valor": 900000000.0,
     "base_legal": "conflito de interesses; quid pro quo EM TESE", "status": "EM TESE; inquérito MPRJ (16/10); "
               "TCE oficiou MPRJ; NÃO provado", "fonte": "atas CEDAE (Anexo C) + imprensa/inquérito"},
    {"id": "sei-restritos", "caso": "Transparência / SEI", "gravidade": "MÉDIA",
     "titulo": "Processos-chave em acesso RESTRITO, ocultos à consulta cross-unit do itkava "
               "(AmbienteJovem 070026/000705/2021; Brasform 070028/000089/2021).", "valor": 0.0,
     "base_legal": "Lei 12.527/2011 (LAI); art. 11 Lei 8.429/92", "status": "mapeado; ver lista de restritos",
     "fonte": "tools/sei_restritos.py (data/sei_restritos.json)"},
]


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _load() -> dict:
    if REG.exists():
        try:
            return json.loads(REG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def _save(reg: dict) -> None:
    REG.parent.mkdir(parents=True, exist_ok=True)
    tmp = REG.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, REG)


def registrar(flag: dict) -> None:
    """Adiciona/atualiza um flag (por id). Preserva 'primeira'; carimba 'ultima'."""
    reg = _load()
    fid = flag["id"]
    e = reg.get(fid, {})
    e.update(flag)
    e.setdefault("primeira", _agora())
    e["ultima"] = _agora()
    reg[fid] = e
    _save(reg)


def semear() -> int:
    for f in _SEED:
        registrar(dict(f))
    return len(_SEED)


def listar() -> list[dict]:
    itens = list(_load().values())
    return sorted(itens, key=lambda e: (_ORDEM.get(e.get("gravidade", "BAIXA"), 9), e.get("caso", "")))


def _fmt_r(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    return "—" if v <= 0 else f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def resumo_texto(markdown: bool = True) -> str:
    """Resumo dos flags graves p/ o digest do Yoda (Markdown do Telegram)."""
    itens = listar()
    if not itens:
        return "Nenhum flag grave registrado."
    linhas = []
    for e in itens:
        g = e.get("gravidade", "")
        bola = {"CRÍTICA": "🔴", "ALTA": "🟠", "MÉDIA": "🟡"}.get(g, "⚪")
        v = _fmt_r(e.get("valor"))
        cabeca = f"{bola} *{g} — {e.get('caso','')}*" if markdown else f"{bola} {g} — {e.get('caso','')}"
        # rótulo explícito: é valor ENVOLVIDO (contrato/concentração), não prejuízo apurado
        linhas.append(f"{cabeca}\n{e.get('titulo','')}" + (f"\n💰 valor envolvido: {v}" if v != "—" else "")
                      + (f"\n⚖️ {e.get('base_legal','')}" if e.get("base_legal") else "")
                      + (f"\n📌 {e.get('status','')}" if e.get("status") else ""))
    return "\n\n".join(linhas)


if __name__ == "__main__":
    import sys
    if "--seed" in sys.argv[1:]:
        n = semear(); print(f"semeados {n} flags")
    for e in listar():
        print(f"[{e.get('gravidade',''):8}] {e.get('caso',''):28} {e.get('titulo','')[:70]}")
    print(f"\nTotal: {len(listar())} flags. Registro: {REG}")
