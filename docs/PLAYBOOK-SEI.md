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

## 2-B. BUSCA POR TEXTO — enumerar processos por termo  ⭐ NOVO 2026-08-12

Serve para a pergunta "quais processos falam de X?" (fornecedor, objeto, número de contrato).

```bash
.venv/bin/python tools/sei_busca_mgs.py "AGILE CORP"        # `Considerar Documentos` já é o padrão
.venv/bin/python tools/sei_busca_mgs.py "MGS CLEAN" --sem-docs   # só metadado de processo
```

> ⚠️ **O ÍNDICE DE TEXTO LIVRE DO SEI É SOBRE DOCUMENTOS.** Com `Considerar Documentos`
> DESMARCADO — o padrão antigo desta ferramenta — a busca varre só metadado de processo e devolve
> **zero para QUALQUER termo**, inclusive o controle positivo. Foi o que manteve o item #10 do
> handoff aberto por um dia inteiro, com a causa registrada como "provável mudança de layout".
> Marcada a caixa, `LIMPEZA` devolve **213.563 documentos**.

Três armadilhas medidas em 2026-08-12, todas na mesma tela:

1. **A contagem não é `(N registros)`** — é `<div class="pesquisaBarraD">Exibindo 1 - 10 de
   213.563</div>`. O parser antigo procurava a primeira forma e não achava nada.
2. **`Nenhum resultado encontrado` é TEMPLATE ESCONDIDO** — está no HTML mesmo quando há 213.563
   resultados. Lê-lo no texto cru como veredito é publicar ausência que não existe.
3. **Zero legítimo ≠ não consegui ler.** `parse_resultado` devolve três estados —
   `com_resultado`, `sem_resultado` e `nao_parseei` — e **`nao_parseei` NUNCA é zero**. Enquanto os
   dois últimos saíam iguais (`n_total: 0, n_registros: null`), a causa ficava invisível.

**Onde rodar.** A sessão itkava é ÚNICA por IP: rodar a busca por fora do ciclo do sweep disputa a
sessão e devolve zero com cara de "não achei". O caminho certo é o `data/sei_busca_pedidos.txt`,
que o `tools/sweep_sei.sh` consome DENTRO do ciclo (sessão já é dele) e sempre com controle
positivo — se o controle não devolver contagem válida, o ciclo ABORTA a busca em vez de registrar
um zero inconclusivo. Fora do ciclo, exige `load < 1,7` (vm_guard) e paciência.

## 3. Leitura pontual sem íntegra (browser)  ⭐ REESCRITO 2026-07-10

> ⚠️ **Teto de texto por documento = `SEI_MAX_CHARS_DOC` (default 60000, era 20000 até
> 2026-08-01).** O cap antigo decapitava a CONCLUSÃO de parecer longo e o juízo LLM condenava
> documento que na verdade concluía (14 falsos escala-3). Truncado legado: lista em
> ⚠️ **0 documentos NÃO é processo vazio.** Antes de anotar INDISPONÍVEL: (1) controle
> positivo (mesmo método, mesma sessão, processo sabidamente bom); (2) re-teste na VM-2. A
> espera da árvore já produziu falso INDISPONÍVEL em massa sob carga — curado em 2026-08-02
> (`_esperar_arvore` espera os NÓS, não o frame); detalhe em
> `~/vault/aprendizados/falso-indisponivel-corrida-da-arvore.md`.
>
> `data/recaptura_cap21k.json`; requeue bounded diário `tools/sei_reparar_truncados --cap
> --aplicar --max 40` (cron 05:40) + re-arquivo automático por FRESCOR no
> `sei_arquivar_do_cache` (cache mais novo que o manifest → re-arquiva, antigo vai p/
> `_substituido/`).
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
- **⚠️ Contexto DECLARADO não é permissão** (2026-07-28). O plano usava o contexto que o
  catálogo anuncia. Com 1M declarado, SEI-080001/003535/2025 (801.665 caracteres, ~400.827
  tokens) saiu como *"Modo de leitura: leitura integral"* e produziu **10 KB de dossiê com
  ZERO documentos citados** — processo de R$ 15,4 milhões, nota no vault sem indício algum.
  Agora vale `TETO_PRATICO_CTX = 128_000` (`sei/dossie_fracionado`), cortando **para baixo,
  nunca para cima**. Medido: **61 processos** do acervo iam numa tacada só, o maior com 544
  mil tokens. O banco de provas já dizia o porquê: três modelos que gabaritam tarefa curta
  ZERAM num documento de 25 mil tokens.
