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
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from compliance_agent.sei.cache_arquivo import glob_cache, ler_json

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
    # `glob_cache`/`ler_json`, NÃO `glob.glob` + `read_text`: 5.660 dos 6.195 blobs do acervo estão
    # comprimidos, e é justamente o cache que sabe o TAMANHO DA ÁRVORE. Com o glob cru, esta fila
    # — a que existe para achar captura truncada — enxergava 8,6% da evidência de truncamento.
    # Quarta ferramenta da casa cega à compressão; as três anteriores estão no catálogo.
    por_numero: dict[str, dict] = {}
    for f in glob_cache(CACHE, "cdp_*.json"):
        try:
            d = ler_json(f)
        except (OSError, ValueError):
            continue
        arv = len(d.get("documentos") or [])
        lido = len(d.get("conteudo_documentos") or [])
        if arv <= lido:
            continue
        numero = str(d.get("numero") or Path(f).name.replace(".zst", "").replace(".json", "")[4:])
        # O MESMO PROCESSO PODE TER DOIS BLOBS — `cdp_270003_001598_2024` e
        # `cdp_SEI_270003_001598_2024` coexistem no acervo, de duas convenções de nome. Sem
        # deduplicar, o processo entra duas vezes e consome DOIS dos poucos slots da recaptura
        # para o mesmo trabalho. Fica o blob que leu MENOS: é o que mais precisa voltar, e reler
        # cobre o outro de qualquer forma.
        chave = re.sub(r"\D", "", numero)
        atual = por_numero.get(chave)
        if atual is None or lido < atual["lido"]:
            por_numero[chave] = {"numero": numero, "arvore": arv, "lido": lido,
                                 "faltam": arv - lido}
    saida.extend(por_numero.values())
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
        # O ZERO ERA IGNORÂNCIA DECLARADA, e deixou de ser preciso. Até 2026-08-07 o arquivo
        # sozinho não sabia o tamanho da árvore — quem sabia era o cache —, então o teto de coleta
        # entrava com `faltam: 0` e a incerteza ficava marcada em `faltam_desconhecido`. O zero
        # servia à ordenação (teto primeiro), mas era um marcador, não uma medida.
        #
        # Agora o manifesto traz `docs_na_arvore` e o gate devolve `faltam_capturar`. Usar o número
        # real muda o que a recaptura FAZ com os poucos slots que tem: com o zero, esta fila
        # ordenava por empate e o primeiro da vez podia ser um processo a 5 documentos do fim ou
        # um a 667 — indiferentemente. Medido hoje: o topo da fila trazia 39/55 e 40/45 marcados
        # como "faltam 0", enquanto processos quase completos esperavam atrás.
        teto = bool(ev.get("teto_de_coleta"))
        faltam_reais = ev.get("faltam_capturar")
        if isinstance(faltam_reais, int) and faltam_reais > 0:
            faltam, incerto = faltam_reais, False
        else:
            faltam = 0 if teto else max(0, n_docs - int(ev.get("n_com_texto") or 0))
            # ARQUIVO VAZIO tem tamanho DESCONHECIDO, não zero. `n_docs == 0` produzia
            # `faltam = 0 - 0 = 0`, literalmente verdadeiro e completamente inútil: 26 pastas sem
            # um único documento encabeçavam a fila como se fossem quase-completas. Não se sabe se
            # ali há 3 documentos ou 900 — e o slot da recaptura é de dois processos a cada três
            # horas, então essa diferença decide a passada.
            incerto = teto or n_docs == 0
        arvore = ev.get("docs_na_arvore") or n_docs
        saida.append({"numero": numero, "arvore": arvore, "lido": n_docs,
                      "faltam": faltam,
                      "faltam_desconhecido": incerto,
                      "origem": "arquivo_nao_integro"})
    # A fila da OUTRA máquina entra aqui, e só o que esta não tem — o que ela já conhece vale
    # mais, porque veio da medição do próprio acervo.
    ja_todos = {re.sub(r"\D", "", str(x["numero"])) for x in saida}
    for x in _compartilhada():
        if re.sub(r"\D", "", x["numero"]) not in ja_todos:
            saida.append(x)

    return ordenar(saida)


# Buraco que ainda cabe num slot de leitura. O gigante de 956 documentos estourou o slot e não
# entregou nada (medido em 07/08), então nada acima disto fura fila por mais alto que seja o score.
_TETO_SLOT = 40
_SCORE_QUASE = 60.0


