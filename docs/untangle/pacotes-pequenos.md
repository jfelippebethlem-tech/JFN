# Decision log — untangle dos pacotes pequenos de `compliance_agent/` (20/11/2026)

Escopo: `emendas`, `database`, `contratos`, `analysis`, `lai`, `auditoria`, `notifications`, `enxame`,
`providers`, `reports` (só código `.py`). Escolhas do dono: **Comentários = sim** (fica medição datada, decisão
do dono, norma, porquê de workaround), **Testes = não**. Regras da casa acima da skill: títulos de alerta, chaves
lidas pelo painel/rotas e esquema de banco (`database/models`) não mudam; OB/pagamento só por
`cruzamentos_intel._ob_paga`; fontes únicas já existentes (`cpf_cnpj`, `credor_institucional`, `esfera_orgao`,
`limites_dispensa`, `limites_habilitacao`) são usadas, não recriadas.

**`territorio/` — fora desta passada** (o dono pediu mudança de regra no território — tirar "sede do órgão" do
cálculo, contar repasses do Estado a municípios e obras de escola/posto como investimento — e outro agente faz).
Os problemas que encontrei lá estão na seção 9, só anotados.

Formato igual a `rules.md`/`padroes.md`: o fix fica acima dos problemas que resolve. `[feito]` = aplicado nesta
passada; `[pendente]` = precisa de decisão do dono ou é redesenho; `[fora do escopo]` = anotado só.

## 0. Prova de equivalência

**Testes casados** (35 arquivos: emendas, contratos, enxame, lai, analysis, providers, telegram/silêncio, offline,
FTS/WAL, catracas, smoke de imports): antes **996 passed, 1 skipped**; depois **992 passed, 1 skipped** — os 4 a
menos são os parâmetros do smoke de imports dos 4 módulos apagados (seção 7).

**Validação empírica, só leitura, sobre os dados reais** (`data/compliance.db`, `data/pcrj.db`, modo `ro`): o mesmo
roteiro rodado com o código de antes (`6f333676`) e o de depois, saídas comparadas chave a chave. LLM, RAG e HTTP
substituídos por falsos (nada saiu para a rede; Telegram com cliente falso).

| Superfície | Universo | Resultado |
|---|---|---|
| `emendas.pericia` D1–D6 (D4 com avaliador falso) | base inteira | **igual** |
| `contratos`: dossiê + pensamentos + parecer/render | 1.301 contratos com aditivo (parecer nos 400 primeiros) | dossiês **iguais**; achados iguais em **1.300**; o parecer só ganha a chave nova `fornecedor_documento` |
| `contratos.estado.montar_dossie_tcerj` | 120 registros do SIGA | **igual** |
| `lai` fatos + requerimento | 14 alvos (processos, CNPJs, nome, inexistente) | **igual** |
| `database.fts` (3 índices) | 5 termos, inclusive um que quebra o FTS | **igual** |
| `reports.html_report` | favorecido "MGS" | **igual** |
| Telegram (`enviar_*`) | 6 cenários com cliente falso | **igual** |
| `anomaly_detector` fracionamento | 24.055 OB de jan–fev/2025 | **muda (defeito, seção 4)**: 775 → 466 alertas — saem os 240 das faixas "concorrência" sem base legal; "dispensa obras" 249 → 191 e "dispensa serviços" 286 → 275 pelos limites corretos de 2025 |
| `auditar_fornecedor` relatório | entrada sintética | **muda (defeito, seção 1)**: `1,234,567.89` → `1.234.567,89` |

O único contrato cujo achado mudou (`42498733000148-2-000341/2026`, acréscimo de 25,03% num objeto com
"equipamento" que não é reforma) é o efeito pretendido da seção 2.1: dos 152 contratos que trocaram de teto, só ele
tinha acréscimo entre 25% e 50%.

Sem índice GitNexus no worktree: o impacto de cada símbolo tocado foi conferido por `grep` em `compliance_agent/`,
`tools/`, `rotas/`, `server.py`, `tests/`, `*.sh` e `config/`.

## 1. Formatação de moeda e dígitos de documento pelas fontes únicas  `[feito — 8dda3632]`