- **Dossiê vazio ≠ processo limpo.** Quando nenhum provedor responde, o dossiê registra "lote
  N não pôde ser lido" e segue — mas o cabeçalho continua dizendo "Documentos com texto: 35",
  porque essa contagem vem da CAPTURA. Medido: 4 dos 157 processos analisados estavam assim,
  somando R$ 70,2 mi, e os 4 geraram nota com `indicios: 0`. Hoje a nota nasce com ⚠️,
  `leitura_incompleta: N` no frontmatter e o aviso ANTES do número.

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

### Reavaliar o que já foi lido — sem gastar cota  ⭐ NOVO 2026-07-28
```bash
.venv/bin/python tools/sei_reindiciar.py             # só relata o que mudaria
.venv/bin/python tools/sei_reindiciar.py --gravar    # regrava as notas que mudaram
```
Melhorar a régua **não conserta o que ela já escreveu**. O DV parou de contar o rótulo do
roteiro às 14:34; às 13:50 uma nota já dizia "4 divergência(s)" — três falsas. 81 das 145
notas nasceram antes do conserto; **43 foram saneadas**, custo zero (o dossiê está em
`output/dossies/`, e régua é código sobre texto já citado).

Duas armadilhas que o reindiciador ensinou, e valem para qualquer reprocessamento:
- **Contagem igual não é conteúdo igual.** A 1ª versão comparava o NÚMERO de indícios e deu
  como inalterada justamente a nota que motivou tudo (3 antes, 3 depois; o DV dentro dela caiu
  de 4 para 1). Compara-se o TEXTO, ignorando `analisado_em`.
- **Reavaliar não é reler:** a data de leitura é preservada. Carimbar hoje mentiria sobre
  quando o processo foi lido.

### `--refazer` ≠ `--reler` (um é grátis, o outro cobra)  ⭐ NOVO 2026-07-28
| flag | o que faz | custo |
|---|---|---|
| `--refazer` | ignora o índice e reaplica as RÉGUAS sobre o dossiê em disco | zero |
| `--reler` | joga fora o dossiê e LÊ o processo de novo (antigo vai para `_substituidos/`) | cota de modelo |
| `--fila-releitura` | analisa só `data/fila_releitura.json`, na ordem de valor DELA | — |

**Tirar o processo do índice NÃO faz o dossiê ser refeito.** `analisar()` só chama o gerador
quando o arquivo não existe. Foram 22 processos devolvidos à fila para releitura, a série os
pegou, achou os dossiês antigos, reaproveitou e marcou como analisados: medido depois, **0 de
22 tinham dossiê refeito**. Para reler de verdade, `--reler`.

`--fila-releitura` tem ordem própria de propósito: a `fila()` normal exclui credor
não-fornecedor e daria **R$ 0,00** para os repasses de maior valor, jogando-os para o fim.

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

## Quais N documentos ler — nunca só "quantos"  ⭐ NOVO 2026-07-28

`SEI_MAX_DOCS=40` limita a leitura por tempo de browser, e isso está certo. O erro era a
ESCOLHA: `documentos[:40]` pega os PRIMEIROS da árvore, e a árvore do SEI começa nos despachos
de abertura. Em SEI-070002/006145/2024 (791 documentos), os 40 primeiros traziam 32 peças de
tramitação e 4 de valor alto — enquanto o processo tem 38 de valor alto, **33 deles pareceres
jurídicos**, todos cabendo no mesmo orçamento. A ficha resultante afirmava faltar "documentação
da licitação e comprovante de pagamento" num processo com **30 Ordens Bancárias** nos autos.

`classificador_doc.ordenar_para_leitura` escolhe por valor fiscalizatório, preservando a ordem
da árvore dentro de cada faixa (a árvore é cronológica: entre peças igualmente decisivas, a
sequência dos atos importa). Medido em 473 processos onde o corte morde: documentos decisivos
lidos **3.032 → 6.472 (2,1×)**, e **zero** processos perdem.

> A Ordem Bancária não existia na taxonomia central e caía em `outros` → valor baixo → texto
> descartado. `cadeia_processo` já a reconhecia; a taxonomia ficou para trás. **Ao criar
> régua nova, procurar a taxonomia que já existe** — duas listas de tipos divergentes é dívida
> que só aparece quando alguém compara.

**A regra geral, que não é sobre o SEI:** limite sem critério vira amostragem por acaso. Onde
a casa corta lista, perguntar **quais** N.

## Recapturar ≠ reanalisar  ⭐ NOVO 2026-07-28

