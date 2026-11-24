# ADR-001 — Autoridade de dados: uma fonte de verdade e um escritor por domínio

| Campo | Valor |
|---|---|
| **Estado** | Aceito (O1.4 do plano mestre v2, 24/11/2026) |
| **Plano** | `~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md` §3.8 (matriz), §2 (linha de base), §11 (aceite) |
| **Linha de base** | `tools/baseline_refatoracao.py --universo snapshot` (O1.3); saída fora do repo, em `~/.local/share/jfn/baseline/` |
| **Relacionados** | ADR-003 (armazenamento), ADR-004 (fila), ADR-011 (dados no git), ADR-012 (motor `jfn-fluxo`) |

## 1. Contexto

A linha de base do snapshot de 24/11/2026 (universo de paridade da parada de obras) mediu:

| Medida | Valor | Estado |
|---|---:|---|
| Tabelas do `compliance.db` | 164 | MEDIDO |
| Tamanho do `compliance.db` | 6.446.190.592 bytes | MEDIDO |
| Bancos SQLite em `data/` (fora do cache SEI) | 31 | MEDIDO |
| Arquivos `.json` soltos em `data/` | 147 | MEDIDO |
| Filas ou estados em JSON (tabela do §4) | 69 arquivos, em 57 linhas | MEDIDO (grep no código) |
| `compliance_analitico.db`: último SIAFE coletado | 20/11/2026 15:12 (o universo tem 24/11/2026 14:50) | MEDIDO: cópia ~4 dias defasada |
| PG `jfn_evidencias`: `fatos` / `jobs`, `processos`, `documentos`, `versoes`, `arvores` | 133.750 / 0 em cada | MEDIDO |

O mesmo dado é escrito em mais de um lugar. Exemplos:
- a fila de recaptura é gravada na VM-1 e copiada por `rsync` para a VM-2;
- as reservas de íntegras são gravadas por cada nó remoto e lidas na VM-1;
- os laudos ficam no `compliance.db` e os fatos ficam no PG.

Nenhuma dessas filas em JSON tem trava entre máquinas. A maioria não tem nem trava local: escreve com
`write_text` direto, e um leitor concorrente pode ler o arquivo pela metade.

## 2. Decisão

**Cada domínio tem uma fonte de verdade, um escritor único e uma data de corte.** Antes da data de corte vale a
fonte antiga. Na data de corte a fonte nova assume e a antiga vira leitura de legado. **Nunca há escrita nos
dois lados.**

### 2.1 Matriz de autoridade

| # | Domínio | Fonte de verdade | Escritor único | Leitores | Data de corte |
|---|---|---|---|---|---|
| D1 | **Fluxo**: jobs, eventos (outbox), agenda, nós, métricas | PG, schema `fluxo` (ADR-012) | supervisor `jfn-fluxo@<nó>`: reserva, conclusão e outbox na mesma transação; o planejador grava `agenda` | painel (visões E15), E18 observar, automelhoria | **Religação O9.0**: cron/timers/`propagacao.db` deixam de valer; `propagacao.db` vira legado de leitura |
| D2 | **Identidade**: processo, árvore, documento, versão, página, aquisição, transformação | PG `public.processos/arvores/documentos/versoes` (+ tabelas novas da O3) | handlers E2 (árvore), E3 (captura), E4 (texto), E5/E6 (OCR) | E8–E16, painel | **O3**: carga dos ~12,6 mil manifestos de `data/sei_arquivo/*/manifest.json`; depois o manifesto é derivado, não fonte |
| D3 | **Fatos, leituras, laudos v2, `execucao_regra`, achados, revisão, contestação, casos** | PG | E8 (fatos/leituras), E10 (`execucao_regra`/achados), E11 (laudos v2), E12 (conferência), E14 (casos) | E13, E15, E16 | **O6**: `pericia_integral`, `lex_execucao`, `alertas_triagem` e a fila do Opus (`conferencia_opus.db`) viram legado de leitura; laudo novo só no PG |
| D4 | **Coleta bruta**: SIAFE, TFE, PNCP, TCE-RJ, DOERJ, PCRJ, folha, sanções | `compliance.db` na VM-1 | **um escritor por tabela**: o E1 `coletar:<fonte>` daquela fonte. Worker remoto (VM-2/it-campo) **não** abre o `compliance.db`: grava em `resultados_*` no PG e o E15 aplica com idempotência na VM-1 | detectores (E10), perícia (E11), painel | Vigente desde a O2 (zero cron). Qualquer outro escritor é defeito |
| D5 | **Analítico pesado** | Parquet + DuckDB na VM-2 e no it-campo | exportador do E15 (a partir de D3/D4) | E10 em lote, E13 calibração | **O5**. O `compliance_analitico.db` (5,9 GB, ~4 dias defasado) não é fonte de nada; sai na O9.1 |
| D6 | **Memória e lições** | jfn-brain (PG) + vault | `cerebro_compartilhado lembrar` (brain) e o autor da nota (vault); uma fonte por lição | todos os agentes | Vigente |
| D7 | **Originais** (PDF, HTML, imagens) | VM-2 quente → HD morno (md5 + índice) → Drive frio | porta única `compliance_agent.armazenamento` (ADR-003) | E4/E5, dossiê | Vigente. `rsync`/`rclone` avulso é proibido |
| D8 | **Estados operacionais em JSON** (§4) | migram para D1 (`fluxo.jobs`/`payload`/`agenda`/`nos`/`metricas`) ou para o gateway de IA (ADR-005) | o handler do estágio de destino | — | Por estágio, quando ele entra no fluxo (O2–O6). Até lá, o escritor atual é o único autorizado |

