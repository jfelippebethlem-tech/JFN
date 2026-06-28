#!/usr/bin/env python3
"""Acha a LICITAÇÃO (pregão/edital) de cada contrato do FUNESBOM já coletado e a ENFILEIRA p/ coleta.
SEI é a fonte fiel (PNCP cobre mal o RJ): varre o texto dos docs coletados procurando
  - nº de pregão/edital ("Pregão Eletrônico nº NNN/AAAA", "Edital nº ...")
  - processos SEI relacionados que NÃO são o próprio contrato (candidatos a processo de licitação)
e injeta os processos-licitação novos no topo da `bombeiros_sei_fila.json` (prioridade alta), p/ o sweep
coletar o edital/ata → destrava direcionamento (ata/desclassificações) e sobrepreço (TR/itens).
Determinístico (regex), idempotente. Honestidade: indício≠acusação."""
import json, re, pathlib, sqlite3

CACHE = pathlib.Path("data/sei_cache")
FILA = pathlib.Path("data/bombeiros_sei_fila.json")
MAP = pathlib.Path("reports/_bombeiros_edital_map.json")

RE_PREGAO = re.compile(r"(?:preg[ãa]o\s+eletr[ôo]nico|preg[ãa]o|concorr[êe]ncia|tomada\s+de\s+pre[çc]os)\s*n?[ºo.]*\s*(\d{1,4}/\d{4})", re.I)
RE_EDITAL = re.compile(r"edital\s*n?[ºo.]*\s*(\d{1,4}/\d{4})", re.I)
RE_SEI = re.compile(r"SEI[-\s]?(\d{6})[/.](\d{6})[/.](\d{4})")

def _texto_do_cache(d: dict) -> str:
    partes = [d.get("texto") or ""]
    for c in (d.get("conteudo_documentos") or []):
        if isinstance(c, dict):
            partes.append(str(c.get("conteudo") or ""))
    for rel in (d.get("cadeia") or []):
        partes.append(str(rel.get("texto") or ""))
    f = d.get("ficha") or {}
    partes.append(json.dumps(f, ensure_ascii=False))
    return "\n".join(partes)

def main():
    fila = json.loads(FILA.read_text())
    fila_sei = {x["sei"] for x in fila}
    mapa = {}
    novos = []  # processos-licitação a enfileirar
    for x in fila:
        ns = x["sei"]
        cf = CACHE / f"cdp_{re.sub(r'[^0-9A-Za-z]', '_', ns)}.json"
        if not cf.exists():
            continue
        try:
            d = json.loads(cf.read_text())
        except Exception:
            continue
        txt = _texto_do_cache(d)
        pregoes = sorted(set(RE_PREGAO.findall(txt)))
        editais = sorted(set(RE_EDITAL.findall(txt)))
        seis = {f"SEI-{a}/{b}/{c}" for a, b, c in RE_SEI.findall(txt)}
        # candidatos a processo de licitação = SEI citados da FAMÍLIA 270xxx (SEDEC/CBMERJ), não o próprio
        # contrato. Filtro de prefixo descarta ruído de outros órgãos (330/070/120…) que aparece na ficha.
        cand = sorted(s for s in seis if s != ns and s.startswith("SEI-270"))
        if pregoes or editais or cand:
            mapa[ns] = {"pregao": pregoes, "edital": editais, "sei_citados": cand,
                        "fornecedor": x.get("forn"), "valor": x.get("valor")}
        for s in cand:
            if s not in fila_sei:
                fila_sei.add(s)
                novos.append({"sei": s, "orig": s, "valor": x.get("valor") or 0,
                              "score": max(40, x.get("score", 0)),  # prioridade alta: é a licitação do contrato suspeito
                              "forn": x.get("forn"), "flags": ["LICITACAO_DE:" + ns], "tipo": "LICITACAO"})
    if novos:
        fila = novos + fila  # licitações no topo (já priorizadas)
        FILA.write_text(json.dumps(fila, ensure_ascii=False, indent=1))
    MAP.write_text(json.dumps(mapa, ensure_ascii=False, indent=1))
    npreg = sum(1 for v in mapa.values() if v["pregao"])
    print(f"[achar_edital] contratos com ref de licitação: {len(mapa)} (c/ pregão nº: {npreg}) | "
          f"novos processos-licitação enfileirados: {len(novos)} -> {MAP}")

if __name__ == "__main__":
    main()
