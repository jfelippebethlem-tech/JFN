#!/usr/bin/env python3
"""Runner E2E — direcionamento de editais municipais.

Pipeline: (opcional) extrai cláusulas de todo o corpus → constrói clusters →
peer-diff por cluster → enxame nas candidatas → PDF Kroll + XLSX + alertas +
casos no vault (veredito ≥ 8).

Uso: tools/editais_direcionamento.py [--clausulas] [--clusters] [--max-candidatas N]
                                     [--sem-pdf] [--limiar-raridade 0.7]
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from compliance_agent.editais import agrupar, clausulas, peer_diff  # noqa: E402
from compliance_agent.editais import db as ed  # noqa: E402
from compliance_agent.enxame import orquestrador  # noqa: E402
from compliance_agent.reporting.pericia_fisc import ctx_de_achados  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def extrair_todas_clausulas(con) -> int:
    rows = con.execute("select numero_controle_pncp, texto, valor_estimado "
                       "from edital_documento where documento_disponivel=1").fetchall()
    tot = 0
    for r in rows:
        cs = clausulas.extrair_clausulas(r["texto"], r["valor_estimado"])
        tot += clausulas.gravar(con, r["numero_controle_pncp"], cs)
    return tot


def _sinais_vencedor(con, numero_controle_pncp: str) -> tuple[str | None, list[str]]:
    """Vencedor via pcrj_contratos do mesmo controle; sinais reusando o que já temos."""
    row = con.execute(
        "select fornecedor_documento, fornecedor_nome from pcrj_contratos "
        "where numero_compra=? or numero_controle_pncp=? limit 1",
        (numero_controle_pncp, numero_controle_pncp)).fetchone()
    if not row or not row["fornecedor_documento"]:
        return None, []
    doc = row["fornecedor_documento"]
    sinais = []
    if con.execute("select 1 from sancoes_federais where cpf_cnpj=? limit 1", (doc,)).fetchone():
        sinais.append("favorecido sancionado (CEIS)")
    if con.execute("select 1 from emenda_favorecidos where documento_favorecido=? limit 1", (doc,)).fetchone():
        sinais.append("favorecido de emenda federal")
    if _tem_tabela(con, "rede_socios_fornecedores"):
        try:
            if con.execute("select 1 from rede_socios_fornecedores where raiz=? limit 1",
                           (doc[:8],)).fetchone():
                sinais.append("sócio liga ≥2 fornecedores (rede)")
        except Exception:
            pass   # coluna 'raiz' pode variar entre versões da rede — não derruba o dossiê
    return f"{row['fornecedor_nome']} ({doc})", sinais


def _tem_tabela(con, nome: str) -> bool:
    return bool(con.execute("select 1 from sqlite_master where type='table' and name=?", (nome,)).fetchone())


def avaliar_clusters(con, max_candidatas: int, limiar_raridade: float) -> list[dict]:
    clusters = con.execute("select id, assinatura_objeto, membros_json from edital_cluster "
                           "where avaliavel=1").fetchall()
    achados = []
    n = 0
    for cl in clusters:
        cands = peer_diff.candidatas(con, cl["id"], limiar_raridade=limiar_raridade)
        membros = json.loads(cl["membros_json"])
        for c in cands:
            if n >= max_candidatas:
                print(f"  [corte] {max_candidatas} candidatas avaliadas — resto no XLSX", flush=True)
                return achados
            irmaos = [con.execute("select objeto from edital_documento where numero_controle_pncp=?",
                                  (m,)).fetchone()["objeto"] or "" for m in membros
                      if m != c["numero_controle_pncp"]][:3]
            venc, sinais = _sinais_vencedor(con, c["numero_controle_pncp"])
            dossie = {"objeto": cl["assinatura_objeto"], "clausula": c,
                      "irmaos_sem_clausula": irmaos, "vencedor_doc": venc,
                      "sinais_beneficiario": sinais}
            r = orquestrador.avaliar(dossie)
            n += 1
            con.execute(
                """INSERT INTO clausula_veredito (clausula_id, cluster_id, numero_controle_pncp,
                     raridade, forca_e7, sumula, votos_json, score_final, veredito)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (c["clausula_id"], cl["id"], c["numero_controle_pncp"], c["raridade"],
                 c["forca_e7"], c["sumula"], json.dumps(r["votos"], ensure_ascii=False, default=str),
                 r["score_final"], r["veredito"]))
            con.commit()
            achados.append({
                "detector": f"edital_direcionamento_{c['forca_e7']}",
                "risco": r["score_final"], "veredito": r["veredito"],
                "titulo": f"Direcionamento ({c['subtipo']}) — {cl['assinatura_objeto'][:45]}",
                "descricao": (f"Indício de direcionamento: no grupo de {len(membros)} editais do mesmo "
                              f"objeto, o edital {c['numero_controle_pncp']} exige \"{c['texto'][:120]}\" "
                              f"que {int(c['raridade'] * 100)}% dos pares NÃO exigem ({c['sumula'] or 's/ súmula'}). "
                              f"Enxame {r['score_final']}/10 = {r['veredito']}. "
                              f"Vencedor: {venc or 'n/d'}; sinais: {', '.join(sinais) or 'nenhum'}. "
                              f"Indício ≠ acusação."),
                "evidencias": {"cluster": cl["id"], "raridade": c["raridade"],
                               "sumula": c["sumula"], "votos": r["votos"]},
                "codigo_emenda": None})
    return achados


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clausulas", action="store_true", help="(re)extrai cláusulas do corpus")
    ap.add_argument("--clusters", action="store_true", help="(re)constrói clusters (usa Cohere)")
    ap.add_argument("--max-candidatas", type=int, default=120)
    ap.add_argument("--limiar-raridade", type=float, default=0.7)
    ap.add_argument("--sem-pdf", action="store_true")
    args = ap.parse_args()

    con = ed.conectar()
    ed.init_schema(con)
    if args.clausulas:
        print(f"cláusulas extraídas: {extrair_todas_clausulas(con)}", flush=True)
    if args.clusters:
        print(f"clusters: {agrupar.construir_clusters(con)}", flush=True)

    achados = avaliar_clusters(con, args.max_candidatas, args.limiar_raridade)
    achados.sort(key=lambda a: -a["risco"])
    print(f"candidatas avaliadas: {len(achados)} | direcionamento (≥7): "
          f"{sum(1 for a in achados if a['risco'] >= 7)}", flush=True)

    hoje = datetime.now().date()
    fontes = [{"dado": "Editais (texto+itens)", "estado": "REAL", "fonte": "PNCP baixar_documentos",
               "data": hoje.isoformat()},
              {"dado": "Agrupamento por objeto", "estado": "REAL", "fonte": "Cohere embeddings",
               "data": hoje.isoformat()},
              {"dado": "Classificação de cláusula", "estado": "REAL",
               "fonte": "E7 + jurisprudência + enxame free-tier", "data": hoje.isoformat()}]
    resultado = {"achados": achados, "cobertura": {"edital_direcionamento": f"ok: {len(achados)}"}}
    ctx = ctx_de_achados("Direcionamento de Editais — Prefeitura do Rio",
                         "Comparação cláusula-a-cláusula entre editais de objeto semelhante · "
                         "peer-diff + enxame de 5 lentes", resultado, fontes)
    saidas = []
    try:
        import pandas as pd
        xlsx = REPO / "reports" / f"editais_direcionamento_{hoje}.xlsx"
        pd.DataFrame([{**a, "evidencias": json.dumps(a["evidencias"], ensure_ascii=False, default=str)}
                      for a in achados]).to_excel(xlsx, index=False)
        saidas.append(xlsx)
    except Exception as e:
        print(f"xlsx INDISPONÍVEL: {e}")

    if not args.sem_pdf and achados:
        from tools.vm_guard import cleanup_orphans, wait_until_safe
        cleanup_orphans()
        ok, msg = wait_until_safe()
        if ok:
            from compliance_agent.reporting.render_html import gerar_pdf
            pdf = await gerar_pdf(ctx, "editais_direcionamento")
            saidas.append(Path(pdf))
        else:
            print(f"vm_guard: {msg} — PDF adiado")

    # casos fortes → vault
    for a in achados:
        if a["risco"] >= 8:
            slug = f"edital-direcionamento-{a['evidencias']['cluster']}"
            nota = REPO.parent / "vault" / "casos" / f"{slug}.md"
            try:
                nota.write_text(
                    f"---\ntipo: caso\nprojeto: jfn\nseveridade: 🔴 {a['risco']}/10\nstatus: aberto\n"
                    f"fonte: enxame de editais (peer-diff + 5 lentes)\natualizado: {hoje}\n---\n\n"
                    f"# {a['titulo']}\n\n{a['descricao']}\n", encoding="utf-8")
            except Exception:
                pass

    for s in saidas:
        print("saída:", s)


if __name__ == "__main__":
    asyncio.run(main())
