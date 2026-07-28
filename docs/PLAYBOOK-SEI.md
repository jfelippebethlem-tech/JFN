# PLAYBOOK SEI — caminho ÚNICO (não reinvente)

> Para QUALQUER modelo/agente. Barato primeiro: o arquivo em disco responde
> 90% das perguntas sem browser, sem SEI, sem IA. Custo sobe a cada passo.

## 0. O processo já está arquivado? (grátis — comece SEMPRE aqui)
```bash
.venv/bin/python tools/sei_consultar.py --listar
.venv/bin/python tools/sei_consultar.py "330020/000762/2021"        # resumo+fases+lacunas
.venv/bin/python tools/sei_consultar.py PROC --fase execucao        # medições/atestos
.venv/bin/python tools/sei_consultar.py PROC --tipo nota_fiscal
.venv/bin/python tools/sei_consultar.py PROC --grep "reajuste"
.venv/bin/python tools/sei_consultar.py PROC --fotos                # fotos de medição (JPEG)
.venv/bin/python tools/sei_consultar.py PROC --doc 12               # texto integral do doc
```
Arquivo em `data/sei_arquivo/<TAG>/` (txt + fotos + manifest). 10-20× menor que o PDF.

## 1. Não está arquivado → baixar a ÍNTEGRA (browser, ~min; SEMPRE background)
```bash
SEI_SEM_TG=1 .venv/bin/python tools/sei_integra_completa.py "PROC"   # sem spam no Telegram
.venv/bin/python tools/sei_integra_completa.py "PROC"                # com envio ao Telegram
```
Grava `data/sei_cache/integra_<TAG>/NNN.pdf` + `manifest.json` (títulos da árvore).

## 2. Converter para o arquivo compacto (CPU local, sem browser)
```bash
.venv/bin/python tools/sei_arquivar.py "PROC"          # txt + fotos + fases + lacunas
.venv/bin/python tools/sei_arquivar.py --pendentes     # tudo que falta (o sweep já faz)
```

## 3. Leitura pontual sem íntegra (browser)  ⭐ REESCRITO 2026-07-10
`sei_reader.ler("SEI-XX:")` — login itkava/ITERJ + abre + extrai a árvore COMPLETA e o texto.
Sessão: `tools/sei_session.py`.

### Como a árvore do SEI funciona (a raiz de anos de "só 5 docs")
A árvore (`ifrArvore`) é **paginada em PASTAS por faixa de data** e **lazy-load**: só a última
pasta auto-abre — por isso `ler()` via só ~5 de N docs. As pastas carregam por um **POST
`procedimento_paginar`** (form `hdnArvore`/`hdnPastaAtual`/`hdnProtocolos`); GET/goto voltam 200+0 bytes.
O DOM é virtualizado (renderiza ~10 nós de 73) e `Nos[]`/`Pastas[]` NÃO são globais p/ `evaluate`.

### A solução (já no código, herdada por ler()/ler_com_cadeia/sweep, SEM mudar caller)
`tools/sei_reader.py`:
- **`abrir_processo(pg, proc)`** — abre com retry (o 1º submit às vezes é comido), detecta a árvore por
  CONTEÚDO (`infraArvoreNo` no HTML do frame), não por nome. Retorna o frame ou None.
- **`arvore_do_fonte(pg)`** — AUTORIDADE da árvore. Chama **`_expandir_pastas_e_ler`**, que aciona o
  **loader NATIVO do SEI no browser** (`abrirFecharPasta(id)` p/ cada pasta), espera os "Aguarde..."
  sumirem e lê as âncoras `a[id_documento]` já materializadas. 100% na sessão itkava, sem forjar request.
- **`_parse_nos_arvore(html)`** — tokenizador ciente de strings p/ `new infraArvoreNo(...)` (fallback).
- **`_conteudo_doc`** — corpo do doc: drilla no IFRAME interno (descarta a casca do menu "AGENERSA…");
  PDF/scan → `_url_conteudo_doc` (arvore_visualizar→documento_visualizar) + OCR.
