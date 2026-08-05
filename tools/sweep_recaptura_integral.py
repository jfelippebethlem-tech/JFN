# -*- coding: utf-8 -*-
"""Recaptura os documentos que o teto de leitura deixou para trás — sem limite de páginas.

O QUE ESTE ARQUIVO CONSERTA, e é grande. O leitor do SEI lê no máximo `SEI_MAX_DOCS` documentos
por processo (**40** por padrão, `tools/sei_reader.py`), escolhidos por valor fiscalizatório
(`ordenar_para_leitura`). O teto é honesto quanto ao tempo de browser numa VM de 2 vCPU, mas
ninguém media o que ele custava. Medido em 2026-08-03 sobre os 314 processos com cache:

    documentos na ÁRVORE: 19.583 · com TEXTO lido: 9.136 · **NÃO LIDOS: 10.447**
    155 processos com documento não lido — o pior tem 956 na árvore e 40 lidos

O cache guarda a árvore inteira (título + URL de cada documento), então sabemos exatamente
QUAIS faltam; o que falta é o texto, e isso só o browser traz.

O QUE A MEDIÇÃO MOSTROU, e muda o desenho (2026-08-03, três tentativas registradas):

  · atacar o pior processo primeiro (956 docs) → estourou 600 s, browser morto
    (`TargetClosedError`), **+0 documentos**;
  · atacar os de lacuna mínima (1 documento) com 170 s → também **+0**;
  · medir o caso MÍNIMO com orçamento real: processo de **5 documentos**, teto 120 →
    **556 segundos** e 4 com texto (o 5º não veio nem assim: não é teto, é documento sem texto
    extraível ou restrito).

Ou seja: **o custo é do login + carga da árvore, não do teto de documentos.** Nove minutos por
processo, e a sessão do SEI é única por IP. Reler os 155 processos um a um, cada um pagando o
login inteiro, custaria ~23 h de browser disputando a mesma sessão do sweep que já roda 24/7.

Por isso este arquivo é a FILA e a MEDIDA, não o executor de volume: quem tem de subir o teto é o
`sweep_sei`, que já faz login UMA vez e processa vários processos na mesma sessão. Aqui ficam a
conta honesta do que falta, o alvo por processo e o modo pontual (`--max 1`) para quando se quer
um processo específico agora.

Disciplina de VM (regra absoluta — a VM já caiu 4×): cede a vez ao sweep SEI (1 sessão SEI por
IP, e o `sei_reader` já serializa por `browser_lock`), respeita load alto, `nice`/`ionice`, teto
de tempo por processo e por slot. O cron repete; nada se perde entre as passadas.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import asyncio
import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

ARQUIVO = Path(__file__).resolve().parents[1] / "data" / "sei_arquivo"
CACHE = RAIZ / "data" / "sei_cache"
PROGRESSO = RAIZ / "data" / "recaptura_integral_progresso.json"


def _tag(nome: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "_", nome or "")


def fila() -> list[dict]:
    """Processos cujo cache prova que há documento na árvore sem texto lido, os piores primeiro.

    A ordem é do MENOR para o MAIOR buraco, e isso foi medido, não escolhido por gosto: a
    primeira tentativa atacou o pior processo (956 documentos na árvore, 916 sem texto), estourou
    600 s com o browser morto (`TargetClosedError`) e trouxe **+0**. Numa VM de 2 vCPU o gigante
    não cabe num slot, e enquanto ele falha nenhum outro anda. Menor primeiro drena dezenas de
    processos por slot; os gigantes vão pelo caminho resiliente (`tools/sei_processo_integral.py`,
    que lê em lotes com checkpoint e relança o browser), via `--gigantes`.
    """
    saida = []
    for f in glob.glob(str(CACHE / "cdp_*.json")):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        arv = len(d.get("documentos") or [])
        lido = len(d.get("conteudo_documentos") or [])
        if arv > lido:
            saida.append({"numero": d.get("numero") or Path(f).stem[4:],
                          "arvore": arv, "lido": lido, "faltam": arv - lido})
    # O ARQUIVO TAMBÉM É FONTE DE PENDÊNCIA, e não era consultado. Esta fila só olhava o CACHE
    # (`cdp_*.json`), então um processo cujo arquivo ficou truncado mas cujo cache foi podado, ou
    # nunca existiu, não tinha rota nenhuma de volta. Medido em 2026-08-05, depois que
    # `manifesto_norm.captura_integra` passou a reconhecer o teto de coleta de 40 documentos:
    # dos **176 arquivos parados exatamente em 40**, 137 voltam pela fila do `sweep_sei` (estão no
    # universo de OB do SIAFE) e 57 por esta fila (o cache sabe que a árvore é maior) — união de
    # 150. Os outros **26 eram órfãos**: nenhuma fila os oferecia, e ficariam truncados para
    # sempre enquanto o motor os tratava como não-avaliáveis.
    #
    # A régua é a MESMA do motor e do `sei_sweep._arquivo_incompleto`, de propósito: o que a
    # avaliação recusa por captura insuficiente é, por definição, o que a leitura precisa refazer.
    ja = {re.sub(r"\D", "", str(x["numero"])) for x in saida}
    from compliance_agent.sei import manifesto_norm as _mn
    for pasta in sorted(ARQUIVO.glob("*")):
        mf = pasta / "manifest.json"
        if not pasta.is_dir() or not mf.exists():
            continue
        try:
            man = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        numero = str(man.get("processo") or pasta.name)
        if re.sub(r"\D", "", numero) in ja:
            continue
        ok, ev = _mn.captura_integra(man, pasta)
        if ok:
            continue
        n_docs = int(ev.get("n_docs") or 0)
        # `faltam` = 0 no teto de coleta NÃO significa "nada falta" — significa que o arquivo
        # sozinho não sabe o tamanho da árvore (quem sabe é o cache, e estes não o têm). O zero
        # serve à ordenação (teto primeiro, que é o que se quer), mas mentiria no total impresso:
        # o SEI-270131/000548/2023 marcava 40/40 e faltavam 25. Por isso a incerteza é declarada.
        teto = bool(ev.get("teto_de_coleta"))
        saida.append({"numero": numero, "arvore": n_docs, "lido": n_docs,
                      "faltam": 0 if teto else max(0, n_docs - int(ev.get("n_com_texto") or 0)),
                      "faltam_desconhecido": teto,
                      "origem": "arquivo_nao_integro"})
    saida.sort(key=lambda x: x["faltam"])
    return saida


def _feitos() -> dict:
    if PROGRESSO.exists():
        try:
            return json.loads(PROGRESSO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


# DESISTIR NÃO PODE SER PARA SEMPRE — a mesma doutrina que o `sei_sweep` já aplica às tentativas
# do sweep principal (lá a tentativa expira em 14 dias). Aqui não expirava: bastava UMA passada sem
# ganho para o processo sair da fila em definitivo. Medido em 2026-08-05, o registro tinha 5
# entradas e **4 com `lido_antes == lido_depois`** — nenhum ganho, e três delas paradas em 40/40,
# ou seja, exatamente os casos de teto de coleta que mais precisam voltar. As tentativas com +0
# são conhecidas e documentadas neste arquivo (browser morto, login que não venceu o WAF, processo
# gigante que estoura o slot): marcar fracasso como "feito" transforma condição transitória em
# exclusão permanente.
_DIAS_NOVA_CHANCE = 7


def _sem_ganho_expirou(reg: dict) -> bool:
    if int(reg.get("lido_depois") or 0) > int(reg.get("lido_antes") or 0):
        return False                       # ganhou: não precisa voltar
    em = str(reg.get("em") or "")
    if not em:
        return True                        # registro antigo, sem data: dá nova chance
    try:
        quando = datetime.fromisoformat(em)
    except ValueError:
        return True
    return (datetime.now() - quando).days >= _DIAS_NOVA_CHANCE


def _marcar(numero: str, antes: int, depois: int) -> None:
    d = _feitos()
    d[numero] = {"lido_antes": antes, "lido_depois": depois,
                 "em": datetime.now().isoformat(timespec="seconds")}
    PROGRESSO.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _lido_agora(numero: str) -> int:
    f = CACHE / f"cdp_{_tag(numero)}.json"
    if not f.exists():
        return 0
    try:
        return len(json.loads(f.read_text(encoding="utf-8")).get("conteudo_documentos") or [])
    except (OSError, ValueError):
        return 0


def reler(numero: str, teto: int, timeout_s: int) -> int:
    """Relê o processo com o teto levantado. Devolve quantos documentos ficaram com texto."""
    from tools import sei_reader as SR
    os.environ["SEI_MAX_DOCS"] = str(teto)
    try:
        asyncio.run(asyncio.wait_for(SR.ler(numero, usar_cache=False), timeout=timeout_s))
    except (TimeoutError, asyncio.TimeoutError):
        print(f"  ! {numero}: estourou {timeout_s}s — o que leu até aqui fica no cache",
              file=sys.stderr)
    except Exception as e:  # noqa: BLE001 — fronteira de browser: um processo ruim não para o lote
        print(f"  ! {numero}: {str(e)[:140]}", file=sys.stderr)
    return _lido_agora(numero)


def arquivar(numero: str) -> None:
    """Materializa no arquivo compacto pelo caminho canônico da casa (nunca reimplementar)."""
    subprocess.run([str(RAIZ / ".venv/bin/python"), "-m", "tools.sei_arquivar_do_cache",
                    "--aplicar", "--max", "1", "--so", numero],
                   cwd=str(RAIZ), timeout=600, check=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--teto", type=int, default=int(os.environ.get("SEI_RECAP_MAX", "400")),
                    help="documentos por processo (0 = sem teto)")
    ap.add_argument("--segundos", type=int, default=1800, help="teto de tempo do slot")
    ap.add_argument("--por-processo", type=int, default=900, help="teto de tempo por processo")
    ap.add_argument("--max", type=int, default=0, help="máx. de processos no slot (0 = pelo tempo)")
    ap.add_argument("--listar", action="store_true", help="só mostra a fila e sai")
    ap.add_argument("--ate", type=int, default=0,
                    help="só processos com lacuna <= N (0 = todos). O gigante não cabe num slot")
    # ALVO NOMEADO. A fila é ordenada por lacuna crescente e `--max` corta do começo, então não
    # havia como pedir UM processo específico. Precisei disto em 2026-08-05 para o
    # SEI-270131/000548/2023, que é o nº 1 da fila do fiscal (7 achados, entre eles o I3 crítico
    # do ato do ordenador sem assinatura de quem decide) e está truncado: árvore de 65, 40 lidos.
    # Recapturar o processo mais importante da fila não deveria depender de ele ser o menor.
    ap.add_argument("--processo", default="", help="recaptura SÓ este processo (número SEI)")
    ap.add_argument("--gigantes", action="store_true",
                    help="inverte a ordem: ataca os maiores pelo caminho resiliente em lotes")
    a = ap.parse_args()

    f = fila()
    if a.processo:
        alvo = re.sub(r"\D", "", a.processo)
        f = [x for x in f if re.sub(r"\D", "", str(x["numero"])) == alvo]
        if not f:
            print(f"[recap] {a.processo} não está na fila (captura já íntegra ou sem pendência).")
            return 0
    if a.ate:
        f = [x for x in f if x["faltam"] <= a.ate]
    if a.gigantes:
        f = list(reversed(f))
    total = sum(x["faltam"] for x in f)
    incerto = sum(1 for x in f if x.get("faltam_desconhecido"))
    print(f"fila: {len(f)} processos · {total} documentos sem texto lido"
          + (f" · {incerto} com lacuna DESCONHECIDA (teto de coleta: o arquivo parou em 40 e só a "
             f"árvore dirá quantos faltam)" if incerto else ""))
    if a.listar:
        for x in f[:25]:
            print(f"  faltam {x['faltam']:4d} de {x['arvore']:4d} (lidos {x['lido']:3d})  "
                  f"{x['numero']}")
        return 0

    feitos = _feitos()
    t0 = time.time()
    n = 0
    for x in f:
        if (time.time() - t0) > a.segundos or (a.max and n >= a.max):
            break
        reg = feitos.get(x["numero"])
        if reg and not _sem_ganho_expirou(reg):
            continue
        restante = int(a.segundos - (time.time() - t0))
        antes = x["lido"]
        depois = reler(x["numero"], a.teto, min(a.por_processo, max(120, restante)))
        if depois > antes:
            arquivar(x["numero"])
        _marcar(x["numero"], antes, depois)
        n += 1
        print(f"  {x['numero']}: {antes} → {depois} documentos com texto "
              f"(+{max(0, depois - antes)})", flush=True)
    print(f"slot encerrado: {n} processo(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
