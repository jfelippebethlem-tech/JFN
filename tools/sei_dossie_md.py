#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera o dossiê .md de um processo SEI, fracionando só quando ele não cabe no modelo.

    .venv/bin/python tools/sei_dossie_md.py 030001_004946_2026 [--vault] [--plano]
    .venv/bin/python tools/sei_dossie_md.py --maiores 5 --plano

`--plano` mostra a decisão de leitura e NÃO chama IA — use sempre antes de gastar chamada num
processo grande. `--vault` grava também no segundo cérebro (`~/vault/processos/`), que é onde o
conhecimento fica pesquisável entre sessões.

Escolha de modelo: perfil `documento` do catálogo vivo (`openrouter_catalogo`), que exige um
piso de capacidade — ler peça processual com modelo pequeno produz leitura errada com aparência
de leitura certa. Se o catálogo estiver fora do ar, cai para `best_free_chat`, e o dossiê
registra no cabeçalho qual modelo de fato respondeu.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

ACERVO = pathlib.Path(os.environ.get("JFN_SEI_ARQUIVO", "data/sei_arquivo"))
SAIDA = pathlib.Path("output/dossies")
VAULT = pathlib.Path(os.path.expanduser("~/vault/processos"))
# Retomada de dossiê interrompido por cota — ver o bloco de checkpoint em gerar().
CHECKPOINTS = pathlib.Path("data/dossie_checkpoints")


def _contexto_do_modelo(model_id: str, padrao: int = 128_000) -> int:
    from compliance_agent.llm.openrouter_catalogo import catalogo
    for m in catalogo():
        if m["id"] == model_id:
            return int(m.get("ctx") or padrao)
    return padrao


class EstouroDeContexto(RuntimeError):
    """O lote não cabe na janela — com a contagem REAL informada pelo provedor.

    Estimar token por caractere não funciona (razão medida de 1,50 a 3,8 conforme o documento).
    Em vez de calibrar uma constante que vai errar no próximo tipo de peça, o planejamento
    reage ao número verdadeiro: divide o lote pelo fator `limite/usado`, com margem.
    """

    def __init__(self, limite: int, usado: int):
        super().__init__(f"lote usou {usado:,} tokens; a janela é {limite:,}".replace(",", "."))
        self.limite, self.usado = limite, usado

    @property
    def fator(self) -> float:
        """Quanto o lote precisa encolher, com 15% de margem para a variação entre lotes."""
        return (self.limite / self.usado) * 0.85


def _post(model_id: str, sistema: str, prompt: str, timeout_s: int = 300,
          max_tokens: int = 4000) -> str:
    import httpx
    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={"model": model_id,
              "messages": [{"role": "system", "content": sistema},
                           {"role": "user", "content": prompt}],
              "max_tokens": max_tokens, "temperature": 0.1},
        timeout=timeout_s)
    r.raise_for_status()
    # HTTP 200 pode trazer corpo de ERRO (upstream do OpenRouter). Ver
    # `conteudo_da_resposta` — parse cru aqui estourava KeyError e escapava do tratamento.
    from compliance_agent.llm.free_llm import conteudo_da_resposta
    return conteudo_da_resposta(r.json()).strip()


