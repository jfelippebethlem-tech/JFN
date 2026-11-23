---
tipo: plano
projeto: JFN
atualizado: 2026-11-23 (versão aprovada pelo dono, 04h20)
frente: 1123-0334-jfn-core-1d82
fontes: [~/Plano_Diretor_de_Otimizacao_e_Arquitetura_Estado_da_Arte_-_Sweep_SEI.pdf (Gemini), ~/Plano_Diretor_Arquitetura_Sweep_SEI_Reescrita_Total.pdf (ChatGPT)]
---

# Plano — JFN como Plataforma de Evidências (sessão de 23/11/2026)

## 1. Contexto

**Pedido do dono.** Ele enviou dois planos externos:
- Gemini: `~/Plano_Diretor_de_Otimizacao_e_Arquitetura_Estado_da_Arte_-_Sweep_SEI.pdf`;
- ChatGPT: `~/Plano_Diretor_Arquitetura_Sweep_SEI_Reescrita_Total.pdf`.

E pediu, nas palavras dele ou em resumo fiel:
- seguir o espírito dos planos; reescrever se valer ("vamos à luta");
- **ler 100% do texto**, sem resumo de IA como substituto;
- automelhoria que vigia e acusa;
- HD externo organizado e indexado;
- usar VM-1, VM-2 e it-campo do melhor jeito, **com tudo funcionando sem o it-campo**;
- menos erro, menos token, mais qualidade, velocidade e confiabilidade, pensando no longo prazo.

**Decisões do dono nesta sessão:**
- Failover: **VM-3 grátis como testemunha**, se a cota oficial permitir; senão, o it-campo.
- Leitura integral: **mistura de API com teto, por prioridade, e assinatura.**

### Achados medidos (base do desenho)

| Achado | Número |
|---|---|
| Texto do acervo que a perícia integral alcança | **17,3%**; 8.321 de 10.730 processos cortados pelo teto de 240k caracteres, 12k por peça |
| Recaptura sem documento novo | **25%** do tempo de captura, 798 casos em 7 dias |
| Fila do Opus em 7 dias | entraram 5.433, saíram 267; 5.751 pendentes |
| Concordância do Opus com os motores baratos | **28%** (108 de 379) |
| Reaproveitamento do cache do Opus pela assinatura | 7% |
| Disco | VM-1 89%; **VM-2 96%** (112 GB de frio) |
| Carga | VM-1 com load 8–12 e swap cheio; **VM-2 com load 1,6** |
| Estado do ciclo | 3 bancos SQLite, cerca de 25 JSON/JSONL soltos, 2 árvores de PDF, 4 grafias do mesmo processo |
| Leituras do processo pela IA | 4 a 6 por processo, nenhuma completa |
| Documentos com número SEI no título | 99,2% de 518.756 |
| GPU do it-campo | RTX 5070 com **8 GB** |

### Pesquisa externa (fontes oficiais, 23/11)
- **Temporal:** pede cerca de 7 núcleos e 13 GB. No it-campo, faria tudo parar quando o notebook fecha. **Fora.**
- **Fila:** fila sobre PostgreSQL com `SKIP LOCKED`.
- **Failover automático:** exige 3 nós.
- **Recall da IA:** cai a partir de cerca de 32k tokens (NoLiMa, Context Rot). Por isso, fatias de 8 a 16k tokens.
- **Custo:** Batch da Anthropic custa 50% menos, e o cache de prompt soma a esse desconto. Haiku 5.5 custa US$ 0,10 por milhão de tokens de entrada; **reconferir na página oficial antes de ligar.**
- **Preços do Gemini:** dobram em 01/12/2026 e em 01/01/2027.

## 2. Já entregue nesta sessão

