# -*- coding: utf-8 -*-
"""SEI FALSO para os testes do E2/E3 (O3.3): árvore paginada de 10 em 10 (como a lista de documentos do SEI) e uma
captura que imita o CONTRATO de saída de tools/sei_integra_completa.py — `manifest.json` (docs com i/arquivo/título/
id_documento/ok/via e `pdf_lotes`), `NNN.pdf` e `donos.json` (dono de cada arquivo pelo id) —, o delta pelo
`captura_delta.plano_de_captura` de verdade, lotes de 40 e documentos OMITIDOS CALADOS pelo "Gerar PDF" que, se
`perder_no_laco`, o laço também não recupera. Nenhum navegador, nenhuma rede."""
from __future__ import annotations

import json
from pathlib import Path

from compliance_agent import captura_delta as CD
from compliance_agent.aplicacao.estagios.arvore import PaginaArvore
from compliance_agent.dominio import processo_id as PI


def arvore_falsa(n: int, base: int = 90_000_000, restritos: tuple[int, ...] = ()) -> list[dict]:
    return [{"t": f"Despacho de teste {k} ({base + k})", "u": f"controlador.php?acao=arvore_visualizar&id_documento="
             f"{500_000 + k}", "restrito": k in restritos} for k in range(n)]


class SEIFalso:
    def __init__(self, docs: list[dict], por_pagina: int = 10, omitir_no_pdf: set[int] = frozenset(),
                 perder_no_laco: set[int] = frozenset(), travar_paginacao: bool = False):
        self.docs = docs
        self.por_pagina = por_pagina
        self.omitir_no_pdf = set(omitir_no_pdf)       # posições que o "Gerar PDF" omite caladas
        self.perder_no_laco = set(perder_no_laco)     # ...e que o laço doc a doc também não traz (1ª vez)
        self.travar = travar_paginacao
        self.paginas_pedidas: list[int] = []
        self.baixados: list[list[int]] = []           # posições baixadas em cada chamada de capturar
        self.lotes: list[list[int]] = []

    # ── E2 ──
    def arvore(self, processo: str, pagina: int) -> PaginaArvore:
        self.paginas_pedidas.append(pagina)
        if self.travar and pagina >= 2 * self.por_pagina:
            return PaginaArvore(docs=self.docs[:self.por_pagina], proxima=pagina + self.por_pagina, via="teste")
        fatia = self.docs[pagina:pagina + self.por_pagina]
        prox = pagina + self.por_pagina if pagina + self.por_pagina < len(self.docs) else None
        return PaginaArvore(docs=fatia, proxima=prox, via="teste")

    # ── E3 ──
    def capturar(self, processo: str, guardados: dict, raiz: Path) -> Path:
        outdir = Path(raiz) / f"integra_{PI.pasta(processo)}"
        outdir.mkdir(parents=True, exist_ok=True)
        plano = CD.plano_de_captura(self.docs, CD.carregar_guardados(guardados))
        manter = {e["i"] for e in plano["manter"]}
        donos_p = outdir / "donos.json"
        donos = json.loads(donos_p.read_text()) if donos_p.exists() else {}
        alvo = [i for i in range(len(self.docs)) if i not in manter and not self.docs[i].get("restrito")
                and donos.get(f"{i:03d}.pdf") != CD._id_documento(self.docs[i])]
        lotes = [alvo[k:k + 40] for k in range(0, len(alvo), 40)]
        self.lotes.append([len(lt) for lt in lotes])
        via, omit = {}, []
        for lt in lotes:
            for i in lt:
                if i in self.omitir_no_pdf:
                    omit.append(i)
                    continue
                via[i] = "pdf_nativo"
        baixados = []
        manifest = []
        for i, x in enumerate(self.docs):
            fp = outdir / f"{i:03d}.pdf"
            idd = CD._id_documento(x)
            ok, v = False, None
            if donos.get(fp.name) == idd and fp.exists():
                ok, v = True, "retomado"
            elif i in manter:
                v = "delta_guardado"
            elif x.get("restrito"):
                v = None
            elif i in via or (i in omit and i not in self.perder_no_laco):
                fp.write_bytes(f"%PDF-falso {processo} {idd} {x['t']}".encode())
                donos[fp.name] = idd
                ok, v = True, via.get(i, "arvore")
                baixados.append(i)
            manifest.append({"i": i, "arquivo": fp.name, "titulo": x["t"], "contexto": "", "url": x["u"],
                             "id_documento": idd, "ok": ok, **({"via": v} if v else {})})
        self.perder_no_laco = set()                   # na próxima tentativa o laço consegue
        self.omitir_no_pdf = set()
        self.baixados.append(baixados)
        donos_p.write_text(json.dumps(donos))
        (outdir / "manifest.json").write_text(json.dumps({
            "processo": processo, "total_arvore": len(self.docs), "completo": True,
            "pdf_lotes": {"via_pdf": len(via), "lotes_ok": len(lotes), "lotes_pedidos": len(lotes),
                          "omitidos": [{"i": i} for i in omit], "recusados": [], "pendentes_janela": 0},
            "docs": manifest}, ensure_ascii=False))
        return outdir
