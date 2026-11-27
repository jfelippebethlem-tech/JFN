"""Backfill da folha do Executivo do RJ (GESPERJ, API pública /remuneracao) desde 2020 — dono 27/11/2026: «faz isso
desde 2020». Roda no it-campo (disco folgado; não pesa o compliance.db da VM-1): um arquivo compacto por competência,
<dir>/gesperj_<AAAA-MM>.jsonl.gz, com nome, máscara do CPF no formato da casa (XX + posições 4–9 + XXX), órgão,
cargo, vínculo, bruta, líquido e matrícula.

CONFIABILIDADE (regra do dono: nenhuma margem de erro):
  • competência só conta como COMPLETA com TODOS os cargos paginados até o fim, sem página com erro e sem bater no
    teto de janela da API; aí, e só aí, grava ok_<AAAA-MM> com as contagens. Incompleta = refeita do zero na
    próxima chamada (o arquivo parcial nunca é lido: o casador exige o marcador).
  • a contagem gravada é conferida contra o totalElements da API para a competência (diferença vai no marcador).
Reusa as funções do coletor da casa (`folha_estado._get/_cargos/_cpf_middle6`): mesma consulta, mesma máscara.
Uso: python -m tools.folha_estado_historico <dir> [--de 2020-01] [--ate AAAA-MM (padrão: mês passado)] [--max 6] [--paralelo 3]
No fluxo: rotina diária no it-campo; cada execução faz no máximo --max competências pendentes (retoma pelos marcadores)."""
from __future__ import annotations

import argparse
import gzip
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from compliance_agent.collectors import folha_estado as F

PAUSA = 0.35


def meses(de: str, ate: str) -> list[str]:
    a, m = int(de[:4]), int(de[5:7])
    out = []
    while f"{a:04d}-{m:02d}" <= ate:
        out.append(f"{a:04d}-{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return out


def competencia(d: Path, comp: str) -> dict:
    marca = d / f"ok_{comp}"
    if marca.exists():
        return json.loads(marca.read_text())
    ano, mes = int(comp[:4]), int(comp[5:7])
    arq = d / f"gesperj_{comp}.jsonl.gz"
    tot = {"competencia": comp, "linhas": 0, "paginas": 0, "erros": 0, "teto": 0}
    with httpx.Client(timeout=40) as c, gzip.open(arq, "wt", encoding="utf-8") as out:
        api = (F._get(c, {"page": 0, "size": 10, "ano": ano, "mes": mes}) or {}).get("totalElements")
        cargos = F._cargos(c)
        if not cargos or not api:
            return {**tot, "erro": "API sem cargos ou sem total para a competência"}
        for cargo in cargos:
            pagina = 0
            while True:
                j = F._get(c, {"page": pagina, "size": F._SIZE, "ano": ano, "mes": mes, "codCargo": cargo})
                if j is None:
                    tot["erros"] += 1
                    break
                for r in j.get("remuneracoes") or []:
                    if not r.get("nomeServidor"):
                        continue
                    out.write(json.dumps({"nome": r["nomeServidor"], "cpf": F._cpf_middle6(r.get("cpf") or ""),
                                          "orgao": r.get("orgao") or "", "cargo": r.get("funcaoCargo") or "",
                                          "vinculo": (r.get("vinculo") or "")[:50],
                                          "bruta": float(r.get("totalVantagens") or 0),
                                          "liquido": float(r.get("valorLiquido") or 0),
                                          "matricula": (r.get("matriculaServidor") or "").strip()}, ensure_ascii=False) + "\n")
                    tot["linhas"] += 1
                tot["paginas"] += 1
                pagina += 1
                if pagina >= (j.get("totalPages") or 0):
                    break
                if pagina >= F._PAGINA_MAX:
                    tot["teto"] += 1
                    break
                time.sleep(PAUSA)
    tot["total_api"] = api
    tot["diferenca_api"] = api - tot["linhas"]
    if tot["erros"] or tot["teto"]:
        tot["erro"] = "incompleta: página com erro ou teto de janela — será refeita"
        return tot
    if abs(tot["diferenca_api"]) > 0.005 * api:          # a partição por cargo perdeu linhas: não é completa
        tot["erro"] = f"incompleta: {tot['linhas']} linhas contra {api} da API — será refeita"
        return tot
    marca.write_text(json.dumps(tot))
    return tot


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", type=Path)
    ap.add_argument("--de", default="2020-01")
    from datetime import date
    h = date.today()
    passado = f"{h.year - 1:04d}-12" if h.month == 1 else f"{h.year:04d}-{h.month - 1:02d}"
    ap.add_argument("--ate", default=passado)
    ap.add_argument("--max", type=int, default=6)
    ap.add_argument("--paralelo", type=int, default=3)
    a = ap.parse_args(argv)
    a.dir.mkdir(parents=True, exist_ok=True)
    # instância única (27/11: após o reboot da VM-1, a cópia remota sobreviveu à queda do ssh e o motor disparou outra —
    # duas gravando os mesmos arquivos de mês). Outra em curso ⇒ não toca em nada e o job volta depois.
    import fcntl
    trava = open(a.dir / ".lock", "w")  # noqa: SIM115 — vive até o fim do processo
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("folha_estado_historico: OUTRA EXECUÇÃO EM CURSO — nada feito")
        return 1
    todas = meses(a.de, a.ate)
    pendentes = [c for c in todas if not (a.dir / f"ok_{c}").exists()][:a.max]
    with ThreadPoolExecutor(a.paralelo) as ex:
        res = list(ex.map(lambda c: competencia(a.dir, c), pendentes))
    ok = [r for r in res if "erro" not in r]
    feitas = sum(1 for c in todas if (a.dir / f"ok_{c}").exists())
    estado = "ok" if len(ok) == len(res) else "INCOMPLETO"
    print(f"folha_estado_historico: {estado} — nesta execução {len(ok)}/{len(res)} completas, {sum(r['linhas'] for r in ok)} linhas; "
          f"histórico {feitas}/{len(todas)} competências; incompletas={[r['competencia'] for r in res if 'erro' in r]}")
    with open(a.dir / "resumo.json", "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return 0 if len(ok) == len(res) else 1           # incompleta = efeito falha, o job volta e refaz


if __name__ == "__main__":
    raise SystemExit(main())
