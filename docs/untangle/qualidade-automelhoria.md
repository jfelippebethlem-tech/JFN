# Untangle — qualidade, autoaprimoramento e automelhoria (registro de decisões)

| | |
|---|---|
| **Escopo** | `compliance_agent/qualidade/` (12) · `compliance_agent/autoaprimoramento/` (14) · `compliance_agent/certeza/` (8, só o que sobrou do untangle do cérebro) · `tools/automelhoria_geral.py` · `tools/automelhoria_executor.py` |
| **Data** | 20/11/2026 — worktree `agent-a17826532dc9166d3`, base `761bd35a` |
| **Opções** | Comentários = SIM (mantida medição datada, decisão do dono e porquê de workaround) · Testes = NÃO (nenhum teste mexido) |
| **Pergunta única** | "Estas peças devem mudar juntas?" |
| **Não muda** | ids de regra/violação e chaves que `/api/qualidade/conformidade` lê · juiz só pela assinatura (`backend="cli"`), fila inteira em lotes (`data/qualidade_juiz_fila.json`) · executor noturno às 01:00 com as travas do motor · crontab |

Legenda: **FEITO** (commit) · **MANTIDO** (caso especial que o sistema ainda precisa, com o motivo) · **ANOTADO**
(fora do escopo desta frente, ou exigiria decisão do dono / prova de paridade que esta frente não fez).

---

## 1. Consertos, com os problemas que cada um resolve

### 1.1 Onde a qualidade guarda o que mede: um lugar — FEITO (`364a456e`)
`qualidade/arquivos.py`: `dados()` (`JFN_DADOS`) e `gravar_json` atômico.
- `sensores.py:42` e `estado.py:28`: duas cópias de `_dados()` (a variável de ambiente escrita duas vezes).
- `.tmp` + `replace` escrito à mão 4× em `sensores.py` (`:254`, `:450`, `:626`) e de novo em `juiz._gravar_json`.

### 1.2 Os sensores com memória só regravam quando a rodada grava — FEITO (`364a456e`) · **defeito**
`Ctx.gravar`; `rodar(gravar=False)` repassa.
- `sensores.py:253–256` (`manchetes_variacao`) e `:450–452` (`alertas_base`) regravavam `qualidade_manchetes.json` e
  `qualidade_alertas.json` mesmo com `--sem-gravar`. A rodada de ensaio virava a "leitura anterior": a rodada real
  seguinte deixava de acusar a variação brusca (CST-02) e o salto de volume (COR-16) que o ensaio já tinha visto.
  Provado na impressão digital (§3): a base reescreve os dois arquivos sem gravar; o novo, nenhum.

### 1.3 O caso do vault e a manchete são lidos por uma função, e o juiz não toca em privado dos sensores — FEITO (`364a456e`)
`sensores.casos_do_vault`, `caso_alto_aberto`, `frontmatter`, `numeros`, `textos_yoda` (públicos).
- `juiz.py:162–176` repetia a leitura dos casos com `sensores._frontmatter` e `sensores._RE_GRAU_ALTO`, sem o filtro
  de `tipo` que o sensor aplica — o que o sensor cobra (COR-01 sobre 🔴 aberto) e o que o juiz julga podiam divergir.
  **Divergência deliberada**: o juiz passa a julgar só nota de `tipo` caso/investigação, como o sensor; medido no
  vault real em 20/11: 97 casos altos abertos, 0 fora desse `tipo` (nenhuma afirmação muda).
- `juiz.py:133` (`sensores._numeros`), `:238` (`sensores._textos_yoda`).

### 1.4 Máscara de CPF antes do modelo mora com os outros verificadores de CPF — FEITO (`364a456e`)
`verificadores.mascarar_cpfs`, sobre as MESMAS regex de `cpf_exposto`.
- `juiz.py:121` (`_mascarar`) tinha cópia própria das duas regex de CPF. Resultado idêntico em 25.007 textos de
  prova (aleatórios + bordas de 9–13 dígitos).

