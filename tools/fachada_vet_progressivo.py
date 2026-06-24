#!/usr/bin/env python3
"""Vetagem progressiva dos candidatos a reabertura de fachada (anti falso-positivo do VLM).

Para cada candidato (visual_classe não-comercial em verificacao_sede do work.db), cruza MÚLTIPLAS
fontes externas — todas via a própria engine da casa (API JFN em 127.0.0.1:8000, que agrega
Receita/QSA, CEIS/CNEP, OpenSanctions) + semântica do endereço — e decide:

  FALSO_POSITIVO  → empresa legítima (ativa, CNAE/endereço comercial, antiga, sem sanção): o VLM errou
  REABRIR_FORTE   → visual não-comercial + sinais de fachada (inativa/baixada, sócio único, sanção,
                    complemento residencial CASA/APTO/FUNDOS) + valor relevante
  REVISAR         → ambíguo, precisa de olho humano

Honestidade: REABRIR_FORTE é INDÍCIO, não acusação. Lê o work.db (read-only); NÃO escreve no DB vivo.
Saída: JSON + markdown ranqueado por valor.
"""
import json, sqlite3, sys, time, urllib.request, urllib.parse
from pathlib import Path

WORK = "/home/ubuntu/JFN/data/backups/compliance.work.db"
API = "http://127.0.0.1:8000"
OUT = Path("/home/ubuntu/JFN/reports/fachada_vetagem_2026-06-24")
NAO_COMERCIAL = ("casa_residencial","predio_residencial","terreno_baldio",
                 "area_aberta_rural","construcao_precaria_barraco","indeterminado")
COMERCIAL_HINT = ("LOJA","SALA","ANDAR","CONJ","CJ","SOBRELOJA","GALPAO","GALPÃO","PAVIMENTO","TORRE","BLOCO COMERCIAL","ED ","EDIFICIO","SHOPPING")
RESID_HINT = ("CASA","APTO","APARTAMENTO","FUNDOS","QUADRA","LOTE","CHACARA","SITIO","FAZENDA")

def _get(path):
    try:
        with urllib.request.urlopen(API+path, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"_erro": str(e)[:80]}

def empresa(cnpj):
    d = _get(f"/api/empresa?cnpj={cnpj}")
    return d.get("dados", d) if isinstance(d, dict) else {}

def idoneidade(cnpj):
    d = _get(f"/api/idoneidade?cnpj={urllib.parse.quote(cnpj)}")
    n = 0
    for res in (d.get("resultados") or []):
        dd = res.get("dados") or {}
        n += int(dd.get("n") or 0)
        if dd.get("sancionado"): n += 1
    return n

def vet(row):
    cnpj = row["cnpj"]; cad = empresa(cnpj); sanc = idoneidade(cnpj)
    end = (row["endereco"] or "").upper(); compl = (cad.get("complemento") or "").upper()
    situ = (cad.get("situacao") or "").upper()
    socios = cad.get("socios") or []
    abertura = cad.get("abertura") or ""
    cnae = (cad.get("cnae") or "")
    txt = end + " " + compl
    comercial_addr = any(h in txt for h in COMERCIAL_HINT)
    resid_addr = any(h in txt for h in RESID_HINT)
    ativa = situ == "ATIVA"
    antiga = abertura and abertura < "2015"
    # decisão
    sinais = []
    if not ativa: sinais.append(f"situação={situ or '?'}")
    if sanc: sinais.append(f"{sanc} sanção(ões) CEIS/CNEP/OpenSanctions")
    if len(socios) == 1: sinais.append("sócio único")
    if resid_addr: sinais.append("complemento residencial")
    pro_ok = []
    if ativa: pro_ok.append("ATIVA")
    if comercial_addr: pro_ok.append("endereço comercial (loja/sala/andar)")
    if antiga: pro_ok.append(f"aberta {abertura[:4]}")
    if "Construç" in cnae or "Comércio" in cnae or "Serviç" in cnae: pro_ok.append(f"CNAE {cnae[:30]}")

    if comercial_addr and ativa and not sanc:
        verdito = "FALSO_POSITIVO"      # VLM errou; é comercial de verdade
    elif (not ativa or sanc or (len(socios)==1 and resid_addr)):
        verdito = "REABRIR_FORTE"
    else:
        verdito = "REVISAR"
    return {
        "cnpj": cnpj, "razao": row["razao"], "total_recebido": row["total_recebido"],
        "visual_classe": row["visual_classe"], "visual_conf": row["visual_conf"],
        "endereco": row["endereco"], "complemento": compl, "situacao": situ,
        "cnae": cnae, "abertura": abertura, "n_socios": len(socios), "n_sancoes": sanc,
        "verdito": verdito, "sinais_fachada": sinais, "sinais_legitimidade": pro_ok,
    }