### 2.2 Regras

1. **Um escritor por tabela ou arquivo.** O escritor é o nome do estágio ou do serviço, nunca "qualquer script
   que precisar". Um escritor novo exige atualizar este ADR no mesmo commit.
2. **Data de corte é um evento conferido.** No dia do corte:
   - o escritor antigo é desligado;
   - a contagem antes e depois bate com a linha de base (O1.3, `--comparar`);
   - a fonte antiga recebe a marca `legado_leitura` no inventário.
3. **Escrita entre máquinas passa pelo PG.** Nunca por `rsync` de JSON nem por SQLite em rede.
4. **INDISPONÍVEL ≠ 0.** Um leitor que não alcança a fonte de verdade devolve INDISPONÍVEL. Ele nunca cai para
   uma cópia defasada sem declarar essa cópia.
5. **Sem dado pessoal em JSON solto.** CPF vai mascarado ou em tabela com controle de acesso. Repo público:
   ADR-011.

## 3. Consequências

- **Positivas:**
  - acaba a corrida entre o JSON gravado e o JSON lido;
  - a paridade antes/depois fica mensurável por domínio;
  - a perda de um nó não corrompe uma fila compartilhada;
  - o painel lê uma fonte só (E15).
- **Negativas:**
  - o PG da VM-2 passa a ser crítico para D1–D3. Daí a restauração semanal como sensor (§11.11) e o modo
    degradado do §3.5;
  - durante a transição convivem leitores do legado e da fonte nova, com custo de manter os dois caminhos até
    a O9.1.
- **Riscos:**
  - um escritor esquecido continua gravando na fonte antiga depois do corte. Mitigação: catraca que procura
    escrita em tabela `legado_leitura` (O8);
  - a data de corte escorrega. Mitigação: cada corte é um item do backlog com critério "pronto" verificável.

## 4. Filas e estados em JSON soltos em `data/`

### 4.1 Como a tabela foi feita

- **Levantamento:** `git grep -F <arquivo>.json` em `*.py`, `*.sh` e `*.service` (os testes ficam fora),
  conferido à mão nos casos ambíguos.
- **Coluna `escritor`:** marcada `(inferido)` quando a escrita não está no mesmo arquivo que nomeia o caminho
  (o caminho chega por parâmetro ou o nome é montado). Toda linha `(inferido)` é **confirmada na O2.1 antes de
  migrar**.
- **Coluna `trava`:**
  - `flock`: o escritor usa `fcntl`/`flock`;
  - `atômica`: grava num temporário e faz `os.replace`/`mv`;
  - `nenhuma`: usa `write_text` direto.
- **Coluna `destino`:** o estágio da §3.2 e o lugar no fluxo (ADR-012).

### 4.2 Tabela