- `reporting.intel_base.moeda` é o formatador BR da casa; `cpf_cnpj.digitos` é o "só dígitos".
  - `_brl` copiado em `emendas/pericia.py:32`, `contratos/parecer.py:17`, `contratos/thoughts.py:52` e
    `reports/html_report.py:26` (este com o "R$ " na frente) — mesma expressão, quatro cópias.
  - `auditoria/auditar_fornecedor._f` formatava no padrão americano (`1,234,567.89`) o relatório `.md` de
    auditoria de fornecedor — contra a regra 1 da casa (R$ com milhar `.` e decimal `,`). **Defeito: corrigido**
    (a saída muda de `1,234,567.89` para `1.234.567,89`).
  - `auditar_fornecedor._f` ficou só repassando para `moeda` → apagado.
  - `_digitos` copiado em `contratos/estado.py`, `providers/registry_providers.py`, `links_providers.py`,
    `eleitoral_providers.py`.
  - Mantido de propósito: `lai/requerimento._moeda` devolve `"R$ —"` para valor inválido (INDISPONÍVEL ≠ 0);
    `moeda` devolveria `0,00`. Passa a ser `"R$ " + moeda(v)` só para valor numérico.

## 2. Contratos: um dossiê, uma régua de veredito  `[feito — c5ddba51, ec55ac2c]`

- `contratos/estado.montar_dossie_tcerj` monta "o MESMO dossiê" da câmara municipal — e copiava
  `_tem_tabela` e `_sinais_fornecedor` de `contratos/dossie.py` linha a linha (com o mesmo comentário). Mudar o
  sinal (ex.: vigência da sanção) exigia lembrar das duas. Agora o estadual chama o de `dossie`
  (`com_rede=True`, que era o comportamento fixo da cópia).
- `contratos/dossie.RAIZ_PREFEITURA_RIO = "42498733"` era cópia de `esfera_orgao.RAIZ_MUNICIPIO_RIO` → usa a
  fonte única.
- O parecer e o enxame decidem a mesma faixa com números escritos duas vezes: `parecer._conclusao` (≥ 7
  "indício de irregularidade", ≥ 4 "diligência") e `enxame/orquestrador._veredito` (≥ `SCORE_DIRECIONAMENTO`
  "direcionamento", ≥ 4 "indício fraco"); e `render_parecer_ctx` ainda testava `score >= 7` para a cor.
  Agora `orquestrador.veredito(score)` é a régua pública (com `SCORE_INDICIO_FRACO = 4` nomeado) e o parecer
  só traduz o rótulo; a cor sai da conclusão. Saída igual nos 11 escores (0–10).
- `sinais_fornecedor`/`tem_tabela` perdem o `_`: viraram API entre `dossie` e `estado`.
- **Defeito (conferência por subagente):** a memória do enxame nunca era achada no parecer de contratos —
  `gravar_e_aprender` gravava com a chave `"NOME (doc)"[:60]` e `_deliberar_achado` consultava pelo documento.
  Agora grava pelo documento (o parecer ganha a chave `fornecedor_documento`), como `reporting/ficha7` já faz.
  As linhas antigas de `memoria_aprendizado` (categoria `contrato_*`) ficam com a chave velha — órfãs.

### 2.1 Teto de 50% do art. 125 só para reforma  `[feito — defeito — 2722bda7]`

- `thoughts.t_aditivo` decidia o teto com regex própria `reforma|edifício|equipamento`: "equipamento" ou
  "edifício" soltos davam 50%. Medido em 20/11/2026: **152 de 1.301** contratos com aditivo (limpeza, telecom,
  engenharia clínica…) mudam de teto. Agora `limites_aditivo.tipo_objeto` (reforma DE edifício/prédio/imóvel/
  equipamento/cobertura) → `teto_acrescimo`, a régua única.
- Código morto em `contratos/thoughts.py`: `_e_acrescimo_de_valor` e `_RX_SEM_ACRESCIMO` (a regra foi para
  `limites_aditivo.classificar_natureza` em julho; ninguém chama) → apagados.

## 3. LAI: o prazo de 20 dias num lugar  `[feito — 016a9725, ec55ac2c]`