### 1.5 Sobras do juiz — FEITO (`364a456e`)
- Parser de "R$" copiado em `_de_yoda` e `_de_produtos` → `_valores_reais`.
- `{"aprovada": 0, "ressalva": 1, "reprovada": 2}` em 3 lugares (`normalizar`, `normalizar_lote` 2×) → `VEREDITOS`.
- `medir_fila` reimplementava a trava de `sensores.trava` com `fcntl` à mão → `trava(..., esperar=False)`.

### 1.6 Um mapa dos sistemas — FEITO (`364a456e`)
`regras._SISTEMAS` (id → nome no painel, nome curto no documento).
- `regras.SISTEMAS`, `estado.NOMES` e `doc._SIS`: três listas dos mesmos 11 sistemas — sistema novo exigia lembrar
  das três (o documento quebrava com `KeyError`). Nomes servidos pelo painel e documento gerado: idênticos
  (`doc.em_sincronia()` verdadeiro).
- `estado._ORDEM_SEV` repetia `regras.SEVERIDADES`.

### 1.7 Autoaprimoramento: caminhos, nomes de arquivo e a abertura do ledger num lugar — FEITO (`95f5b967`)
`config.CASA`, `config.compliance_db()`, `config.BANCO`/`config.KILL`, `registro.abrir()`.
- `REPO/"data"/"compliance.db"` montado à mão em `monitor.py:24`, `reexecucao.py:77`, `selecao.py:40`, `importar.py:217`.
- `ledger.conectar()` + `registro.preparar(con)` repetidos em 4 chamadores (`__main__` 2×, `orquestrador` 2×):
  esquecer o segundo deixa o banco sem a semente do campeão.
- `__main__ teste` lia os rótulos de treino+validação duas vezes.
- `orquestrador.relatorio` com `nivel_prova=2` literal.

### 1.8 A saúde do ledger mora no monitor; o sensor da automelhoria só traduz — FEITO (`95f5b967`)
`monitor.saude(pasta, compliance_db)` e `monitor.fora_do_ledger`.
- `automelhoria_geral.sensor_autoaprimoramento` abria `auto.db` e `KILL` pelo nome e contava "fora do ledger"
  com `nivel_prova=2` e `== 2` literais (`:486`, `:490`): mudar a escala de prova ou o nome do arquivo no
  autoaprimoramento quebrava o sensor sem aviso.

### 1.9 O que o /melhorias diz que vigia sai da tabela dos sensores — FEITO (`593f4ed5`) · **defeito**
`_SENSORES` (nome → função, rótulo); `SENSORES` e `_AREAS` derivados.
- `automelhoria_geral._AREAS` era lista à parte, parada em 13 rótulos: o resumo ao dono omitia 7 dos 20 sensores
  (qualidade, certeza, autoaprimoramento, detectores, máquinas, voz, pareceres). Mudança visível: só a linha
  "Vigio:" do `--resumo`.
- `automelhoria_executor.FILA` era segunda cópia do caminho da fila → importa de `automelhoria_geral`.

### 1.10 Achados da revisão independente (subagente só-leitura), conferidos e consertados — FEITO (`2ff692d9`)
- **defeito** `automelhoria_geral.sensor_painel:335`: QUALQUER `URLError` virava `cod = 200` ("cache frio"). Conexão
  recusada (API caída) responde em milissegundos → nenhum item. Só tempo esgotado é cache frio; provado com
  `urlopen` dublê (recusa → 3 itens "fora do ar (ConnectionRefusedError)"; timeout → 0).
- **defeito** `sensor_certeza:519`: cópia da lista de achados graves do grafo sem `derivado_nunca_rodou` e
  `despachante_parado` (`grafo.py:203` os conta) → `certeza.grafo.GRAVES`. Estado real hoje: 0 e 0 (nada muda já).