| # | Arquivo (`data/`) | Escritor | Leitores | Trava | Destino no fluxo |
|---:|---|---|---|---|---|
| 1 | `sei_fila_vinculo_ob.json` | `compliance_agent/vinculo_ob_contrato.py` | `tools/sei_sweep.py`; sonda em `config/propagacao.yaml` | atômica | E2 `arvore:` com prioridade única (§3.7) em `fluxo.jobs` |
| 2 | `bombeiros_sei_fila.json` | `tools/bombeiros_achar_edital.py` | `tools/sei_bombeiros_sweep.py`, `bombeiros_integra_supervisor.py`, `bombeiros_alerta_telegram.py`, `lex_bombeiros_aprofundado.py`, `pericia_bombeiros_reconcilia.py`, `relatorio_bombeiros.py`, `sei_integra_fila.py`, `sei_integra_vm2.py` | nenhuma | E2/E3 (a lente "bombeiros" vira filtro, §3.6); fila some |
| 3 | `agente_publico_fila.json` | `tools/agente_publico_reverso.py` (`gravar_fila`) | `tools/sei_sweep.py` | nenhuma | E2 `arvore:` (motivo `osint`) |
| 4 | `fila_recaptura_compartilhada.json` | `tools/sweep_recaptura_integral.py` (VM-1) | `tools/colher_vm2.sh` (copia por `rsync` para a VM-2) | nenhuma; **duas máquinas** | E3 `capturar:` em `fluxo.jobs`. Acaba a cópia por `rsync` |
| 5 | `sei_ocr_reserva_estado.json` | `tools/sei_ocr_reserva.py` | `tools/inventario_jobs.py` | flock | E5 `ocr:` (lease em `fluxo.jobs`) |
| 6 | `sei_fila_dinheiro.json` | `tools/sei_fila_por_dinheiro.py` | `tools/sei_integra_vm2.py`, `deploy/systemd/jfn-integra-fila.service` | nenhuma | prioridade única do planejador (§3.7), não fila |
| 7 | `fila_releitura.json` | sem escritor no código versionado (gerado à mão) | `tools/sei_analise_em_serie.py --fila-releitura` | — | E8 `fatos:` reenfileirado por evento |
| 8 | `.integras_fila_pre.json` | `tools/sei_integra_vm2.py` | o próprio | flock | E3 `capturar:` |
| 9 | `.integras_vm2_reserva.json` | `tools/sei_integra_vm2.py` (inferido) | `tools/sei_integra_fila.py` | nenhuma | lease de `fluxo.jobs` (substitui a reserva por nó) |
| 10 | `.integras_itcampo{1..9}_reserva.json` (9 arquivos) | trabalhador de cada nó (nome montado `.integras_<nó>_reserva.json`) | `tools/sei_integra_fila.py` | nenhuma; **várias máquinas** | lease de `fluxo.jobs` |
| 11 | `.sei_cpf_acervo_vistos.json` | `tools/sei_cpf_sweep.py` (inferido) | `tools/sweep_sei.sh` | nenhuma | E8 (cursor vira `efeito` do job) |
| 12 | `.foco_couto_processos.json` | `compliance_agent/foco.py` (inferido) | o próprio | atômica | prioridade única (constante `governo_couto.INICIO`) |
| 13 | `recaptura_integral_progresso.json` | `tools/sweep_recaptura_integral.py` | o próprio | nenhuma | E3 (progresso = `fluxo.jobs.estado`) |
| 14 | `propostas_sei_extrair.json` | `tools/propostas_sei_extrair.py` | sonda em `config/propagacao.yaml` | nenhuma | E8 `fatos:` |
| 15 | `siafe_dias_verificados.json` | `tools/siafe_recoletar_dias.py` | o próprio | nenhuma | E1 `coletar:siafe` (`aquisicao` por dia) |
| 16 | `siafe_dias_tfe_verificados.json` | `tools/siafe_recoletar_dias.py` | o próprio | nenhuma | E1 `coletar:tfe` |
| 17 | `siafe_dias_inconclusivos.json` | `tools/siafe_recoletar_dias.py` | o próprio | nenhuma | E1 (`quarentena` em `fluxo.jobs`) |
| 18 | `siafe_documento_sweep_estado.json` | `tools/siafe_documento_sweep.py` | sonda em `config/propagacao.yaml` | nenhuma | E1 `coletar:siafe_documento` |
| 19 | `siafe_agenda_documentos.json` | `compliance_agent/siafe_agenda.py` (nome montado) | sonda em `config/propagacao.yaml` | nenhuma | `fluxo.agenda` |
| 20 | `siafe_agenda_status.json` | `compliance_agent/siafe_agenda.py` (nome montado) | sonda em `config/propagacao.yaml` | nenhuma | `fluxo.agenda` |
| 21 | `siafe_status_releitura.json` | `compliance_agent/siafe_status_ob.py` | sonda em `config/propagacao.yaml` | nenhuma | E1 `coletar:siafe_status` |
| 22 | `siafe_dreno_quarentena.json` | `tools/siafe_drenar_capados.sh` (inferido) | `tools/automelhoria_geral.py` | flock (no script) | E1 (`quarentena`) |
| 23 | `emendas_checkpoint.json` | `compliance_agent/emendas/coletor.py` | o próprio | atômica | E1 `coletar:emendas` (cursor no `payload`) |
| 24 | `folha_estado_progresso.json` | `compliance_agent/collectors/folha_estado.py` | o próprio | flock | E1 `coletar:folha` |
| 25 | `lentes_estado.json` | `tools/lentes_materializar.py` | `rotas/investigacao.py` | nenhuma | E15 `materializar:lentes` (visão no PG) |
| 26 | `digest_estado.json` | `tools/digest_diario.py` | `tools/lentes_materializar.py` | atômica | E16 `entregar:digest` |
| 27 | `vault_retratos_estado.json` | `compliance_agent/vault_retratos.py` | o próprio | atômica | E15 `materializar:vault` |
| 28 | `cerebro_ponte_estado.json` | `compliance_agent/cerebro_ponte.py` | sonda em `config/propagacao.yaml` | nenhuma | E17 `manter:brain` |
| 29 | `pipelines_slo_estado.json` | `tools/pipelines_slo.py` | `rotas/sistema.py`, `tools/lentes_materializar.py` | nenhuma | E18 `observar` → `fluxo.metricas` |
| 30 | `qualidade_estado.json` | `compliance_agent/qualidade/doc.py` (inferido) | `qualidade/estado.py`, `qualidade/sensores.py`, `tools/automelhoria_geral.py` | nenhuma | E18 → `fluxo.metricas` |
| 31 | `qualidade_juiz_fila.json` | `compliance_agent/qualidade/juiz.py` | `qualidade/__main__.py`, `qualidade/estado.py`, `qualidade/sensores.py` | nenhuma | E12 `conferir:` em `fluxo.jobs` |
| 32 | `automelhoria_fila.json` | `tools/automelhoria_geral.py` | `tools/automelhoria_executor.py` | nenhuma | E17/E18 (`fluxo.jobs` tipo `manter:`) |
| 33 | `automelhoria_executor.json` | `tools/automelhoria_executor.py` | o próprio | nenhuma | E17 |
| 34 | `yoda_melhorias_fila.json` | `tools/yoda_autoauditoria.py` (inferido) | `tools/automelhoria_geral.py` | nenhuma | E17; o Yoda só lê (fora do JFN, §16.6) |
| 35 | `ronda_state.json` | `tools/ronda.py` | `tools/automelhoria_geral.py` | nenhuma | E18 `observar` |
| 36 | `sentinela_integridade_estado.json` | `tools/sentinela_integridade.py` | o próprio | nenhuma | E18 |
| 37 | `deploy_estado.json` | `tools/deploy_pos_commit.sh` | `tools/automelhoria_geral.py` | flock + atômica (`mv`) | ADR-010 (deploy): evento no `fluxo.eventos` |
| 38 | `itcampo_estado.json` | `tools/itcampo_ocr_cpu.sh` | `tools/automelhoria_geral.py` | flock | `fluxo.nos` (heartbeat do nó) |
| 39 | `.navegador_claude_guard.json` | `tools/vm_guard.py` (inferido) | o próprio | atômica | `fluxo.nos.recursos` (slot de navegador) |
| 40 | `claude_contingencia.json` | `compliance_agent/llm/contingencia.py` | consumidores de `llm/` | nenhuma | gateway de IA (ADR-005): estado do provedor no PG |
| 41 | `claude_motor_estado.json` | `compliance_agent/llm/claude_motor.py` | o próprio; inventário de qualidade | flock | ADR-005 |
| 42 | `claude_motor_uso.json` | `compliance_agent/llm/claude_motor.py` | `compliance_agent/llm/orcamento.py` | flock | ADR-005 (orçamento) |
| 43 | `claude_assinatura_uso.json` | `compliance_agent/llm/ritmo_assinatura.py` | o próprio | nenhuma | ADR-005 (trava de ritmo) |
| 44 | `claude_api_gasto.json` | `compliance_agent/llm/claude_api.py` (inferido) | `compliance_agent/qualidade/sensores.py` | flock (no leitor) | ADR-005 (livro de custo) |
| 45 | `openrouter_pago_gasto.json` | `compliance_agent/llm/openrouter_pago.py` | o próprio | atômica | ADR-005 (livro de custo) |
| 46 | `openrouter_chaves_esgotadas.json` | `compliance_agent/llm/free_llm.py` | o próprio | nenhuma | ADR-005 |
| 47 | `.llm_month_cap.json` | `compliance_agent/llm/free_llm.py` | sonda em `config/propagacao.yaml` | nenhuma | ADR-005 (teto mensal) |
| 48 | `triagem_uso.json` | `compliance_agent/llm/camada_triagem.py` | o próprio | nenhuma | ADR-005 |
| 49 | `streetview_quota.json` | `compliance_agent/verificacao_endereco.py` | o próprio | nenhuma | ADR-005 (cota de API externa) |
| 50 | `geocoding_quota.json` | `compliance_agent/fachada_doubt.py` | o próprio | nenhuma | ADR-005 |
| 51 | `quota_places.json`, `quota_geocoding.json`, `quota_addressvalidation.json` | **sem escritor no código atual** (última escrita em 07/2026) | nenhum | — | órfãos: arquivar na O9.1 |
| 52 | `pericia_refazer.json` | `compliance_agent/pericia_integral.py` (inferido) | o próprio | nenhuma | E11 `periciar:` reenfileirado |
| 53 | `sei_ficha_acervo_estado.json` | `tools/sei_ficha_acervo.py` | o próprio | atômica | E11 |
| 54 | `vm2_amostra_pendente.json` | `tools/vm2_conferencia.py` | o próprio | flock | E12 `conferir:` (amostra estratificada) |
| 55 | `vm2_amostra_sorteio.json` | `tools/vm2_conferencia.py` | o próprio | flock | E12 (semente no `payload`) |
| 56 | `cpf_fila_humana.json` | `tools/desmascarar_cpf_externo.py` | o próprio | nenhuma | fila humana em tabela com acesso controlado (dado pessoal: sai do JSON) |
| 57 | `telegram_silencio.json`, `promessas_pendentes.json`, `.bombeiros_alerta_cursor.json` | `notifications/silencio.py` (inferido), `compliance_agent/promessas.py` (atômica), `tools/bombeiros_alerta_telegram.py` | `tools/digest_diario.py`; os próprios | ver escritor | E16 `entregar:` (entrega honesta: `ok=False` quando silenciado) |