- `lai/registro.atualizar(prazo_dias=20)` e `lai/requerimento.DESTINATARIOS[...]["prazo_dias"] = 20` (duas
  vezes) — o mesmo prazo do art. 11, §1º da Lei 12.527/2011 em três literais. Agora `registro.PRAZO_LAI_DIAS`;
  a prorrogação de 10 dias (§2º), literal no texto do pedido, vira `registro.PRORROGACAO_LAI_DIAS`.

## 4. Fracionamento por limite: a tabela de dispensa é a da casa  `[feito — defeito — f3a6a51e]`

- `analysis/anomaly_detector.detectar_fracionamento_threshold` tinha a própria tabela `LIMITES`, contra a regra
  escrita em `limites_dispensa.py` ("NUNCA duplicar esta tabela em detector"), e errada:
  - `dispensa_servicos = 50.000` é o valor de 2021 (2025 = R$ 62.725,59; 2026 = R$ 65.492,11);
  - `dispensa_obras = 30.000` "art. 75, I" — nunca foi esse valor (art. 75, I: R$ 100.000 em 2021; R$ 125.451,15
    em 2025);
  - `concorrencia_peq/media/alta` (165 mil, 1,65 mi, 3,3 mi) não existem na Lei 14.133/2021 (não há modalidade
    por valor) — sobra das faixas da Lei 8.666.
  Agora: limite de compras e de obras do ANO da OB por `limites_dispensa.limite_dispensa`; as três faixas sem
  base legal saem. Formato do título igual. Efeito medido na seção 0.

## 5. FTS: uma consulta, três índices  `[feito — 79a7f40a]`

- `database/fts.buscar_contratos_fts/buscar_doerj_fts/buscar_alertas_fts`: o mesmo esqueleto (conexão, `MATCH`,
  `ORDER BY rank`, log de falha, fechar) três vezes. Agora `_buscar(tabela, sql, query, limite, linha)`; as chaves
  devolvidas (lidas pelas rotas) não mudam.

## 6. Telegram: o prólogo de envio num lugar  `[feito — b4fd28cc]`

- `enviar_mensagem` e `enviar_arquivo` repetiam: silêncio do aviso automático (decisão do dono 17/11/2026) →
  resolver chat → resolver token → erro "não configurado". Agora `_destino(chat_id, resumo)`; o resto igual.
  Validado com cliente HTTP falso (nada foi enviado).

## 7. Sobra: módulos sem nenhum chamador (nem teste)  `[feito — b1c08b05, ec55ac2c]`

- `database/cache.py` (cache em `data/api_cache.db` por caminho relativo ao cwd; o arquivo nem existe).
- `reports/charts.py` (gráficos PNG) — e com ele o bloco "4. GRÁFICOS" de `reports/pdf.py`, que fazia `glob` em
  `reports/charts/` (relativo ao cwd, diretório que nada mais escreve), a classe vazia `RelatorioCompliance` e
  `gerar_relatorio_mensal` (sem chamador).
- `providers/cadastro_pf_providers.py` (nome→CPF por bureau PAGO — o dono vetou bureau pago, `tasks/todo.md`).
- `notifications/telegram.enviar_alerta_urgente` (zero chamadores).
- `auditoria/tfe_fornecedor.py`: cópia quase literal de `auditar_fornecedor.py` (mesma aba CDP, mesma consulta
  TFE, mesmas regex) com agregação divergente; o documentado (`PASSO-A-PASSO.md`, `AMBIENTE.md`) é o
  `auditar_fornecedor`.

### 7.1 Defeitos da conferência por subagente  `[feito — ec55ac2c]`

- `providers/sanctions_providers.PortalTransparenciaCEIS.consultar`: sem CNPJ a chamada ao CEIS ia SEM filtro —
  `/api/idoneidade?nome=X` devolvia `ok=True` com a 1ª página de sanções de qualquer empresa. Agora INDISPONÍVEL
  com o motivo; CNPJ por `cpf_cnpj.digitos`.
- `emendas/pericia` D5: a evidência gravava `match_tipo: "CPF"` também quando a pessoa casou por CNPJ.

## 8. Pendente — pede decisão do dono ou é redesenho  `[pendente]`