def _chamar(model_id: str, sistema: str, prompt: str, *, max_tokens: int = 4000) -> str:
    """Uma etapa do dossiê, encarando o limite de cota do jeito que ele aparece de verdade.

    Modelo `:free` NÃO cai de uma vez: ele estoura cota no meio da tarefa, tipicamente com 429
    depois de algumas chamadas seguidas. Num processo de 16 lotes isso é quase certo. Três
    defesas, nesta ordem:

      1. **esperar** — 429 é condição do momento; recuar e repetir resolve a maioria;
      2. **trocar de modelo** — insistindo, passa para o próximo id vivo do catálogo, porque a
         cota é POR MODELO e o vizinho costuma estar livre;
      3. **cair para a cadeia** — Cerebras/Gemini/Groq etc., que têm cota independente.

    Vazio só depois de tudo isso — e aí quem chama registra a lacuna no dossiê em vez de fingir
    que o lote foi lido.
    """
    import httpx

    from compliance_agent.llm.openrouter_catalogo import escolher

    tentar = [m for m in (model_id, escolher("smart"), escolher("fast")) if m]
    tentar = list(dict.fromkeys(tentar))
    for i, mid in enumerate(tentar):
        for espera in (0, 20, 60):
            if espera:
                print(f"    429 em {mid} — aguardando {espera}s (cota é por modelo)")
                time.sleep(espera)
            try:
                return _post(mid, sistema, prompt, max_tokens=max_tokens)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    continue
                corpo = (e.response.text or "")[:300]
                from compliance_agent.llm.free_llm import estouro_de_contexto
                estouro = estouro_de_contexto(corpo)
                if estouro:
                    # Sobe para quem planeja: a contagem VERDADEIRA do tokenizador permite
                    # refazer o corte, e é melhor que qualquer estimativa por caractere.
                    raise EstouroDeContexto(*estouro) from e
                print(f"    {mid} respondeu {e.response.status_code}: {corpo[:150]} — próximo")
                break
            except Exception as e:  # noqa: BLE001
                print(f"    {mid} falhou ({type(e).__name__}) — próximo")
                break
        if i + 1 < len(tentar):
            print(f"    trocando de modelo: {tentar[i + 1]}")

    try:
        from compliance_agent.llm.free_llm import best_free_chat
        print("    caindo para a cadeia grátis (cota independente do OpenRouter)")
        return best_free_chat(prompt, system=sistema, smart=True, fallback="")
    except Exception as e:  # noqa: BLE001
        print(f"    cadeia grátis indisponível ({type(e).__name__})")
        return ""


def assinatura_do_plano(plano) -> str:
    """Identidade do plano de leitura — o que torna um lote comparável entre execuções.

    O checkpoint era indexado só pelo NÚMERO do lote, e isso não identifica conteúdo: trocar o
    modelo muda o contexto, refaz o plano, e o mesmo processo passa de 16 lotes para 4. Os
    índices 1..4 continuavam existindo e a retomada colava extrações do plano ANTIGO num plano
    NOVO — dossiê afirmando cobrir 291 documentos com a leitura de ~57, sem um aviso.
    """
    import hashlib
    bruto = f"{len(plano.lotes)}|{plano.n_docs}|{plano.orcamento}|" + ",".join(
        f"{lote.indice}:{len(lote.docs)}:{lote.tokens}" for lote in plano.lotes)
    return hashlib.sha256(bruto.encode()).hexdigest()[:16]


def ler_checkpoint(caminho: pathlib.Path, plano) -> dict[int, str]:
    """Lotes já feitos PARA ESTE PLANO. Plano diferente devolve vazio, e é o ponto do conserto."""
    assinatura = assinatura_do_plano(plano)
    feitos: dict[int, str] = {}
    try:
        linhas = pathlib.Path(caminho).read_text().splitlines()
    except OSError:
        return {}
    for linha in linhas:
        try:
            d = json.loads(linha)
            if d.get("plano") != assinatura:     # inclui o formato antigo, que não tem a chave
                continue
            feitos[int(d["lote"])] = d["texto"]
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            continue
    return feitos


def gravar_lote(caminho: pathlib.Path, plano, indice: int, texto: str) -> None:
    caminho = pathlib.Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a") as fh:
        fh.write(json.dumps({"plano": assinatura_do_plano(plano), "lote": indice,
                             "texto": texto}, ensure_ascii=False) + "\n")


_SECOES = ("Objeto e enquadramento", "Partes e responsáveis", "Linha do tempo", "Valores",
           "Indícios a verificar", "Contradições entre documentos", "Lacunas")


def _consolidacao_utilizavel(texto: str) -> bool:
    """A consolidação vale se traz as seções pedidas e não é monólogo do modelo.

    Exigir 5 das 7 (e não as 7) porque o modelo às vezes funde duas seções legitimamente. O que
    NÃO se aceita é o texto que apenas ECOA a lista de seções dentro do raciocínio — daí a
    checagem de monólogo junto, e não em vez.
    """
    if not (texto or "").strip():
        return False
    from tools.bench_modelos import penalidade_formato
    presentes = sum(1 for sec in _SECOES if sec.lower() in texto.lower())
    return presentes >= 5 and penalidade_formato(texto) < 24