Commits locais; o push sai pelo portão.
- `f21bc7a0`, `6f43c82e`: a depuração do frio passa pelo semáforo e pela carga.
- `ee290fa6`: sensor `plataforma` na automelhoria (5 vigílias) e `docs/PLANO-PLATAFORMA-EVIDENCIAS.md`.
- `dacaa738`: `llm_trace` passa a gravar a tarefa.
- `e39607ce`: o laudo declara a cobertura real.
- `b9215330`: guarda de convergência da recaptura, lida do log (29 processos).
- `03b485e9`: semáforo único de pesado (`tools/pesado.sh` e despachante); 7 linhas de crontab embrulhadas. Backup em `~/.config/jfn/backups/crontab-20261123-0353.txt`.
- `db65bce7`: estado da Fase 0.
- **Não commitado:** `compliance_agent/evidencias.py` e `tests/test_evidencias.py` (8 testes verdes). A carga de teste foi adiada pelo semáforo, com load 11.
- **Em curso** (só copia e confere): VM-2 → `D:\JFN-Frio\sei\{pdfs_escaneados,integras_cache}` via rclone pela VM-1, em `~/JFN/data/hd_migracao/`. A primeira tentativa, pelo WSL, deu ENOMEM e deixou sobras em `D:\JFN-Frio\sei_pdfs` e em `sei_cache`.
- RTK mantido (economia medida de 82,5%), com `ps` nas exceções.

## 3. Arquitetura-alvo

**Regra:** cada função tem um dono e uma volta. Nada essencial depende do it-campo.

| Papel | Dono | Volta |
|---|---|---|
| Estado canônico em PostgreSQL 16 (identidade, filas, fatos, leituras, laudos v2) | **VM-2** | Fases 1–5: WAL contínuo para nuvem grátis e restauração testada toda semana na VM-1. Fase 6: réplica viva na VM-1 já aliviada, com a VM-3 grátis de testemunha (`pg_auto_failover`) e o it-campo de reserva |
| Painel, API, Yoda e `compliance.db` legado | VM-1 | — |
| Captura SEI | it-campo (N sessões) e VM-2 (1 sessão) | só a VM-2; a VM-1 em último caso (regra atual) |
| Conferência e arquivamento das entregas | **VM-2** (sai da VM-1) | VM-1 |
| OCR | GPU do it-campo, por job com prazo | a reserva em CPU da VM-2 assume quando o prazo vence, o que fecha a janela INDETERMINADA de 105 min |
| Leitura por IA em volume | Batch da Anthropic chamado da VM-2, com teto no console; e a assinatura | cascata atual |
| Juízo de risco | Opus pela assinatura | a fila espera; o item nunca vira VERIFICADO sem ele |
| PDF original | quente na VM-2 **até o OCR terminar**; depois morno no HD (`D:\JFN-Frio`, indexado); frio no Drive pela porta única | o PDF pendente de OCR nunca sai da VM-2 |
| Texto do acervo | VM-1 (painel e Yoda), com cópia única para a VM-2 conferida por md5 | — |

**Núcleo de dados:**
- **`processos`:** uma chave canônica `NNNNNN/NNNNNN/AAAA` e uma única função de normalização, que acaba com as 4 grafias.
- **`arvores`:** hash de cada captura.
- **`documentos`:** identificador `sei:<nº>` ou `pos:<i>`; número repetido vira `#2` e nunca some.
- **`versoes`:** sha256; nada é sobrescrito.
- **`paginas`:** perfil de cada página (nativa, escaneada ou branca).
- **`artefatos`:** texto por página × motor@versão, com bbox e limite de disco.
- **`fatos`:** valor, trecho literal, documento, página, posição, motor e verificação.
- **`leituras`:** cobertura por processo × estágio.
- **`jobs`:** reserva atômica (`UPDATE … WHERE id=(SELECT … FOR UPDATE SKIP LOCKED) RETURNING`), prazo pelo relógio do servidor, ficha de posse, teto de tentativas e estado de quarentena.
- **`eventos`:** registro de eventos.
- **Regra de migração:** uma única direção de verdade por tabela, com data de corte. O legado vira leitura derivada e **nunca há escrita nos dois lados.**

**Leitura integral comprovada:**
1. O código monta o índice do processo.
2. O texto é cortado em fatias de 8 a 16k tokens, sem quebrar documento quando couber.
3. O código **mascara CPF e conta bancária** antes de enviar, com mapa reversível que fica local. Peça sigilosa não sai.
4. A IA extrai fatos com citação literal: Haiku em lote, com o prefixo fixo em cache.
5. O código confere cada citação. **Fato sem citação conferida fica INDISPONÍVEL.**
6. O fato fica guardado pela chave `(sha do documento, versão do prompt, modelo)`; documento inalterado não é relido.
7. Perícia, Lex e ficha consomem esses fatos e releem o trecho original quando precisam.
8. A cobertura é gravada; abaixo de 100%, a leitura é "parcial".
9. O hash de cada payload enviado à API fica registrado.