`sei_triagem_flags.encaminhamento` manda **recapturar** todo processo cujas flags são só
lacuna, supondo que a queixa reflete o acervo. Nem sempre reflete: o processo acima tem 294
documentos arquivados aqui. Recapturar gastaria sessão SEI para trazer o que já temos e
devolveria a mesma ficha enquanto a leitura continuasse nos 2 documentos.

`encaminhamento_com_acervo(flags, docs_no_acervo=…, docs_lidos=…)` separa **reanalisar** de
**recapturar**; sem saber o acervo, devolve o que a régua antiga devolvia.

## Processo ENCERRADO não se relê — mas segue auditável  ⭐ NOVO 2026-07-28

O sweep de captura já pulava árvore encerrada; a ANÁLISE, que gasta cota, não. Três condições,
todas necessárias (`compliance_agent/sei/encerramento.py`):

    já foi lido        — nunca pular o que nunca se leu; encerrado e não lido é o PIOR caso
    está encerrado     — Termo de Encerramento no arquivo OU `sei_arvore.encerrado`
    sem pagamento novo — OB posterior à leitura reabre; pagar depois do encerramento é sinal

Leitura INCOMPLETA não conta como lida — pular por "já lido" cristalizaria dossiê que não cobriu
o processo. Medido: 308 encerrados pelo arquivo, 184 pela árvore, **51 concordam** (a divergência
é informação: árvore sem termo no arquivo sugere captura parcial). Tira 23 de 170 da fila.

`--incluir-encerrados` força. O veredito traz sempre o MOTIVO: o que cai é a prioridade de
RELER, nunca a de fiscalizar.

## Duas máquinas capturando: fatia determinística  ⭐ NOVO 2026-07-28

```bash
JFN_SWEEP_FATIA=0/2 bash tools/sweep_sei.sh     # VM-1 (padrão do script)
JFN_SWEEP_FATIA=1/2 bash tools/sweep_sei.sh     # VM-2 (imposto pelo timer systemd)
```
Divide pelo hash do número do processo: sem lock distribuído, sem heartbeat, sem uma máquina
precisar saber que a outra existe. Medido: **21.045 + 20.695 = 41.740**, o universo inteiro, sem
sobreposição. Configuração inválida LEVANTA — cair no padrão faria as duas varrerem tudo.

> Contexto: 45.939 processos citados em OB, 2.007 com texto, vazão de 102/dia. Uma máquina só
> levaria ~430 dias.

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
- ❌ **Confiar no contexto DECLARADO do catálogo** para decidir "cabe inteiro" — corte pelo
  teto prático (128k). Capacidade anunciada ≠ capacidade real.
- ❌ **Tirar do índice achando que isso reler** o processo: sem `--reler`, o dossiê em disco é
  reaproveitado e o processo volta marcado como analisado, com o mesmo dossiê de antes.
- ❌ **Editar `data/analise_serie.json` com a série rodando.** O lote em execução tem o índice
  em memória; ao terminar, ele grava — e antes de `gravar_indice_mesclado` isso apagava a
  edição em silêncio. Pare o produtor por PID, e **`pgrep -f` casa o wrapper `timeout` junto**:
  filtre pelo interpretador (`grep -E "^[0-9]+ [^ ]*python"`) e confira com `ps` antes de
  matar. Matar o wrapper deixa o filho vivo, gravando.
- ❌ **Apresentar transferência a ente federativo como pagamento de contratação.** Repasse a
  prefeitura ou a fundo municipal é despesa legítima e de fiscalização DIFERENTE (prestação de
  contas do convênio); a nota declara a natureza — não se espera ali edital, contrato ou
  fiscal designado.

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

## 6. Saúde do acervo (o que grita quando algo apodrece em silêncio)
```bash
PYTHONPATH=. .venv/bin/python -m tools.sentinela_integridade          # 4 invariantes de QUALIDADE
PYTHONPATH=. .venv/bin/python -m tools.sei_purgar_anexo_cache --aplicar --max 20
PYTHONPATH=. .venv/bin/python -m tools.sei_reparar_truncados --sem-texto --aplicar --max 40
PYTHONPATH=. .venv/bin/python -m tools.sei_reparar_truncados --cap --aplicar --max 40
```
`pipelines_slo` responde "produziu no prazo?"; a **sentinela_integridade** responde "produziu
CERTO?" — cache obeso (binário serializado), texto amputado no teto, processo arquivado sem
texto, veredito sem prova. Cron `37 * * * *`, alerta só na transição ok→violado. Foi ela que
achou 128 caches obesos e 147 capturas vazias silenciosas em 2026-08-02.