def _mapear_subdividido(modelo: str, lote, fator: float, prompt_map) -> str:
    """Reprocessa um lote que estourou, dividindo seus DOCUMENTOS em partes menores.

    Divide por documento, como o planejamento original — o corte por caractere continua sendo o
    último recurso, porque é ele que destrói a citação.
    """
    from compliance_agent.sei.dossie_fracionado import Lote

    partes = max(2, round(1 / max(0.05, fator)))
    docs = lote.docs
    tamanho = max(1, len(docs) // partes)
    saidas = []
    for n, i in enumerate(range(0, len(docs), tamanho), 1):
        sub = Lote(indice=lote.indice, docs=docs[i:i + tamanho])
        sistema, prompt = prompt_map(sub)
        try:
            texto = _chamar(modelo, sistema, prompt)
        except EstouroDeContexto as e:
            print(f"      parte {n} ainda estourou — dividindo de novo")
            texto = _mapear_subdividido(modelo, sub, e.fator, prompt_map)
        if texto:
            saidas.append(f"_(parte {n} do lote {lote.indice})_\n\n{texto}")
    return "\n\n".join(saidas)


def gerar(nome_pasta: str, *, so_plano: bool = False, vault: bool = False) -> pathlib.Path | None:
    from compliance_agent.sei.dossie_fracionado import (
        cabecalho_md, planejar, prompt_map, prompt_reduce,
    )
    from compliance_agent.llm.openrouter_catalogo import escolher

    pasta = ACERVO / nome_pasta
    if not pasta.is_dir():
        print(f"processo não encontrado no acervo: {pasta}")
        return None

    modelo = escolher("documento") or ""
    ctx = _contexto_do_modelo(modelo) if modelo else 128_000
    plano = planejar(nome_pasta, pasta, contexto_modelo=ctx)

    print(f"{nome_pasta}: {plano.n_docs} doc(s) com texto · {plano.tokens_total:,} tokens est. "
          f"· modelo {modelo or '(cadeia grátis)'} ctx={ctx:,}".replace(",", "."))
    print(f"  → {'cabe inteiro' if plano.cabe_inteiro else f'fracionado em {len(plano.lotes)} lote(s)'}"
          f" · orçamento por lote {plano.orcamento:,} tokens".replace(",", "."))
    if plano.docs_vazios:
        print(f"  ⚠️  {plano.docs_vazios} documento(s) sem texto — não serão lidos")
    if so_plano:
        return None

    # CHECKPOINT POR LOTE. Um processo de 16 lotes leva quase meia hora, e a cota de modelo
    # grátis estoura no meio com frequência. Sem isto, um 429 no 12º lote joga fora os onze
    # anteriores — e a próxima execução paga tudo de novo. Cada lote é gravado assim que
    # responde; relançar o comando retoma de onde parou.
    ckpt = CHECKPOINTS / f"{nome_pasta}.jsonl"
    feitos = ler_checkpoint(ckpt, plano)
    if feitos:
        print(f"  retomando: {len(feitos)} de {len(plano.lotes)} lote(s) já no checkpoint")
    elif ckpt.exists():
        print("  checkpoint existe mas é de outro plano de leitura (o modelo mudou) — "
              "relendo do zero, para não misturar lotes de planos diferentes")

    blocos: list[str] = []
    for lote in plano.lotes:
        if lote.indice in feitos:
            blocos.append(feitos[lote.indice])
            continue
        sistema, prompt = prompt_map(lote)
        t0 = time.monotonic()
        try:
            saida = _chamar(modelo, sistema, prompt)
        except EstouroDeContexto as e:
            # Não é falha: é a medição certa chegando tarde. Refaz o corte com ela.
            print(f"    lote {lote.indice} estourou ({e}) — subdividindo em "
                  f"{max(2, round(1 / e.fator))} parte(s) com a contagem real")
            saida = _mapear_subdividido(modelo, lote, e.fator, prompt_map)
        print(f"  lote {lote.indice}/{len(plano.lotes)}: {len(lote.docs)} doc(s) · "
              f"{lote.tokens:,} tk · {time.monotonic() - t0:.0f}s · "
              f"{'ok' if saida else 'SEM RESPOSTA'}".replace(",", "."))
        if saida:
            gravar_lote(ckpt, plano, lote.indice, saida)
        blocos.append(saida or f"_(lote {lote.indice} não pôde ser lido — nenhum provedor "
                               "respondeu; os documentos deste lote NÃO entraram no dossiê. "
                               "Relançar o comando retoma só os lotes que faltam.)_")

    if len(blocos) == 1:
        corpo = blocos[0]
    else:
        sistema, prompt = prompt_reduce(nome_pasta, blocos)
        corpo = _chamar(modelo, sistema, prompt, max_tokens=12_000)
        # DEFESA EM PROFUNDIDADE. Medido em 2026-07-28: o modelo consolidou 16 lotes devolvendo
        # o próprio raciocínio em inglês, truncado no meio de uma frase, sem nenhuma das sete
        # seções — enquanto os blocos do `map` traziam 232 citações [doc ...] e valores reais.
        # Consolidação ruim não pode apagar extração boa: sem as seções, entrega-se o material
        # bruto, que é útil, em vez do monólogo, que não é.
        if not _consolidacao_utilizavel(corpo):
            print("  ⚠️ consolidação inutilizável (monólogo ou sem as seções) — entregando as "
                  "extrações por lote, que preservam as citações")
            corpo = ("> ⚠️ A consolidação automática não produziu as seções esperadas. Abaixo, as "
                     "extrações por lote, com as citações preservadas.\n\n"
                     + "\n\n".join(f"## Extração do lote {i}\n\n{b}"
                                   for i, b in enumerate(blocos, 1)))

    md = cabecalho_md(plano, modelo or "cadeia grátis") + "\n" + corpo + "\n"
    # `garantir_neutro` VALIDA e levanta; não devolve texto. Atribuir o retorno dele a `md`
    # apagava o dossiê inteiro (None) depois de meia hora de chamadas — erro cometido aqui em
    # 2026-07-28. O gate avisa e o trabalho segue: perder o dossiê por causa de um termo
    # interno seria pior que entregá-lo com o aviso.
    try:
        from compliance_agent.reporting.neutralidade import termos_proibidos
        internos = termos_proibidos(md)
        if internos:
            print(f"  ⚠️ gate de neutralidade acusou termo interno: {internos} — revisar antes "
                  "de encaminhar")
    except Exception as e:  # noqa: BLE001
        print(f"  gate de neutralidade não rodou ({type(e).__name__})")

    SAIDA.mkdir(parents=True, exist_ok=True)
    destino = SAIDA / f"{nome_pasta}.md"
    destino.write_text(md)
    print(f"  gravado: {destino}")
    if vault:
        VAULT.mkdir(parents=True, exist_ok=True)
        (VAULT / f"{nome_pasta}.md").write_text(md)
        print(f"  segundo cérebro: {VAULT / f'{nome_pasta}.md'}")
    return destino


def _maiores(n: int) -> list[str]:
    tam = []
    for p in ACERVO.iterdir():
        td = p / "texto"
        if td.is_dir():
            b = sum(f.stat().st_size for f in td.glob("*.txt"))
            if b:
                tam.append((b, p.name))
    return [nome for _, nome in sorted(tam, reverse=True)[:n]]


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("processo", nargs="*")
    ap.add_argument("--maiores", type=int, help="usa os N maiores processos do acervo")
    ap.add_argument("--plano", action="store_true", help="só decide a leitura; não chama IA")
    ap.add_argument("--vault", action="store_true", help="grava também em ~/vault/processos/")
    a = ap.parse_args()

    alvos = list(a.processo) + (_maiores(a.maiores) if a.maiores else [])
    if not alvos:
        ap.error("informe ao menos um processo ou --maiores N")
    for nome in alvos:
        gerar(nome, so_plano=a.plano, vault=a.vault)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