**Ordem de leitura, conforme a decisão do dono:** por valor pago e risco. A API trabalha até o teto que o dono fixar. A assinatura cobre o que entra novo e o juízo.

## 4. Fases

A ordem foi revista para entregar cedo o ganho principal e validar custo e qualidade antes da infraestrutura.

| # | Fase | Entregas | Critério de saída |
|---|---|---|---|
| 0 | **Fechar a segurança operacional** | Ler `check_*.txt` da migração. Gerar `D:\JFN-Frio\_indice\indice.jsonl` e `00-LEIAME.md`; registrar no índice único e no jfn-brain. Apagar da VM-2 só o que foi conferido, mantendo os PDFs pendentes de OCR. Limpar as sobras no HD. Fazer o push. `MemoryHigh` no `jfn.service`. Tokens de OpenRouter, Nous e Groq no trace. md5 em `colher_vm2.sh` e no frio. Commit de `evidencias.py` com a correção da reserva | VM-2 abaixo de 70% de disco; nenhum fluxo sem md5; o sensor deixa de acusar `disco_vm2` |
| 1 | **Piloto da leitura integral** | Fatiador, máscara de CPF e conta, verificador de citação e cliente Batch sobre os arquivos que já existem. Fatos no SQLite do `evidencias.py`. **50 processos**, já conferidos pelo Opus, mais 30 com fatos anotados à mão (ouro de extração) | Tokens e custo reais medidos e projetados para o acervo; recall ≥ Opus no ouro; 0 citação inexistente aceita; o dono fixa o teto |
| 2 | **Fila do Opus por risco** | Entrada por divergência, valor, detector grave e baixa confiança, mais amostra estratificada. Os 5.751 pendentes são triados e o restante recebe "NÃO JULGADO — fila", visível no painel. Laudos antigos marcados com a cobertura real | A saída da fila alcança a entrada; o painel não mostra item não julgado como limpo |
| 3 | **Fundação** | PostgreSQL na VM-2 (tuning para 2 vCPU e 11 GB). WAL-G ou pgBackRest para nuvem grátis, com restauração semanal automática na VM-1. Esquema; `evidencias.py` portado, com testes de concorrência no PostgreSQL. Cópia do texto para a VM-2 com md5. Carga dos 12,6 mil manifestos. Conferir a cota grátis oficial e abrir a VM-3 se houver | Carga bate 100% com os manifestos; restauração testada; worker derrubado sem perda nem efeito em dobro; disco da VM-2 abaixo de 60% |
| 4 | **Captura por delta** | Jobs de captura com reserva. O worker baixa só documento novo ou retificado. Entrega e conferência na VM-2 | Modo sombra por 7 dias: zero documento novo perdido; recaptura igual abaixo de 5%; processos novos por hora em alta |
| 5 | **Documento e OCR** | Perfil por página, incluindo página em branco. Jobs por página com prazo (GPU ou reserva). bbox gravada; conferência por recorte; SIAFE como nível A. Ouro de OCR com cerca de 200 páginas | Não inferior ao atual no ouro; 0 valor inventado em campo crítico; OCR anda com o it-campo desligado |
| 6 | **Leitura integral plena e migração** | Batch por prioridade, até o teto. Perícia, Lex, ficha e 360 consomem fatos. Legado desligado módulo a módulo. Réplica viva na VM-1, testemunha na VM-3 | Cobertura de 100% nos processos lidos; VM-1 com load abaixo de 3 sustentado; failover testado |

**Sensores novos na automelhoria**, com aviso pelo Yoda só quando o dono pedir: custo por dia e por processo, idade do job mais velho por fila, jobs em quarentena, atraso do WAL, resultado do último teste de restauração e cobertura de leitura.