- `sensores.sensor_gasto_api:503` lia `JFN_CLAUDE_API_TETO_USD` (ninguém define); a API aplica `JFN_API_TETO_USD`
  → `claude_api.teto_usd()`. Hoje os dois valem US$ 100.
- `monitor.saude` passa a ver também `JFN_AUTOAPRIMORAMENTO_KILL=1` (como `config.morto()`).
- `automelhoria_executor:52,76`: negações de leitura e prompt com `/home/ubuntu/JFN` escrito à mão → `_REPO`/home.
- Aviso "NÃO pegou em 2 tentativas" com o 2 fixo → `MAX_TENTATIVAS`.

### 1.11 Comentários que só repetiam o código — FEITO (commit deste registro)
`estado.py` ("a mais recente do dia vence"), `juiz.py` ("o mesmo id duas vezes", "mais velho antes"). Mantidos todos
os que trazem medição datada, decisão do dono ou fato externo.

---

## 2. Casos especiais MANTIDOS

| Onde | Caso especial | Por que fica |
|---|---|---|
| `autoaprimoramento/__main__.py:37` | "tentar de novo" decidido pelo PREFIXO do texto de `claude_motor.ultimo_motivo` ("ocupado", "passou do prazo") | O motor só expõe o motivo como texto; o conserto (`ultimo_tipo`) é da frente `llm/` (já anotado em `docs/untangle/llm.md` §4.2) |
| `reexecucao.MOTOR_FORA` (global escrito pelo gerador) | sinal de parada por variável de módulo | `avaliar_processo` engole a exceção do gerador; a global é o único canal até lá. É contrato de teste (`test_autoaprimoramento_ciclo.py:428`) |
| `ledger._sem_banco` | guarda `PYTEST_CURRENT_TEST` própria | Diferente de `arquivo_estado.sob_pytest()`: aqui o teste PODE gravar se apontar diretório próprio |
| `juiz._grupo_poda` × `Afirmacao.grupo` | dois agrupamentos por prefixo de id | Medem coisas diferentes: fonte que leu (poda) × vaga reservada na fila. O histórico só guarda o id |
| `juiz.julgar` × `julgar_lote` (lote de 1 vai ao prompt individual) | dois caminhos de prompt | Reescrita do juiz de hoje (`4b9d1d39`): o prompt de 1 item é o que os vereditos vigentes julgaram; trocar invalida o cache por impressão |
| `automelhoria_geral._DISPENSADOS_DONO` | `if` por assinatura | Decisão do dono, datada |
| `executor.AREAS` inclui `dados` (SIAFE) | área que o próprio comentário diz não ser do braço | Os 2 itens de `dados` têm remédio automático; tirar muda o que o executor pega — decisão do dono |

---

## 3. Validação empírica (estado real, sem LLM, sem gravar em `data/`)

Script `empirico.py` (scratchpad): `data/` de mentira com symlink para o real e CÓPIA dos arquivos que sensores e juiz
reescrevem; payloads da API gravados uma vez e reusados; relógio congelado; ledger do autoaprimoramento copiado.
Base = `git archive 761bd35a`; novo = este worktree; rodados em sequência sobre o mesmo estado.

