"""Chaves de casamento com os benefícios sociais do Portal da Transparência (dados abertos da CGU), a partir do
compliance.db (SÓ LEITURA). Nunca CPF completo: só a máscara pública de cada fonte.
  sócios     (QSA, máscara 4–9): "NOME NORMALIZADO|dddddd"  -> [cnpj, ...]
  servidores (folha, máscara 3–8): "NOME NORMALIZADO|ddddd" (posições 4–8, as comuns às duas máscaras)
             -> {vinc: [órgão · cargo · vínculo], meses: {"AAAA-MM": remuneração bruta}}
Uso: python -m tools.beneficios.chaves <dir_saida>"""
import json
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()).strip()


def chaves_socios(con) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for cnpj, nome, doc in con.execute("SELECT cnpj, socio_nome, socio_doc FROM socios_fornecedor WHERE socio_doc LIKE '%*%'"):
        d = re.sub(r"\D", "", doc or "")
        if len(d) == 6:
            out.setdefault(f"{norm(nome)}|{d}", []).append(cnpj)
    return out


def chaves_servidores(con) -> dict[str, dict]:
    ch: dict = defaultdict(lambda: {"vinc": set(), "meses": {}})
    for nome, cpf, orgao, cargo, vinc, comp, bruta in con.execute(
            "SELECT nome, cpf, orgao_nome, cargo, vinculo, competencia, remuneracao_bruta FROM registros_folha WHERE cpf LIKE 'XX%'"):
        d = re.sub(r"\D", "", cpf or "")
        if len(d) != 6:
            continue
        e = ch[f"{norm(nome)}|{d[1:]}"]
        e["vinc"].add(f"{orgao} · {cargo} · {vinc}"[:160])
        e["meses"][comp] = round(bruta or 0, 2)
    return {k: {"vinc": sorted(v["vinc"])[:4], "meses": v["meses"]} for k, v in ch.items()}


def main(argv: list[str]) -> int:
    saida = Path(argv[1]); saida.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect("file:data/compliance.db?mode=ro", uri=True, timeout=60)
    s, v = chaves_socios(con), chaves_servidores(con)
    json.dump(s, open(saida / "chaves_socios.json", "w"))
    json.dump(v, open(saida / "chaves_servidores.json", "w"), ensure_ascii=False)
    print(f"beneficios_chaves: socios={len(s)} servidores={len(v)}")
    return 0 if s and v else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