- Relacionados agora excluem a fila do menu (`procedimento_controlar`) → só processos REAIS.
- **0 docs SEM árvore aberta = leitura FALHA (caiu na caixa da unidade), não processo vazio** —
  `ler_processo` marca `indisponivel` (sinal `arvore_vista`; a heurística antiga `rel>=15` morreu
  junto com o lixo do menu que ela media — fix 2026-07-10). Consumidor honesto NÃO cacheia esse 0.
**PROVADO 2026-07-10:** túnel `SEI-460001/000779/2023` = **5 → 658 documentos** (árvore inteira,
contrato 033/2023 + 1º Termo Aditivo de valor/RERRA + aditivo de prazo + todas as medições).

### Íntegra / envio (já sobre o primitivo)
`tools/sei_integra_completa.py "PROC"` (PDF único → Telegram; `SEI_SEM_TG=1` só arquiva) ·
`tools/sei_proc_paginado.py "PROC" "kw"` (lista + OCR dos alvos) ·
`tools/sei_docs_to_telegram.py "PROC" "kw"` — TODOS enumeram via `abrir_processo`+`arvore_do_fonte`.
As antigas `docs_da_pagina`/`clicar_proxima` (paginação de BUSCA) estão **aposentadas** (davam 0 na árvore).

## 4. LER o processo com IA (quando o texto não basta)  ⭐ NOVO 2026-07-28
```bash
.venv/bin/python tools/sei_dossie_md.py PROC --plano        # decide a leitura, SEM gastar IA
.venv/bin/python tools/sei_dossie_md.py PROC --vault        # gera o dossiê e grava no vault
```
**Sempre `--plano` antes** num processo grande: ele diz se cabe inteiro ou em quantos lotes.
Medido no acervo: mediana 6.295 tokens (97% cabem inteiros), mas a cauda vai a 1,85 milhão em
291 documentos. O fracionamento é por DOCUMENTO, nunca por caractere — cortar por caractere
destrói a citação, e achado sem citação não vale em peça.

- **Checkpoint por lote** (`data/dossie_checkpoints/`): cota de modelo grátis estoura NO MEIO;
  relançar o comando retoma. O checkpoint é ligado à ASSINATURA DO PLANO — trocar de modelo
  refaz o plano e o checkpoint antigo é descartado com aviso (misturar lotes de planos
  diferentes já produziu um dossiê que dizia cobrir 291 documentos com a leitura de 57).
- **A IA lê, o CÓDIGO arruma.** A consolidação em seções é determinística
  (`sei/dossie_fracionado.consolidar`). Duas tentativas de consolidar por LLM falharam: os
  modelos devolveram o próprio raciocínio, truncado.
- **Estouro de contexto se resolve com a contagem VERDADEIRA** que o provedor devolve no erro,
  não com constante de chars/token (a razão medida varia de 1,5 a 3,8 conforme o documento).

## 5. Indícios e análise em série  ⭐ NOVO 2026-07-28
```bash
.venv/bin/python tools/sei_analise_em_serie.py --fila            # ordem por valor pago (OB)
.venv/bin/python tools/sei_analise_em_serie.py --n 10            # analisa e grava no vault
.venv/bin/python tools/sei_analise_em_serie.py --fila-captura    # pagos e SEM texto
.venv/bin/python tools/sei_analise_em_serie.py --fila-recaptura  # lidos pela METADE
.venv/bin/python tools/sei_analise_em_serie.py --fila-pais       # processo-pai não capturado
```
As três filas respondem perguntas diferentes e não se substituem:

| fila | o que é | por que importa |
|---|---|---|
| `--fila-captura` | pago e sem uma linha lida | 27 processos, R$ 25,9 mi |
| `--fila-recaptura` | ≥30% dos documentos cegos | 129 processos, 4.568 documentos |
| `--fila-pais` | processo de contratação ausente | destrava os responsáveis dos filhos |

**Processo lido pela metade é PIOR que não lido: parece analisado.** Um processo saiu com
"0 indícios" e era o primeiro da fila de recaptura, 100% cego.

