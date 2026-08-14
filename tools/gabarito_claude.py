# -*- coding: utf-8 -*-
"""Confronto MEDIDO entre a leitura do Claude, a da LLM gratuita e a da régua determinística.

POR QUE ESTE ARQUIVO EXISTE. A leitura dupla (regra × LLM grátis) extrai sinal da DIVERGÊNCIA entre
os dois — e divergência só enxerga campo que alguém perguntou. Os dois maiores achados de leitura
desta sessão vieram de fora dela, de um terceiro leitor sem o formulário na mão:

  · a **Ata de Registro de Preços**, instrumento presente em 21% do acervo e que ninguém perguntava
    (a LLM respondia `contrato: NAO_CONSTA` e estava CERTA — só que o instrumento existia);
  · a **regra tributária da planilha de retenção** (`Art. 2º-A da IN RFB nº 1234`), que fundamenta
    RETENÇÃO DE IMPOSTO com a mesma fórmula do fundamento da despesa, e entrava limpa.

Nos dois casos os dois leitores CONCORDAVAM, e o laudo saía completo e errado por omissão.

E o confronto corta os dois lados: num processo dei como falso positivo um ARP que a régua achara, e
o texto de fato trazia `ade- são de ata de registro de preços nº 007/2022`, quebrado por hifenização
de linha. **Eu li um trecho; ela leu o documento.** A leitura do Claude não é gabarito automático —
é a terceira opinião, e vale pelo que sobrevive à conferência.

O gabarito ACUMULA: cada rodada acrescenta processos lidos à mão, e o placar é recalculado sobre
todos. Sem isso, cada confronto morre na rodada em que aconteceu e vira anedota.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_GAB = _REPO / "data" / "gabaritos_sei.json"
_DB = _REPO / "data" / "compliance.db"

# Só os campos objetivamente conferíveis. `o_que_e` e `chama_atencao` são juízo — entram no laudo,
# não no placar, porque discordância de redação não é erro de leitura.
CAMPOS = ("contrato", "pregao", "arp", "dispositivo", "favorecido")


def _so_digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


# `?` = NÃO CONFERI. Distinção que o primeiro placar exigiu: eu havia marcado `NAO_CONSTA` no
# `favorecido` de vários processos onde simplesmente não fui atrás do CNPJ, e a régua — que o tira
# da Ordem Bancária, fonte canônica — apareceu com 33% de acerto. Gabarito que afirma AUSÊNCIA onde
# o leitor apenas NÃO OLHOU pune justamente quem acertou. Campo com `?` sai do placar.
NAO_CONFERI = "?"


def _ausente(v) -> bool:
    return _so_digitos(v) == "" or str(v).strip().upper() in {
        "NAO_CONSTA", "NÃO_CONSTA", "N/A", "NONE", "NULL", "", "SEM CONTRATO"}


def concorda(a, b) -> bool:
    """Mesma resposta, tolerando grafia — `PE 008/23` × `008/23`, `R$ 1.000,00` × `1000.00`.

    Ausência casa com ausência: `NAO_CONSTA`, vazio e `SEM CONTRATO` afirmam a mesma coisa, e tratar
    isso como divergência foi o defeito que afogou 61 das 77 primeiras linhas da fila.
    """
    if _ausente(a) and _ausente(b):
        return True
    if _ausente(a) or _ausente(b):
        return False
    da, db = _so_digitos(a), _so_digitos(b)
    return da == db or da in db or db in da


def carregar() -> dict:
    if not _GAB.exists():
        return {}
    try:
        d = json.loads(_GAB.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def gravar(proc: str, respostas: dict, fonte: str = "claude") -> dict:
    """Acrescenta (ou corrige) a leitura do Claude para um processo. Read-modify-write no disco.

    Relê o arquivo ANTES de escrever: gravar índice sem reler apaga trabalho alheio — a casa já
    perdeu 22 processos assim.
    """
    d = carregar()
    d[proc] = {**{k: respostas.get(k, "") for k in CAMPOS}, "fonte": fonte}
    _GAB.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def placar() -> dict:
    """Quanto a LLM grátis e a régua acertam CONTRA a leitura do Claude, campo a campo."""
    gab = carregar()
    if not gab:
        return {"ok": False, "erro": "gabarito vazio"}
    con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=60)
    try:
        linhas = {r[0]: r for r in con.execute(
            "SELECT numero_sei, deterministico, ia FROM sei_leitura_dupla")}
    finally:
        con.close()
    r = {"processos": 0, "ia": {}, "regra": {}}
    de_para = {"favorecido": "cnpjs", "arp": "arp"}
    for proc, esperado in gab.items():
        linha = linhas.get(proc)
        if not linha:
            continue
        r["processos"] += 1
        det = json.loads(linha[1] or "{}")
        ia = (json.loads(linha[2] or "{}").get("fatos") or {})
        for campo in CAMPOS:
            alvo = esperado.get(campo, "")
            if str(alvo).strip() == NAO_CONFERI:
                continue                      # não conferi: não conta a favor nem contra ninguém
            v_ia = ia.get(campo, "")
            v_re = (det.get(de_para.get(campo, campo)) or {}).get("valor", "")
            for quem, valor in (("ia", v_ia), ("regra", v_re)):
                b = r[quem].setdefault(campo, {"acerto": 0, "erro": 0})
                b["acerto" if concorda(alvo, valor) else "erro"] += 1
    return {"ok": True, **r}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--gravar", help="processo a registrar (com --campos)")
    ap.add_argument("--campos", help='JSON: {"contrato":"85/2022","arp":"NAO_CONSTA",...}')
    ap.add_argument("--placar", action="store_true")
    a = ap.parse_args(argv)
    if a.gravar and a.campos:
        d = gravar(a.gravar, json.loads(a.campos))
        print(f"gabarito: {len(d)} processos lidos pelo Claude")
        return 0
    p = placar()
    if not p.get("ok"):
        print(p.get("erro"), file=sys.stderr)
        return 1
    print(f"placar contra a leitura do Claude — {p['processos']} processos\n")
    print(f"{'campo':12} {'LLM grátis':>14}   {'régua':>14}")
    for campo in CAMPOS:
        i, g = p["ia"].get(campo, {}), p["regra"].get(campo, {})
        ti, tg = i.get("acerto", 0) + i.get("erro", 0), g.get("acerto", 0) + g.get("erro", 0)
        pi = f"{i.get('acerto',0)}/{ti} ({100*i.get('acerto',0)//max(ti,1)}%)"
        pg = f"{g.get('acerto',0)}/{tg} ({100*g.get('acerto',0)//max(tg,1)}%)"
        print(f"{campo:12} {pi:>14}   {pg:>14}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