| Medida (estado real de 20/11, ~07:15) | Base × novo |
|---|---|
| Sensores de qualidade (`rodar(gravar=False)`): 5 violações (CST-03, CST-08, CST-14, PAD-03, SUB-02), 0 cegos — lista completa com chave, título, detalhe, severidade | **idêntico** |
| `para_automelhoria` (itens da fila única) | **idêntico** |
| Juiz: 166 candidatas (id, grupo, impressão, risco, canal), ordem da fila, plano de 43 lotes, sha1 de cada prompt de lote | **idêntico** |
| `juiz.medir_fila` (cobertura 3,0%, 161 pendentes, 43 chamadas para zerar, `pendentes_desde`) | **idêntico** |
| `estado.painel()` (o JSON de `/api/qualidade/conformidade`, menos `gerado_em`) | **idêntico** |
| Sensores da automelhoria `autoaprimoramento`, `certeza`, `detectores`; `executor.escolher` (5 itens) | **idêntico** |
| Arquivos reescritos por `sensores.rodar(gravar=False)` (por mtime) | base: `qualidade_alertas.json`, `qualidade_manchetes.json` · novo: nenhum (§1.2) |
| `automelhoria --resumo` | só a linha "Vigio:" muda (20 rótulos em vez de 13 — §1.9) |
| Prompt do executor | só o caminho da árvore (a base fixa `/home/ubuntu/JFN`; o novo usa `_REPO` — idêntico em produção) |
| Ciclo de ensaio do autoaprimoramento (cópia do ledger) + relatório; `certeza.laudos` | iguais exceto deriva do dado entre as duas rodadas (~30 min): `lex_execucao` ganhou 10 laudos (6.606 → 6.616 processos; deriva 3.167 → 3.174 laudos da semana). Candidatos, portão, fila da fonte (30, 6 aleatórios), monitor e registro de versões: iguais |

**Testes casados** (26 arquivos: `test_regra_*`, `test_autoaprimoramento_*`, `test_automelhoria_*`, `test_certeza_*`,
`test_rota_qualidade`, `test_proveniencia_manchetes`, `test_nucleo_autoaprimoramento`, `test_cerebro_vigencia`):
347 verdes na base → 347 verdes ao fim (+ `test_cerebro_ponte`, 8, usa `registro.preparar`: 355 verdes). Catracas de `except` e `test_claude_api`: 30 verdes.

GitNexus: o índice não conhece os símbolos deste worktree; impacto feito por grep do repositório inteiro
(`.py/.sh/.yaml/.js`) e revisão independente por subagente.

---

## 4. ANOTADO — não mexido aqui