- **Achados da conferência que mudam saída e pedem régua/decisão** (não aplicados):
  - `contratos/dossie.sinais_fornecedor` devolve TEXTO ("fornecedor sancionado (…)") e `thoughts` decide risco 8 e
    o sinal de cartel do Lex procurando as palavras "sancionado"/"rede" nele; a sanção não passa por vigência,
    `sancao_impeditiva` nem `sancao_abrangencia` (que a D3 das emendas usa). Redesenho: sinais estruturados.
  - `thoughts._RX_PRORROGA` conta `repactua` como prorrogação (para `limites_aditivo` é reequilíbrio) — usar
    `classificar_natureza(...) == "prazo"`.
  - `providers/eleitoral_providers.doador_contrato` casa sócio × doador só pelo nome, contra a régua
    `identidade_pessoa.chave_qsa` (19/11/2026) que a D5 já usa.
  - D5 compara `camara.norm_nome` (mantém pontuação) com `socios_receita.nome_norm` (gerado por
    `identidade_pessoa.normalizar_nome`): nome com hífen/apóstrofo nunca casa.
  - `emendas/pericia._ENTE_PUBLICO` (regex no nome) × `credor_institucional.institucional` (natureza da Receita).
  - D4 abre `get_session()` (banco padrão) enquanto os outros detectores usam o `con` recebido, e roda
    `create_all` a cada CNPJ; D5 guarda `cobertura`/`descartes` como atributo da função (estado global entre
    corridas).
  - `contratos/estado.contratos_dos_seis`: `limite_por_orgao * 6` limita o total, não cada órgão.
  - `contratos/dossie._itens_default` e `auditar_fornecedor.consulta_tfe` engolem a falha e devolvem `[]`
    ("PNCP fora do ar" parece "sem itens"; TFE ilegível vira "0 empenhos — R$ 0,00").
  - `analysis/anomaly_detector` imprime `favorecido_cpf` inteiro em título/descrição e valores `:,.0f`
    (padrão americano) em títulos — títulos de alerta não mudam nesta passada; o módulo nunca gerou alerta.
  - `enxame/lentes._TETOS_LEGAIS` repete 10%/50% de `limites_habilitacao` no prompt (mudar o prompt muda voto).
  - `database/migrations/003` cria a tabela em `get_engine()` (banco padrão), não no da sessão;
    `migrations/002` tem taxonomia de categoria própria (≠ `reports/categorizar`) — migração aplicada, congelada.
  - Caminhos repetidos: `~/shared-brain/sei_pcrj_prioridade.txt` (`lai/gerar`, `deploy/vm2/refresh_fila_prio.py`,
    `tools/pcrj_saude.py`); `data/sei_cache` calculado de três jeitos em `auditoria/` (um ignora `JFN_DATA_DIR`);
    chave/URL do Portal da Transparência em `emendas/coletor` e `providers/sanctions_providers` (este ignora
    `TRANSPARENCIA_API_KEY`).
  - Imports de privado restantes: `database.models._resolver_db` (fts + 7 módulos fora do escopo);
    `emendas` (`camara._HEADERS`, `coletor._BASE/_chave`) — pedem um `emendas/http.py` público; três políticas de
    nova tentativa HTTP no mesmo pacote (`coletor` repete sem limite em 429/transporte).
  - "Reais em texto → float" copiado em `emendas/coletor.parse_brl`, `auditar_fornecedor._valor`,
    `siafe_contratos`, `eleitoral_providers`, `migrations/001` — sem fonte pública única hoje.
  - Sobra com teste: `analysis/curva_abc` (só os testes usam); `thoughts.t_execucao_financeira` (sempre `[]`,
    documentada como "não avaliável").

- **OB do espelho TFE fora da régua `_ob_paga`** (regra "OB → SIAFE, nunca o espelho TFE"):
  `analysis/benford.benford_ob` (servido em `/api/anomalias` junto com `anomalias.top_anomalias`, que lê a
  MESMA tabela — trocar só um descasaria as duas populações da resposta), `analysis/anomaly_detector` e
  `analysis/graph_analyzer` (via `OrdemBancaria` do SQLAlchemy, rodados por `scheduler.py`) e
  `reports/html_report` (soma `ordens_bancarias` sem filtro de paga). Migrar muda número exibido.