### Estado da execução (23/11/2026, 05h20)
| Fase | Feito | Falta |
|---|---|---|
| 0 | semáforo de pesado, depuração com carga, guarda de convergência, sensor `plataforma`, cobertura no laudo, trace com tarefa e caracteres, `MemoryHigh` 3,5 GB no `jfn.service` (pico medido 3,3 GB), `tools/hd_indice.py` | migração VM-2 → HD (rclone pela VM-1, ~5 MB/s, término ~11h) → índice/LEIAME/brain → apagar da VM-2 só o conferido e fora da fila de OCR. md5 extra em `colher_vm2.sh`/frio: **dispensado** (rsync já confere cada arquivo; `colher_vm2` nem está no cron) |
| 1 | `leitura_integral.py` com porta do lote (captura completa + texto nativo + sha não lido), máscara de CPF/conta, verificador literal (datas por extenso), reverificação sem gasto. Lote li-1: 50 proc, US$ 1,12, 3.733 verificados, 820 recusados (303 citações inexistentes barradas), 7.798 de OCR a confirmar; 36/75 achados do Opus eram atos não extraídos → prompt li-2 | li-2 colhido: 39 proc pela porta, 253 fatias, **US$ 0,33**, 3.809 verificados, 5,5% recusados (79 citações inexistentes barradas), 0,8% sem resposta, 1.024 atos/decisões/condições; **52% dos achados do Opus** cobertos no universo comparável (o resto são inferências entre documentos — camada de juízo). **Custo do acervo pela porta: ≤ US$ 141** (8.899 proc, 3,05 bi chars nativos, US$ 0,046/M chars). Falta: teto do dono; ouro de extração (30 processos anotados) |
| 2 | amostra de controle dos ⚪ na fila do Opus (1 a cada 8). Leitores de `lex_execucao`: conferido que já marcam estado por motor (`certeza/orquestrador` calibra por nível; `correlacao_sei` usa `estado_do_laudo`; `cge_confronto`/`indeterminados` não apresentam veredito) | medir recall pela amostra após ~1 semana |
| 3–6 | — | Fase 3 depende do disco da VM-2 (após a migração). **VM-3 grátis NÃO cabe** (doc oficial Oracle Always Free, conferida 23/11: A1 = 2 OCPU/12 GB por conta, já usado por cada VM; 2 Micro AMD grátis por conta, mas o disco grátis é 200 GB por conta somando boot — as VMs atuais já usam ~191–194 GB) ⇒ testemunha = **it-campo** (escolha de reserva do dono). Alternativa só do dono: 3ª conta grátis (termos da Oracle não conferidos) |

**Medidas do acervo que orientam a leitura integral:** processo mediano 146 mil caracteres; 10% maiores = 71% do
texto; os 119 maiores documentos (460 M caracteres) são planilhas (lidas por código); 72,7% do texto é nativo e
27,1% veio de OCR (espera confirmação por página); 8.834 de 12.707 processos têm captura declarada completa.

## 5. Arquivos críticos
- `compliance_agent/evidencias.py`: núcleo. Corrigir `reservar`, que hoje faz SELECT e depois UPDATE (linhas ~116–127).
- `compliance_agent/pericia_integral.py`: teto em `:59-60`, cobertura em `_texto_por_valor`.
- `compliance_agent/llm/claude_api.py`: cache em `:409`; o cliente Batch fica ao lado.
- `compliance_agent/llm/conferencia_opus.py`: regra de entrada da fila.
- `compliance_agent/sei/classificador_doc.py`: `ordenar_para_leitura`.
- `compliance_agent/sei/acervo_texto.py`: `ler`.
- `tools/sei_integra_vm2.py`, `tools/vm2_conferencia.py`, `tools/itcampo_sei_paralelo.py`: captura e entrega.
- `tools/sei_ocr_gpu_fila.py`, `tools/sei_ocr_reserva.py`, `deploy/itcampo/ocr_gpu/ocr_gpu_worker.py`: OCR.
- `tools/colher_vm2.sh`, `tools/sei_arquivo_frio.sh`: md5.
- `tools/automelhoria_geral.py`: sensores.
- `compliance_agent/armazenamento.py` e `config/armazenamento_nuvens.json`: o HD como lugar.
- `docs/PLANO-PLATAFORMA-EVIDENCIAS.md`: plano versionado, a manter igual a este.

## 6. Verificação
- **Testes:** em lotes, na VM-2 (`tools/testar_na_vm2.sh`). Nunca pytest amplo na VM-1.
- **Controle positivo e negativo nos dados reais** antes de qualquer troca. Modo sombra antes de desligar o legado.
- **Antes e depois sempre no mesmo universo:** cobertura de leitura, recaptura igual, processos novos por hora, load da VM-1, fila do Opus (entrada × saída), custo por processo, acurácia no ouro.
- **API paga:** teto no console da Anthropic e estimativa de requisições × preço antes de ligar qualquer lote.
- **Fechamento de cada etapa:** reescrever `~/vault/RETOMADA.md`; fato durável no jfn-brain; memória quando valer; quadro `1123-0334-jfn-core-1d82` atualizado; commit semântico e push.