| # | Problema | Onde | Por que não agora |
|---|---|---|---|
| A1 | `selecao`, `importar` importam privados `tools.lex_execucao._chave_processo` e `cruzamentos_intel._ob_paga`; `reexecucao` escreve `LX._LICOES_SOMBRA` | `selecao.py:46,91`, `importar.py:152,169,213`, `reexecucao.py:57–60` | Os donos (`lex_execucao`, `cruzamentos_intel`) são de outras frentes; precisam expor API pública |
| A2 | `importar._json` é parser de JSON à mão (≠ `parse_json_llm`) | `importar.py:43` | Trocar exige prova de paridade sobre a fila real (memória `parse-json-llm-unico-provado`) e muda o hash das versões do ledger |
| A3 | `automelhoria_executor` usa `claude_motor._trava_arq()` (privado) | `automelhoria_executor.py:118` | Frente `llm/`: o motor precisa expor a trava |
| A4 | `regras.problemas` importa `sensores` (volátil) para conferir nomes de sensor | `regras.py:107` | É a conferência do registro; import tardio, sem ciclo |
| A5 | Escala de prova com o mesmo 0/1/2 e nomes diferentes em `autoaprimoramento.config` (FRACO/RESUMO/FONTE) e `certeza.config` (ESTIMATIVA/AGREGADO/FONTE); `certeza.orquestrador.laudos` tem o dicionário de nomes à mão | `certeza/orquestrador.py:56` | Certeza foi mexida hoje pelo untangle do cérebro; unificar a escala muda o `estado.json` da certeza |
| A6 | `sensor_certeza` conhece a estrutura interna de `data/certeza/estado.json` e trata "não medido" como zero: ignora `contratos.estado == "INDISPONIVEL"`, `indisponiveis` e `risco_alto_verificado_sem_prova_primaria = None`; recalcula regressões em vez de ler `resumo`; usa `DATA/"certeza"` em vez de `config.dados()`/`ler_estado()` | `automelhoria_geral.py:495–550` | Muda o que entra na fila (itens novos "indisponível"); o mesmo conserto de 1.8 (`certeza` expõe os itens). **Próximo a fazer** |
| A7 | Nível de prova de um laudo decidido por TEXTO livre de `lex_execucao.modelo` em 3 leitores (`ledger.motor_e_nivel`, `correlacao_sei.estado_do_laudo`, `monitor.fora_do_ledger` com `LIKE '%Claude Code%'`) e 2 escritores à mão (`importar.tudo`, `tools/pericia_agentes_aplicar.py`) | ver coluna | Conserto é um módulo que escreve E lê a proveniência (ou coluna `nivel_prova`): toca `lex_execucao`, `correlacao_sei` — outras frentes |
| A8 | `ALTO = 7` × `nota_risco >= 7` literal | `tools/lex_execucao.py:525` | Frente da perícia |
| A9 | `data/compliance.db` montado à mão ~10× fora do autoaprimoramento | `automelhoria_geral` (5×), `certeza/orquestrador:106`, `certeza/__main__:75`, `sensores.py:428` | Cada pacote tem a sua raiz de dados (`JFN_DADOS`, `JFN_CERTEZA_DIR`…); um helper da casa (`compliance_agent.config`) é decisão transversal |
| A10 | Nome/chaves de `qualidade_juiz_fila.json` compartilhados só por string (juiz escreve; sensor, estado e CLI leem) | `juiz.py`, `sensores.py:558`, `estado.py:65` | Constante + leitor no juiz; o painel lê as chaves — mexer só com o painel junto |
| A11 | `config/qualidade_inventario.yaml` lido em 3 lugares; `qualidade_detectores.yaml` lido por fora de `detectores.carregar()` | `inventario.py:20`, `sensores.py:61`, `certeza/grafo.py:155,168` | `grafo` é da certeza; os testes do sensor trocam a raiz pelo `Ctx.repo` |
| A12 | Regra "motor sem efeito" em duas leituras de `aovivo/motores.yaml` | `catracas.py:184`, `inventario.py:124` | `inventario._yaml` devolve `{}` sem arquivo; a catraca LEVANTA — unificar sem perder isso |
| A13 | Status da fila (`aberto`/`REINCIDIU`/`curado`/`dispensado`) e nomes de área como strings soltas entre loop e executor; `executor.AREAS` precisa casar o `area` de `_p()` | `automelhoria_geral.py`, `automelhoria_executor.py:40,64` | Baixo risco hoje; constantes no loop importadas pelo executor |
| A14 | Executor commita o que sobrou na árvore quando a saída do modelo não traz `CONSERTO:` (o `resumo` vira os últimos 600 caracteres) | `automelhoria_executor.py:135–141` | Muda o que o executor commita — decisão do dono (hoje é "nunca apagar trabalho feito") |
| A15 | Executor depende de regra não escrita do `telegram.enviar_mensagem` (sem `chat_id` cai no filtro de silêncio) e usa `_get_chat_id` privado | `automelhoria_executor.py:164–167` | Frente das notificações |
| A16 | Ensaio do ciclo troca `JFN_AUTOAPRIMORAMENTO_DIR` para o processo inteiro (o gancho `ledger.arquivar_linha` de outro fio gravaria no `dryrun/`) e copia `"auto.db"` literal | `orquestrador.py:24–38` | O ciclo roda sozinho no processo (CLI/cron); passar a pasta explícita mexe em todas as funções que chamam `config.dados()` |
| A17 | Erros engolidos que viram "nada": tabela de OB ausente → COR-12 não roda (`sensores.py:441`); banco ausente → importação vazia (`importar._ro`); fonte do juiz que falha some da cobertura (`juiz.py:235–240,301`) | ver coluna | Cada um muda o que o painel/fila mostra; registrar a fonte que falhou na fila do juiz é o primeiro |
| A18 | `remediar` muda a fila em memória e depende de `main` regravá-la; `conciliar` também grava | `automelhoria_geral.py:705,794` | Contrato dos testes de `conciliar` (gravam e releem) |