def main():
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    con = sqlite3.connect(f"file:{WORK}?mode=ro", uri=True); con.row_factory = sqlite3.Row
    # Seleção INDEPENDENTE da imagem (Mapillary é lixo/desligado): pega os "ok" residenciais
    # de maior valor e deixa o cruzamento cadastro/QSA/sanções decidir. visual_classe entra
    # só como informação auxiliar, nunca como gatilho.
    rows = con.execute(
        "SELECT cnpj,razao,total_recebido,visual_classe,visual_conf,endereco "
        "FROM verificacao_sede WHERE status='REVERIFICAR' "
        "ORDER BY total_recebido DESC LIMIT ?", (limite,)).fetchall()
    con.close()
    print(f"[vet] {len(rows)} candidatos (top {limite} por valor) — cruzando cadastro+sanções…", flush=True)
    res = []
    for i, r in enumerate(rows, 1):
        v = vet(r); res.append(v)
        if i % 10 == 0: print(f"  ...{i}/{len(rows)}", flush=True)
        time.sleep(0.2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
    # markdown ranqueado
    by = {"REABRIR_FORTE": [], "REVISAR": [], "FALSO_POSITIVO": []}
    for v in res: by[v["verdito"]].append(v)
    L = [f"# Vetagem progressiva de fachadas — {len(res)} candidatos (2026-06-24)\n",
         f"Fontes cruzadas por caso: VLM (Street View) + Receita/QSA + CEIS/CNEP + OpenSanctions + semântica de endereço.",
         f"**Indício ≠ acusação.**\n",
         f"- 🔴 REABRIR_FORTE: {len(by['REABRIR_FORTE'])}",
         f"- 🟡 REVISAR: {len(by['REVISAR'])}",
         f"- 🟢 FALSO_POSITIVO (VLM errou): {len(by['FALSO_POSITIVO'])}\n"]
    for k, ic in (("REABRIR_FORTE","🔴"),("REVISAR","🟡"),("FALSO_POSITIVO","🟢")):
        L.append(f"\n## {ic} {k}\n")
        L.append("| R$ recebido | Razão | Visual | Situação | Sinais |\n|---:|---|---|---|---|")
        for v in sorted(by[k], key=lambda x: -x["total_recebido"]):
            s = "; ".join(v["sinais_fachada"] if k!="FALSO_POSITIVO" else v["sinais_legitimidade"])
            L.append(f"| {v['total_recebido']:,.2f} | {v['razao'][:38]} | {v['visual_classe']} {v['visual_conf'] or ''} | {v['situacao']} | {s[:70]} |")
    OUT.with_suffix(".md").write_text("\n".join(L))
    print(f"[vet] CONCLUÍDO. {len(by['REABRIR_FORTE'])} reabrir-forte / {len(by['REVISAR'])} revisar / {len(by['FALSO_POSITIVO'])} falso-positivo")
    print(f"[vet] relatório: {OUT}.md / .json")

if __name__ == "__main__":
    main()