---

## Anexo A — Veredito item a item sobre os dois planos externos

| Proposta | Plano | Medido no sistema (23/11) | Decisão |
|---|---|---|---|
| Poda de restritos antes do despacho | Gemini | **Já existe** (`sei_integra_vm2.py:109-125`, reavaliação 30 d). "216/1.137" não se reproduz: 287 de 4.978 tentativas, quase todas reavaliação legítima; desperdício real ≈ 38 | Manter; estender a `sei_integra_fila.py` (não filtra) |
| Captura incremental por documento | ambos | **Parcial**: retoma por `id_documento` só se a pasta local existir; sem `tree_hash`; nó não sabe o que já está guardado → recaptura inteira | **Fase 2** |
| Guarda de convergência da recaptura | ambos | **Parcial**: 2 reprovações → 24 h fora, sem comparar árvore/motivo; 23 processos com ≥ 2, 13 com ≥ 3 | **Fase 0** |
| VM-1 só coordena; fim da "tempestade de crons" | ambos | ~105 crons; 5 pesados simultâneos com swap 100%; despachante com semáforo **já existe** (`propagacao.py:583`) mas os crons antigos correm ao lado; nenhum limite systemd em `jfn.service` | **Fase 0** |
| Disco: expurgo e gatilho | Gemini | VM-1 89%, **VM-2 96%** (frio parado: "só 8 GB livres"); `vm_guard` não olha disco | **Fase 0** (HD externo + gatilho) |
| Triagem por página antes da GPU | Gemini | **Já existe** no worker GPU (`pagina_nativa`); falta página em branco e triagem na reserva | Fase 3 |
| Conferência por recorte (ROI) | ambos | bbox **não é gravada** (Surya: só texto; RapidOCR: descartada); 2ª leitura relê página inteira | **Fase 3** |
| Confirmação pelo SIAFE | ambos | Código existe (`ocr_ia_prova.py:358-400`), **0 de 1.288** confirmações vieram dele | Fase 3 (com a ressalva do ChatGPT: "valor na fonte" ≠ "valor lido") |
| Perícia em 5 eixos numa chamada | Gemini | **Já é uma chamada, com 10 eixos** (`pericia_integral.py:427-456`) | Nada a fazer |
| Prompt caching | Gemini | API Anthropic já usa; **Opus pela assinatura lê ~9k de 127k do cache** (variável antes do fixo); Lex começa pelo variável | Fase 4 (reordenar prefixo) |
| IR resumido (`processo_ir.json`, −90% tokens) | Gemini | Não existe; `manifest.json` em 12.604 pastas é meio caminho | **Rejeitado como substituto do texto** (decisão do dono) → vira **índice determinístico + leitura integral** (§3) |
| Tirar "convergentes" da fila do Opus (5.731 → < 400) | Gemini | Fila: 5.750; entra por **falta de cota**, não por divergência; não há campo de convergência; **Opus concordou em só 28% (108/379)** dos conferidos | **Rejeitado.** Fila passa a ser por risco + amostra (Fase 5) |
| Temporal + NATS + PostgreSQL + MinIO + K8s, 16 semanas | ChatGPT | VM-1 e VM-2 com 2 vCPU/11 GB, swap cheio; um dono | **Rejeitado na forma**; adotado o **conteúdo** (idempotência, lease+fencing, estados, outbox) sobre SQLite e workers existentes (§4) |
| Dataset ouro, modo sombra, canário, gates | ChatGPT | Há bancadas pontuais (OCR 40 págs, régua do Sonnet) mas não um ouro fixo | **Adotado** (Fases 3–5) |
| Metas 2.000–3.000 proc/dia, OCR zerado em 24 h, 80 ms/campo | Gemini | — | Não são metas; são hipóteses medidas contra a linha de base |

**GPU do it-campo:** RTX 5070 **8 GB** de VRAM (o Gemini supôs 12 GB) — muda o tamanho de VLM viável.

---