def _quase_veredito() -> dict[str, float]:
    """Processos SEM veredito cujo score já é alto — ler mais alguns documentos DECIDE o caso.

    Medido em 2026-08-09: 33 processos estão em `NAO_AVALIAVEL` só por captura incompleta e já
    pontuam ≥60 com o pouco lido (um chega a 90,2). Eles não precisam de mais fila: precisam de
    mais LEITURA. Degrada em silêncio — sem a tabela, devolve vazio e a ordem volta a ser a antiga.
    """
    import sqlite3

    try:
        from compliance_agent.reporting.intel_base import _DB
    except ImportError:
        return {}
    try:
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        return {re.sub(r"\D", "", str(n)): float(s) for n, s in con.execute(
            "SELECT numero_sei, score100 FROM processo_avaliacao "
            "WHERE faixa='NAO_AVALIAVEL' AND score100 >= ?", (_SCORE_QUASE,))}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def ordenar(fila_bruta: list[dict]) -> list[dict]:
    """ORDEM: quem está a poucos documentos de um VEREDITO alto primeiro; depois buraco medido,
    do menor para o maior; tamanho desconhecido por último.

    `faltam=0` com tamanho desconhecido não é "quase pronto" — é ignorância, e tratá-la como zero
    põe na frente justamente o que pode ser um gigante de 900 documentos, que estoura o slot e não
    entrega nada. Com o buraco medido, cada slot drena os quase completos, que é onde ele rende.

    A camada de cima (2026-08-09) é a única exceção, e é conservadora: só fura fila quem já tem
    score alto SEM veredito **e** cujo buraco cabe num slot. Antes disso, um processo a UM
    documento de fechar 80/100 esperava na posição 314 de 3.625, e a maioria dos 33 casos entre
    1.575 e 2.729 — meses de espera por leitura quase pronta.
    """
    quase = _quase_veredito()

    def _chave(x: dict) -> tuple:
        desconhecido = bool(x.get("faltam_desconhecido"))
        faltam = x.get("faltam") or 0
        perto = (not desconhecido and 0 < faltam <= _TETO_SLOT
                 and re.sub(r"\D", "", str(x.get("numero"))) in quase)
        return (0 if perto else 1, desconhecido, faltam)

    return sorted(fila_bruta, key=_chave)


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
    """Aceita os DOIS formatos de registro: o desta ferramenta (`lido_antes`/`lido_depois`) e o
    do `run_recaptura` do sei_sweep (`antes`/`depois`) — são dois armazéns de progresso, e a
    doutrina tem de valer nos dois. Até 2026-08-08 ela só valia aqui, no caminho que NINGUÉM
    agenda: o cron roda `run_recaptura`, que filtrava `not in feitos` sem expiração — toda
    releitura sem ganho (browser instável, doc restrito hoje) virava exclusão perpétua."""
    antes = int(reg.get("lido_antes", reg.get("antes")) or 0)
    depois = int(reg.get("lido_depois", reg.get("depois")) or 0)
    if depois > antes:
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
    # `ler_json`, NÃO `read_text` cru: ~91% dos blobs estão em `.json.zst`. Com o caminho cru,
    # blob comprimido lia como 0 → `_marcar(antes, 0)` gravava "sem ganho" FALSO e o processo
    # expirava da fila apesar do ganho real. Quinta ferramenta da casa cega à compressão.
    d = ler_json(CACHE / f"cdp_{_tag(numero)}.json")
    if not isinstance(d, dict):
        return 0
    return len(d.get("conteudo_documentos") or [])


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

# ── FILA COMPARTILHADA ENTRE AS DUAS MÁQUINAS (2026-08-07) ────────────────────────────────────
# A fatia (`JFN_SWEEP_FATIA`) divide o trabalho quando as duas máquinas VEEM o mesmo universo. Aqui
# elas não veem: esta fila nasce do acervo LOCAL, e o acervo de cada máquina é o que ela mesma
# capturou. Medido hoje: fila da VM-1 com 1.515 processos, da VM-2 com 96, e **apenas 45 em comum**
# — aplicar a fatia sem mais nada só faria cada uma trabalhar menos, sem que a segunda ajudasse no
# atraso da primeira.
#
# A recaptura não precisa do arquivo local para funcionar: ela precisa do NÚMERO do processo, e lê
# tudo do SEI. Então basta a fila atravessar. A VM-1 grava o arquivo abaixo e o empurra junto da
# colheita (`tools/colher_vm2.sh`, que já tem o canal aberto); a VM-2 o encontra e o soma ao que
# tem. Com a união nas duas pontas, a fatia passa a dividir de verdade — e as duas somadas dobram
# a vazão sem coordenação nenhuma, que é o único jeito que funciona em duas máquinas separadas.
COMPARTILHADA = RAIZ / "data" / "fila_recaptura_compartilhada.json"


def _compartilhada() -> list[dict]:
    """A fila que a outra máquina exportou. Ausente ou ilegível ⇒ lista vazia, nunca erro."""
    if not COMPARTILHADA.exists():
        return []
    try:
        d = json.loads(COMPARTILHADA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    itens = d.get("itens") if isinstance(d, dict) else d
    fora = []
    for x in itens or []:
        if not isinstance(x, dict) or not x.get("numero"):
            continue
        fora.append({"numero": str(x["numero"]),
                     "arvore": int(x.get("arvore") or 0), "lido": int(x.get("lido") or 0),
                     "faltam": int(x.get("faltam") or 0),
                     "faltam_desconhecido": bool(x.get("faltam_desconhecido")),
                     "origem": "fila_da_outra_maquina"})
    return fora


def exportar_compartilhada(destino: Path | None = None) -> dict:
    """Grava a fila desta máquina para a outra consumir. Só os campos que atravessam."""
    itens = [{"numero": x["numero"], "arvore": x.get("arvore"), "lido": x.get("lido"),
              "faltam": x.get("faltam"), "faltam_desconhecido": x.get("faltam_desconhecido")}
             for x in fila()]
    alvo = Path(destino or COMPARTILHADA)
    alvo.write_text(json.dumps({"gerado_em": time.strftime("%Y-%m-%d %H:%M"), "itens": itens},
                               ensure_ascii=False), encoding="utf-8")
    return {"itens": len(itens), "arquivo": str(alvo)}

