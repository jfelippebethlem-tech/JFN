#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrai o cadastro NOMINAL (matrícula, nome, CPF, função, admissão, salário) das folhas de
pagamento públicas do Ambiente Jovem (ONG Con-tato, dpto FECAM). Dedup por CPF entre as ~26
competências. Fonte pública (contato.org.br) — CPFs abertos pela própria OS. Saída: JSON."""
import glob
import json
import re
import sys

from pdfminer.high_level import extract_text

PDFS = sorted(glob.glob("data/ajovem_folhas/*.pdf"))
_NUM = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})")
_CPF = re.compile(r"CPF\s*:\s*(\d{11})")
_MATNOME = re.compile(r"(\d{6})\s+([A-ZÀ-Ÿ][A-ZÀ-Ÿ .'\-]{4,60})")
_FUN = re.compile(r"Fun[çc][ãa]o\s*:\s*([^\n]+)")
_DATA = re.compile(r"(\d{2}/\d{2}/\d{4})")


def comp_de(pdf: str) -> str:
    m = re.search(r"(\d{2})[.\-]\w+-(\d{4})", pdf)
    return f"{m.group(2)}{m.group(1)}" if m else "?"


def main():
    pessoas: dict[str, dict] = {}
    for i, pdf in enumerate(PDFS, 1):
        comp = comp_de(pdf)
        try:
            t = extract_text(pdf)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(PDFS)}] ERRO {pdf}: {e}", flush=True)
            continue
        n0 = len(pessoas)
        for m in _CPF.finditer(t):
            cpf = m.group(1)
            win = t[max(0, m.start() - 500):m.start()]
            mn = _MATNOME.findall(win)
            if not mn:
                continue
            mat, nome = mn[-1][0], mn[-1][1].strip()
            fun = _FUN.search(win)
            funcao = fun.group(1).strip() if fun else ""
            adm = _DATA.search(win)
            sal = _NUM.search(win)
            if len(cpf) != 11 or not nome:
                continue
            e = pessoas.setdefault(cpf, {"cpf": cpf, "nome": nome, "funcao": funcao, "mat": mat,
                                         "adm": adm.group(1) if adm else "", "comps": set(),
                                         "sal": sal.group(1) if sal else ""})
            e["comps"].add(comp)
            if funcao:
                e["funcao"] = funcao
            if len(nome) > len(e["nome"]):
                e["nome"] = nome
        print(f"[{i}/{len(PDFS)}] {comp}: +{len(pessoas)-n0} novos · total {len(pessoas)}", flush=True)
    for e in pessoas.values():
        e["comps"] = sorted(e["comps"])
    json.dump(sorted(pessoas.values(), key=lambda x: x["nome"]),
              open("data/ajovem_contratados.json", "w"), ensure_ascii=False, indent=1)
    print(f"FIM — {len(pessoas)} pessoas únicas por CPF", flush=True)


if __name__ == "__main__":
    sys.exit(main())