- **`analysis/graph_analyzer` nunca acerta e, se acertar, viola LGPD**: o sócio vira nó `PJ:{empresa_id}` e o
  favorecido da OB `PJ:{cnpj}` — o "triângulo servidor-sócio-UG" nunca fecha; a descrição põe o CPF inteiro
  (`PF:{cpf}`) e afirma "Configura nepotismo" (acusação, não indício). Zero alertas desses tipos no banco.
  Consertar = redesenho do detector (ou apagar).
- **Bot de comandos do Telegram (~950 linhas, `notifications/telegram.py` de `obter_atualizacoes` a
  `loop_comandos`)**: declarado desativado desde 06/06 (disputa o token com o gateway do Yoda); só é alcançável
  por `iniciar.sh` → `scheduler --loop`. Apagar exige mexer em `scheduler.py` e em `nucleo/telegram_nucleo`.
- **`contratos/estado.py` construído, testado, nunca rodado** (regra 8): sem chamador fora de `tests/`.
- **`reports/html_report.py` é um segundo produto de relatório** fora de `reporting/inteligencia.py`, com régua
  P×I própria (R01–R05) e rótulos ALTO/MÉDIO-ALTO; documentado em `docs/JFN-PIPELINE-OBS.md`. Aposentar ou ligar
  ao produto da casa é decisão do dono.
- `reports/categorizar.UG_NOMES`: tabela à mão de UG → nome (ex.: `"270042": "ITERJ"`, enquanto a casa usa
  UG `133100` para o ITERJ — a dupla numeração de UG); deveria vir do índice de UG do SIAFE.
- `analysis/anomaly_detector` e `graph_analyzer` gravam alerta com o mesmo bloco "dedup por título"
  (evidências como `str(dict)` num, JSON no outro), fora de `alertas_persistencia.gravar`.
- Caminho do `compliance.db` escrito em 185 arquivos; nestes pacotes: `emendas/db._DB_PADRAO` (de fato a fonte
  de `editais/db` e `collectors/tcerj_licitantes`, importado como privado), `database/models.DB_PATH`,
  `database/guarda_wal._DB_PADRAO`, `analysis/benford`, `reports/html_report` (este respeita `JFN_DATA_DIR`, os
  outros não). Unificar é passada de repositório inteiro.
- Status do dia ALTA/MÉDIA/NORMAL calculado duas vezes (`reports/pdf.gerar_relatorio_diario` e
  `notifications/telegram.enviar_resumo_diario`); contagem por severidade também em `reports/text_report`.
- `emendas/pericia._brl/_sev/_achado` são o mesmo contrato de `pcrj/pericia_gastos` (já registrado em `pcrj.md`).

## 9. Fora desta passada / fora do escopo (anotado, não mexido)

- **`territorio/`** (ver topo). Achados para quem pegar: a versão do motor `"12"` escrita em quatro lugares
  (`api._VERSAO`, `atribui_estado._pagos_guardados`, o `por_meta("estado_versao", "12")` e o `b"12"` de
  `_versao_regras`); `GRAUS` em `agrega` e em `atribui_estado`; `_iso` copiado em `atribui_pcrj`;
  `"3304557"` literal em `atribui_pcrj.unidades_saude` (é `geo.RIO`); `_digitos` própria; `api._doc` mascara
  CPF no formato D1–D3+DV (a pendência PAD-04 de `nucleo-knowledge-osint.md`); `esfera_unidade` é um
  classificador de esfera por nome paralelo a `esfera_orgao`.
- **Emendas federais**: `emendas/` coleta emendas da União (Portal da Transparência, Transferegov, Câmara) com
  recorte autor-RJ/destino-RJ; o escopo da casa é só o RJ. Nada apagado — anotado para o dono.
- `auditoria/sei_auditor.py` guarda um caminho Windows pessoal (`C:\Users\...\hermes\.env`) e o órgão `"71"`
  (ITERJ) fixo; `auditoria/siafe_contratos.py` é roteiro Playwright do SIAFE (não mexido).
- `enxame` importa `SCORE_DIRECIONAMENTO` de `editais/db` (já registrado em `editais.md`).
