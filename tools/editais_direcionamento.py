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
import sqlite3
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from compliance_agent.editais import agrupar, clausulas, peer_diff  # noqa: E402
from compliance_agent.editais import db as ed  # noqa: E402
from compliance_agent.enxame import orquestrador  # noqa: E402

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
            # a raiz (8 dígitos) do vencedor aparece em cnpjs_basicos de algum sócio que liga
            # ≥2 fornecedores → indício de grupo econômico oculto por trás do certame
            raiz = re.sub(r"\D", "", doc)[:8]
            if raiz and con.execute(
                    "select 1 from rede_socios_fornecedores "
                    "where n_fornecedores>=2 and cnpjs_basicos like ? limit 1",
                    (f"%{raiz}%",)).fetchone():
                sinais.append("sócio liga ≥2 fornecedores (rede)")
        except sqlite3.Error as e:
            print(f"  rede_socios indisponível p/ {doc[:8]}: {e}", file=sys.stderr)
    return f"{row['fornecedor_nome']} ({doc})", sinais


def _tem_tabela(con, nome: str) -> bool:
    return bool(con.execute("select 1 from sqlite_master where type='table' and name=?", (nome,)).fetchone())


def avaliar_clusters(con, max_candidatas: int, limiar_raridade: float,
                     raizes_cnpj: tuple[str, ...] | None = None) -> list[dict]:
    """Roda o enxame (5 lentes LLM free-tier) nas cláusulas RARAS (peer-diff) dos clusters avaliáveis.

    DEDUP (2026-07-20): pula cláusula que JÁ tem veredito — re-run não desperdiça chamada LLM nem
    duplica linha (antes o INSERT era cego). `raizes_cnpj` (ex.: ('42498600','42498733')) restringe
    às esferas fiscalizadas — acende o índice do RJ sem gastar LLM em edital federal fora da jurisdição."""
    clusters = con.execute("select id, assinatura_objeto, membros_json from edital_cluster "
                           "where avaliavel=1").fetchall()
    ja_avaliadas = {r[0] for r in con.execute("select distinct clausula_id from clausula_veredito "
                                              "where clausula_id is not null")}
    achados = []
    n = 0
    for cl in clusters:
        cands = peer_diff.candidatas(con, cl["id"], limiar_raridade=limiar_raridade)
        membros = json.loads(cl["membros_json"])
        for c in cands:
            if c["clausula_id"] in ja_avaliadas:
                continue  # dedup: já tem veredito — não re-bate o LLM
            if raizes_cnpj and (c["numero_controle_pncp"] or "")[:8] not in raizes_cnpj:
                continue  # fora da esfera-alvo — não gasta LLM
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
                     raridade, forca_e7, sumula, votos_json, score_final, veredito,
                     vencedor_doc, sinais_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (c["clausula_id"], cl["id"], c["numero_controle_pncp"], c["raridade"],
                 c["forca_e7"], c["sumula"], json.dumps(r["votos"], ensure_ascii=False, default=str),
                 r["score_final"], r["veredito"],
                 venc or None, json.dumps(sinais, ensure_ascii=False) if sinais else None))
            con.commit()
            achados.append({
                "detector": f"edital_direcionamento_{c['forca_e7']}",
                "risco": r["score_final"], "veredito": r["veredito"],
                "titulo": f"Direcionamento ({c['subtipo']}) — {cl['assinatura_objeto'][:45]}",
                "descricao": (f"Indício de direcionamento: no grupo de {len(membros)} editais do mesmo "
                              f"objeto, o edital {c['numero_controle_pncp']} exige \"{c['texto'][:120]}\" "
                              + (f"que {int(c['raridade'] * 100)}% dos pares NÃO exigem "
                                 if c["raridade"] is not None else
                                 "— grupo pequeno demais p/ comparação entre pares; indício pela força "
                                 "absoluta do catálogo E7 ")
                              + f"({c['sumula'] or 's/ súmula'}). "
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
    ap.add_argument("--so-rj", action="store_true",
                    help="restringe o enxame às esferas estadual-RJ + municipal-Rio (CNPJ-raiz "
                         "42498600/42498733) — acende o índice do RJ sem gastar LLM no federal")
    ap.add_argument("--sem-pdf", action="store_true")
    ap.add_argument("--so-relatorio", action="store_true",
                    help="só (re)gera o PDF/XLSX dos vereditos JÁ avaliados — não re-roda o enxame (sem custo LLM)")
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()

    con = ed.conectar()
    ed.init_schema(con)
    if args.so_relatorio:
        achados = []  # o montador lê direto de clausula_veredito; não precisa re-avaliar
        print("modo --so-relatorio: regenerando do que já está em clausula_veredito", flush=True)
    else:
        if args.clausulas:
            print(f"cláusulas extraídas: {extrair_todas_clausulas(con)}", flush=True)
        if args.clusters:
            print(f"clusters: {agrupar.construir_clusters(con)}", flush=True)
        raizes = ("42498600", "42498733") if args.so_rj else None
        achados = avaliar_clusters(con, args.max_candidatas, args.limiar_raridade, raizes_cnpj=raizes)
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
    # Montador JURÍDICO dedicado (ficha completa por achado, sem truncar) — lê os vereditos
    # persistidos em clausula_veredito e enriquece com órgão/processo/cláusula íntegra/súmulas.
    # (o ctx_de_achados genérico achatava tudo numa tabela título+descrição — ver relatorio_direcionamento.py)
    from compliance_agent.reporting.relatorio_direcionamento import montar_ctx as montar_ctx_dir
    ctx = montar_ctx_dir(con)
    ctx["proveniencia"] = fontes
    ctx["rotulo_score"] = "Gravidade do achado de maior escore"
    # XLSX de apoio: exporta a lista COMPLETA de vereditos do banco (não só os achados desta rodada),
    # para o anexo do PDF ter respaldo consultável — inclui os descartados e a cauda.
    saidas = []
    try:
        import pandas as pd
        rows_db = con.execute(
            "SELECT numero_controle_pncp, cluster_id, raridade, forca_e7, sumula, score_final, veredito, votos_json "
            "FROM clausula_veredito ORDER BY score_final DESC").fetchall()
        xlsx = REPO / "reports" / f"editais_direcionamento_{hoje}.xlsx"
        pd.DataFrame([dict(r) for r in rows_db]).to_excel(xlsx, index=False)
        saidas.append(xlsx)
    except Exception as e:
        print(f"xlsx INDISPONÍVEL: {e}")

    tem_vereditos = bool(con.execute("SELECT 1 FROM clausula_veredito LIMIT 1").fetchone())
    if not args.sem_pdf and tem_vereditos:
        from tools.vm_guard import cleanup_orphans, wait_until_safe
        cleanup_orphans()
        ok, msg = wait_until_safe()
        if ok:
            from compliance_agent.reporting.render_html import gerar_pdf
            pdf = await gerar_pdf(ctx, "editais_direcionamento")
            saidas.append(Path(pdf))
        else:
            print(f"vm_guard: {msg} — PDF adiado")

    if args.telegram and saidas:
        from compliance_agent.notifications.telegram import enviar_arquivo
        n_dir = ctx.get("_dados", {}).get("quentes", sum(1 for a in achados if a.get("risco", 0) >= 7))
        for s in saidas:
            await enviar_arquivo(str(s), caption=f"Fiscalização de direcionamento em editais — {hoje} "
                                                 f"({n_dir} achados de direcionamento; ficha jurídica por achado)")

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
            except OSError as e:
                print(f"  nota do vault {slug} não gravada: {e}", file=sys.stderr)

    for s in saidas:
        print("saída:", s)


if __name__ == "__main__":
    asyncio.run(main())