São **69 arquivos em 57 linhas**: as linhas 10, 51 e 57 juntam arquivos da mesma família. O §2 pedia ≥ 34.
Os demais `.json` de `data/` (147 no total) são caches, relatórios gerados, gabaritos ou configuração; não são
filas nem estados, e a ADR-011 trata os que estão versionados.

### 4.3 Achados da tabela

- **Duas máquinas escrevem sem trava** (linhas 4, 9 e 10). A ADR-012 resolve com o lease de `fluxo.jobs`.
- **Os sete estados de LLM** (linhas 40–48) são o mesmo domínio, com sete arquivos e três tipos de trava. O
  gateway de IA da ADR-005 vira o escritor único.
- **Três arquivos de cota são órfãos** (linha 51). Ficam declarados aqui e não são apagados agora.

## 5. Não adotar

- **"Banco único para tudo" (só PG ou só SQLite):** rejeitado.
  - O `compliance.db` de coleta bruta é a fonte que os detectores leem há meses. Migrá-lo inteiro agora não
    traz ganho medido e arrisca a paridade.
  - Ele fica como D4 até um ADR futuro mostrar ganho.
- **Replicação SQLite ↔ PG em duas vias:** rejeitada. Viola "nunca escrita nos dois lados".
- **Manter as filas em JSON com `flock` melhorado:** rejeitado. `flock` não atravessa máquinas, e as linhas 4,
  9 e 10 provam que a fila já atravessa.

## 6. Gatilhos de reavaliação

- O `compliance.db` passa de 10 GB, ou uma escrita de coleta trava leitura do painel por mais de 5 s (p95).
- O PG da VM-2 fica indisponível por mais de 1 h em 7 dias: rever o modo degradado de D1–D3.
- Um escritor não previsto nesta matriz aparece em código. A catraca da O8 deve barrar; se passar, este ADR
  está errado.
- A paridade `--comparar` da linha de base diverge depois de um corte.
