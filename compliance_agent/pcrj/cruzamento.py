# -*- coding: utf-8 -*-
"""Cruzamento Câmara Municipal × Prefeitura do Rio — por NOME (sem CPF).

Fluxo direcional (a Prefeitura não tem lista em massa; a Câmara sim):
    para cada servidor da Câmara → consulta o nome na Prefeitura (várias competências)
    → filtra linhas com NOME NORMALIZADO idêntico → registra como INDÍCIO de duplo vínculo.

Honestidade (regra dura do projeto): sem CPF, nome idêntico é INDÍCIO, nunca prova.
Níveis de confiança:
    - ``nao_encontrado``      : nenhum servidor PCRJ com o nome → só Câmara.
    - ``indicio_nome_unico``  : exatamente 1 matrícula PCRJ com o nome → duplo vínculo provável
                                (ainda assim homônimo é possível — exige verificação).
    - ``homonimo_ambiguo``    : >1 matrícula PCRJ com o mesmo nome → não dá para isolar a pessoa.
    - ``indisponivel``        : erro de consulta (≠ 'não encontrado').

Duplo vínculo entre Câmara (Legislativo) e Prefeitura (Executivo), se confirmado por CPF,
pode caracterizar acumulação vedada (CF art. 37, XVI/XVII) — o relatório trata como
indício a verificar, jamais como acusação.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj.nomes import normalizar
from compliance_agent.pcrj.pcrj_remuneracao import Sessao, competencia_mais_recente

# Competências históricas (a Prefeitura publica 2021→2026). Snapshots-chave capturam
# as janelas administrativas sem consultar os 72 meses (o servidor limita rajada):
# 06/2024 = pico da gestão anterior; 06/2021 = início da janela. A competência mais
# recente (gestão atual) é somada em ``cruzar`` via ``incluir_recente``.
COMPETENCIAS_HISTORICO = [(6, 2024), (6, 2021)]


def _pessoas_camara(con, gabinete: int | None, limite: int | None) -> list[dict]:
    q = ("SELECT nome_norm, MIN(nome) nome, "
         "GROUP_CONCAT(DISTINCT gabinete_num) gabs, "
         "GROUP_CONCAT(DISTINCT cargo) cargos "
         "FROM pcrj_camara_servidores WHERE nome_norm<>'' ")
    args: list = []
    if gabinete is not None:
        q += "AND gabinete_num=? "
        args.append(gabinete)
    q += "GROUP BY nome_norm ORDER BY nome_norm"
    if limite:
        q += f" LIMIT {int(limite)}"
    return [dict(r) for r in con.execute(q, args)]


def _consultar_pessoa(pessoa: dict, competencias: list[tuple[int, int]],
                      sess: Sessao) -> dict:
    """Consulta uma pessoa da Câmara em todas as competências; agrega matches PCRJ."""
    alvo = pessoa["nome_norm"]
    por_matricula: dict[str, dict] = {}
    houve_erro = False
    for mes, ano in competencias:
        linhas = sess.consultar_nome(pessoa["nome"], mes, ano)
        if linhas is None:
            houve_erro = True
            continue
        for row in linhas:
            if normalizar(row.get("nome", "")) != alvo:
                continue                     # substring trouxe outro nome — descarta
            mat = row.get("matricula") or "?"
            # mantém a competência mais recente por matrícula (maior valor de contexto)
            por_matricula.setdefault(mat, row)
    return {"pessoa": pessoa, "matches": por_matricula, "erro": houve_erro}


def _classificar(res: dict) -> str:
    if res["matches"]:
        return "indicio_nome_unico" if len(res["matches"]) == 1 else "homonimo_ambiguo"
    return "indisponivel" if res["erro"] else "nao_encontrado"


def cruzar(competencias: list[tuple[int, int]] | None = None, gabinete: int | None = None,
           limite: int | None = None, workers: int = 3, db_path=None,
           incluir_recente: bool = True, pausa: float = 0.4) -> dict:
    """Executa o cruzamento e grava consultas + vínculos. Retorna resumo com contagens."""
    if competencias is None:
        competencias = list(COMPETENCIAS_HISTORICO)
        if incluir_recente:
            competencias = [competencia_mais_recente()] + competencias
    _db.inicializar(db_path)
    con = _db.conectar(db_path)
    pessoas = _pessoas_camara(con, gabinete, limite)
    agora = datetime.now(timezone.utc).isoformat()

    sessoes = [Sessao(pausa=pausa) for _ in range(workers)]

    def tarefa(i_pessoa):
        i, pessoa = i_pessoa
        return _consultar_pessoa(pessoa, competencias, sessoes[i % workers])

    contagem = {"nao_encontrado": 0, "indicio_nome_unico": 0,
                "homonimo_ambiguo": 0, "indisponivel": 0}
    feitos = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
          for res in ex.map(tarefa, enumerate(pessoas)):   # persiste incremental (VM/bg-safe)
            conf = _classificar(res)
            contagem[conf] += 1
            p = res["pessoa"]
            gabs = p.get("gabs") or ""
            # busca o(s) vereador(es) do(s) gabinete(s) da pessoa
            vereadores = []
            for gnum in [g for g in (gabs.split(",") if gabs else []) if g]:
                vr = con.execute("SELECT vereador FROM pcrj_gabinetes WHERE gabinete_num=?",
                                 (int(float(gnum)),)).fetchone()
                if vr:
                    vereadores.append(vr["vereador"])
            for mat, row in (res["matches"] or {"": None}).items():
                con.execute(
                    """INSERT OR REPLACE INTO pcrj_prefeitura_consulta
                       (nome_norm,encontrado,nome_pcrj,orgao,cargo,vinculo,remuneracao,
                        confianca,bruto,consultado_em) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (p["nome_norm"], 1 if row else 0, row.get("nome") if row else None,
                     row.get("lotacao") if row else None, row.get("cargo") if row else None,
                     None, row.get("valor_liquido") if row else None, conf,
                     json.dumps(row, ensure_ascii=False) if row else None, agora))
                if row:                       # só grava vínculo quando há match de nome
                    con.execute(
                        """INSERT OR REPLACE INTO pcrj_vinculo_cruzado
                           (nome_norm,nome_camara,gabinetes,cargos_camara,nome_pcrj,
                            orgao_pcrj,cargo_pcrj,confianca,observacao,gerado_em)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (p["nome_norm"], p["nome"],
                         "; ".join(f"Gab {g} ({v})" for g, v in zip(
                             [x for x in (gabs.split(',') if gabs else []) if x], vereadores))
                         or gabs, p.get("cargos"), row.get("nome"), row.get("lotacao"),
                         row.get("cargo"),
                         conf, f"admissao={row.get('admissao')} exoneracao={row.get('exoneracao')} "
                               f"matricula={mat} valor_liq={row.get('valor_liquido')}", agora))
            feitos += 1
            if feitos % 50 == 0:
                con.commit()
                print(f"  ...{feitos}/{len(pessoas)} consultados", flush=True)
        # Reconciliação (runs suplementares): quem tem match em QUALQUER competência não pode
        # seguir também como 'nao_encontrado'/'indisponivel' de outro run (dupla contagem).
        con.execute("""DELETE FROM pcrj_prefeitura_consulta
                       WHERE encontrado=0 AND nome_norm IN
                         (SELECT DISTINCT nome_norm FROM pcrj_prefeitura_consulta WHERE encontrado=1)""")
        con.commit()
    finally:
        con.close()
    resumo = {"pessoas_consultadas": len(pessoas), "competencias": competencias,
              "gabinete": gabinete, **contagem}
    return resumo


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Cruzamento Câmara×Prefeitura RJ por nome")
    ap.add_argument("--gabinete", type=int, default=None)
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    print(f"Iniciando cruzamento (gab={args.gabinete}, limite={args.limite})", flush=True)
    resumo = cruzar(gabinete=args.gabinete, limite=args.limite, workers=args.workers)
    print(f"\nRESUMO FINAL: {resumo}", flush=True)


if __name__ == "__main__":
    main()