## Responsáveis: quem responde pelo processo  ⭐ NOVO 2026-07-28
```bash
curl "http://127.0.0.1:8000/api/responsaveis?processo=SEI-030001/004724/2026"
.venv/bin/python tools/sei_agentes_sweep.py            # materializa agente_processo
```
Ausência de responsável identificado **NÃO** é ausência de responsável designado: em 97% dos
processos o ato de designação não integra o processo de pagamento — ele vive no processo de
CONTRATAÇÃO (daí a `--fila-pais`). Confundir as duas coisas é acusação falsa de violação do
art. 117.

## Requisição formal (o que a lista não abre, o ofício abre)
```bash
.venv/bin/python tools/gerar_requisicoes.py --resumo   # a conta, por órgão
.venv/bin/python tools/gerar_requisicoes.py            # emite as minutas
```
71 órgãos · 77 processos com acesso restrito. A peça PEDE, não acusa — e pede também o
**fundamento legal da restrição**, porque restringir acesso é ato administrativo e ato
administrativo se motiva.

## Fases da contratação = CÓDIGO, não memória
`compliance_agent/sei/fases.py` (testes: `tests/test_sei_fases.py`):
planejamento → selecao → contratacao → execucao → despesa (+controle/tramitacao).
`classificar(titulo)`, `linha_do_tempo(titulos)`, `lacunas(fases, modalidade)`.
Lacuna CRÍTICA clássica: **pagamento sem evidência de execução** (OB/NF sem
medição/atesto/relatório fotográfico). Fotos de medição são PROVA — o arquivador
as preserva em `fotos/` justamente para conferir se o serviço foi feito.

## NUNCA
- ❌ Culpar acesso/WAF: o login SEMPRE funciona (cron prova). Falha = seu método.
- ❌ Browser em foreground ou 2 browsers: use background + `tools/vm_guard.py`.
- ❌ Reinventar parsing/leitura de PDF: `sei_consultar.py` já entrega texto.
- ❌ Carregar PDF/íntegra inteira no contexto: use `--grep`/`--fase`/`--doc`.
- ❌ Rodar OCR fora do `sei_arquivar.py` (ele já decide quando OCR é preciso).
- ❌ **Re-extrair documento com `chars=0`**: não há de onde. O arquivo de ORIGEM não é guardado
  (o acervo tem só `texto/` e `fotos/`; há UM pdf em 2.055 processos). Eles precisam de
  RECAPTURA no SEI — ver `--fila-recaptura`.
- ❌ **Ler "0 indícios" como processo limpo** sem olhar a cobertura do dossiê.
- ❌ Fixar id de modelo `:free` em código: eles são aposentados o tempo todo e apodrecem
  calados. O catálogo vivo resolve (`llm/openrouter_catalogo.py`).

## Lanes de coleta (quem lança o sweep — NUNCA 2 lançadores)
- **Lane geral = SÓ o cron `*/30 tools/sweep_sei.sh`** (bounded, single-pass). É ele quem roda o
  pipeline completo: sweep → pais → cpf → refichar → depurar → árvore → direcionamento → lex → aprendizado.
- **`tools/sei_supervisor.sh` = DEPRECADO** (lane contínuo revertido no cont.25). Um resquício dele ficou
  vivo na memória de 09-06 a 07-07/2026 monopolizando o mutex (`pgrep tools.sei_sweep`) e starvando o
  downstream do cron de dia. NÃO relançar; se precisar de vazão extra, aumentar `--max` do cron.
- **`tools/bombeiros_supervisor.sh`** = lane dedicado FUNESBOM (deliberado, downstream próprio); espera o
  mutex do sweep geral e serializa browser via `browser_lock`.

## Melhorias 2026-07-05 (event-based + frescor)
- `sei_reader.py` usa **espera por condição com teto** (`_ate()`): pós-login, abertura da
  Pesquisa e pós-submit retornam assim que a página/árvore pinta (teto = sleep fixo antigo →
  pior caso idêntico, caso típico 5–15s mais rápido por processo).
- `sei_integra_fila.py --geral` agora re-enfileira processo **já arquivado que ganhou OB nova**
  (SIAFE ou TFE) depois do arquivo (`_fila_reler_por_ob`, bounded 10/rodada, valor desc) —
  OB nova = processo andou → re-ler, senão a perícia roda incompleta.
