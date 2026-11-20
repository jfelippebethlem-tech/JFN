# Decision log — untangle de `nucleo/`, `knowledge/` e `osint/` (20/11/2026)

Escopo: `compliance_agent/nucleo/` (17), `compliance_agent/knowledge/` (17: base legal, catálogo de vícios,
jurisprudência) e `compliance_agent/osint/` (16: série societária, beneficiário final, contato compartilhado).
Escolhas do dono: **Comentários = sim** (saem só os que repetem o código; medição datada, decisão do dono e
norma ficam), **Testes = não**. Regras da casa acima da skill: constante normativa e citação em fonte única,
CPF mascarado, comportamento igual salvo defeito provado, validação empírica sobre dado real (só leitura).
**Nenhuma citação jurídica foi criada, alterada ou removida** — o conteúdo das bases curadas é decisão do dono.

Formato igual a `rules.md`: o fix fica acima dos problemas que resolve. `[feito]` = aplicado nesta passada;
`[pendente]` = precisa de decisão do dono ou muda número/saída; `[fora do escopo]` = só anotado.

Prova (harnesses só-leitura em scratch, código de antes = `git archive 761bd35a`, rodado contra
`data/compliance.db`, `data/tcu_juris.db` e `data/receita_estab.db` reais):
- knowledge: 467 chaves (catálogo inteiro; tipicidade e moldura por vício/fase; base legal e jurisprudência por
  tipo de alerta; os 15 tipos do INDICE_CLAUSULA; as 10 súmulas; os 38 acórdãos contra o índice real do TCU;
  standard × grau × famílias; corpus/golden sobre o acervo de 17.510 enunciados) — **antes = depois**.
- validadores de CPF/CNPJ: as 9 cópias antigas (extraídas por AST) × a fonte única, sobre todo documento
  distinto do banco (credor SIAFE, favorecido TFE, empresas) + 400 mil sintéticos — ver §1.
- nucleo: `periciar_ob` sobre 90 OB SIAFE contabilizadas (15 por exercício 2021–2026, faixa dos tetos) +
  `periciar_contrato` sobre os 41 contratos, memória pericial numa cópia — ver §3.
- osint: 25 credores PJ reais do SIAFE 2025 com QSA (parentesco, interposição, beneficiário final, contato
  compartilhado, série societária, marca) — ver §5.

## 1. Uma fonte para dígito verificador de CPF/CNPJ: `compliance_agent/cpf_cnpj.py`  `[feito]`

- `cpf_cnpj` (só `re`): `digitos`, `cnpj_valido`, `cpf_valido` — pontuação ignorada, vazio/`None` e dígito
  repetido inválidos. `nucleo/dossie` e `qualidade/verificadores` reexportam os nomes (testes não mudam).
  - O módulo 11 do CNPJ estava escrito em `nucleo/dossie`, `qualidade/catracas`, `sei/cotacoes_acervo`,
    `padroes/compra_fora_do_siafe` (`cnpj_ok`), `processo_360` (`_cnpj_valido`), `anomalias` (`_cnpj_valido`)
    e `cerebro_fts`; o do CPF em `nucleo/dossie` e `qualidade/verificadores`.
  - As cópias tinham bordas diferentes (aceitar pontuação, `None`, exigir `isdigit`). Cada chamador recebe
    o que já recebia: `cotacoes_acervo` e `processo_360` só passam 14 dígitos de regex; `verificadores` só
    11 dígitos; os demais passam texto cru — e a fonte única tira a pontuação como `dossie`/`catracas`/
    `compra_fora_do_siafe` já faziam.
  - `anomalias._cnpj_valido` fica como regra PRÓPRIA da quarentena (o que não tem 14 dígitos "não barra") e
    delega o dígito à fonte única.
  - `nucleo/adaptador_db._digits` → `cpf_cnpj.digitos`.
- **Exceção mantida:** `cerebro_fts.cnpj_valido` continua cópia — o módulo declara que não importa nada do JFN
  porque roda igual nas duas máquinas (vm1/vm2).
- **Ainda fora:** `rodizio_grafo._cnpj_dv_ok` e `tools/lentes_pcrj_execucao._dv_cnpj_ok` (achados na revisão,
  não medidos) — próximos a apontar para `cpf_cnpj`.
- Paridade: 138.651 documentos distintos do banco (133.927 formas só-dígito) + 400.007 sintéticos (CPF e CNPJ
  aleatórios, `None`, vazio, repetidos, formatados): **0 divergências** nas 8 cópias substituídas, exceto
  `qualidade/catracas` com `None` (antes `TypeError`, agora `False`) — o chamador só passa casamento de regex.

## 2. knowledge: uma régua de grau, uma porta para o acervo do TCU, citação de cláusula conferida  `[feito]`

- `standard_prova.FORCA_GRAU` (A..E → força) é a única; `subsuncao._FORCA` era cópia ("herda a régua em vez de
  criar outra", dizia o comentário, ao lado da cópia).
- `corpus_veredito` abre o acervo por `tcu_juris_index.abrir`.
  - `corpus_veredito.DB_PADRAO = Path("data/tcu_juris.db")` era relativo ao cwd e ignorava
    `JFN_TCU_JURIS_DB`; a outra definição (`tcu_juris_index.DB_PADRAO`) usa a variável e `~/JFN/data`.
    **Defeito:** rodado fora da raiz do repositório, `cobertura()` dizia `indice_ausente` e `iterar_casos()`
    devolvia 0 casos (medido); pela porta única, 1.530 casos, igual ao de dentro da raiz.
- `catalogo_vicios.validar()` confere também os acórdãos e as súmulas do `INDICE_CLAUSULA` que o catálogo aponta.
  - `jurisprudencia.fundamentar_clausula` descarta CALADO o acórdão que não resolve em `TODOS_ACORDAOS` (um
    número do índice e o acervo curado mudam separados). Hoje todos resolvem; o `validar()` (já travado por
    `tests/test_catalogo_vicios.py`) passa a acusar a divergência. `_acordao_por_numero` → `acordao_por_numero`.
- Apagado o que não tem chamador nenhum (nem teste): `casos_rj.CASOS_POR_ID`, `CASOS_POR_STATUS`,
  `TODOS_TERMOS_CASOS`; `fraudes_licitacao.FRAUDES_POR_CATEGORIA`; `pattern_engine.enriquecer_alerta`;
  `moldura_juridica.fases_disponiveis`; comentários que repetiam o código em `pattern_engine`.

## 3. nucleo: o teto de dispensa é o do exercício da contratação; a referência de preço é a da categoria  `[feito]`

- `indicadores._teto_dispensa(c, pid)`: `limite_dispensa(c.data.year, tipo)` (fonte única `limites_dispensa`),
  limitado por cima pelo parâmetro (que, sendo "lei", só endurece por override). Usado por IND-FRAC-01,
  IND-DIR-01 e IND-LIM-01.
  - **Defeito:** `parametros._teto_corrente` congela `date.today().year` na importação; uma OB de 2022 era
    medida contra o teto de 2026 (R$ 65.492,11 em vez de R$ 54.020,41), e o caso-ouro de `avaliacao` (59.900,00
    em 2024) só disparava porque 90% do teto de 2026 ainda o alcança — um decreto de 2027 o derrubaria.
- `adaptador_db._referencia_categoria` filtra os contratos pela categoria do objeto.
  - **Defeito:** a consulta trazia TODOS os contratos; `categoria` só servia para não estar vazia. O IND-SUP-01
    comparava cada contrato com a mediana da base inteira.
- `ciclo._data_siafe` → `dossie.para_data` (mesmo `dd/mm/aaaa`; a outra cópia de parser de data). Na edição o
  comentário engoliu a linha `observacao=` (OB do ciclo sem objeto); a revisão independente achou e 6fee429d
  corrigiu — o harness rerodado deu o mesmo resultado.
- Sem chamador nenhum, apagados: `adaptador_db.periciar_top_obs` (ainda lia o espelho TFE, contra a regra "OB →
  SIAFE"), `nucleo.diagnostico_parametros`, `grounding.ancorar_muitos`, `telegram_nucleo.AJUDA_NUCLEO`.
  LEIAME aponta a varredura para `ciclo.py`.
- Comentários que repetiam o código (dossie, extracao_robusta, scoring, parametros, indicadores,
  autoaprimoramento, memoria_pericial). O de `aprendizado._IND_PARAMS` dizia "mesma lista que cada indicador
  declara" e não é: são só os calibráveis (os de origem "lei" ficam fora) — reescrito.
- Medição (131 laudos): IND-SUP-01 14 → 14, IND-SIT-01 1 → 1, classes de risco iguais (116 baixo, 15 alto);
  **IND-LIM-01 13 → 15, em 20 OB que trocaram de lado** — 9 saem (ex.: OB de 2021 de R$ 119.403,60 caía na
  faixa de 90–100% do teto de obras de 2026, mas está acima do teto de obras de 2021, R$ 100.000,00; OB de 2025
  de R$ 64.472,00 passa do teto de compras de 2025, R$ 62.725,59) e 11 entram (ex.: OB de 2022 de R$ 53.589,14 é
  99% do teto de compras de 2022, R$ 54.020,41, e ficava abaixo da faixa de 2026). Nenhum laudo mudou de classe.

## 4. osint: um normalizador de nome para a série societária; rótulo mascarado no grafo  `[feito]`

- `historico_societario.nome_norm` (sem acento, maiúsculas, espaços simples) é a régua da coluna `nome_norm`; o
  escritor (`tools/socios_dump_sweep._norm`, também usado por `tools/socios_serie_historica`) passa a importá-la.
  - **Defeito:** a consulta (`vinculo_na_data`, `historico_do_socio`) usava `_norm_nome`, que MANTINHA o acento,
    contra a coluna gravada sem acento (medido: 0 de 2.561.657 linhas de `socio_snapshot` com caractere não-ASCII).
    "JOSÉ" respondia NAO para quem é sócio.
- `GrafoVinculos.rotulo(no)` e `vinculos.chave_publica(no)`: toda saída (`caminho`, `narrar`,
  `beneficiario_final` — inclusive o campo `no` das pessoas —, ciclos, cadeias) passa por eles; nó `pf:` sem
  rótulo sai com o CPF mascarado. O grafo interno segue com a chave íntegra.
  - **Defeito LGPD:** `self.rotulos.get(no, no)` devolvia a CHAVE quando faltava rótulo, e a chave `pf:` de quem
    entra com documento íntegro (`tools/colher_vm2_grafo`) é o CPF inteiro. A docstring prometia
    `mascarar=True`, parâmetro que não existe — corrigida.
- `parentesco.mascarar` (cópia literal de `vinculos.mascarar_cpf`, zero chamadores) apagada.
- `grupo_economico.HHI_CONCENTRADO` importa de `editais/screens_participacao` (o comentário já dizia "o mesmo
  piso"; eram dois literais).
- Medição (25 credores PJ do SIAFE 2025 com QSA, 321 chaves): parentesco, interposição, beneficiário final do
  CNPJ, contato compartilhado, marca e `vinculo_na_data`/`historico_do_socio` com o nome como gravado — **iguais**.
  Mudaram só as 60 chaves que provam os defeitos: os 58 sócios consultados com o nome acentuado (como vem num
  documento) passam de NAO para SIM; e o grafo-teste com nó `pf:` de documento íntegro sem rótulo deixa de pôr o
  CPF em claro em `caminho.narrativa`, `passos` e `beneficiario_final.pessoas` (2 chaves).

## 5. Pendente — muda saída, pede decisão do dono ou é redesenho  `[pendente]`

- **Máscara de CPF em dois formatos que, juntos, revelam o CPF.** PAD-04 (`config/qualidade_regras.yaml`) manda
  `***.123.456-**` (D4–D9) — é o de `qualidade/verificadores`, `padroes/_comum`, `triagem_alertas`,
  `reporting/intel_base.fmt_doc`. `osint/vinculos.mascarar_cpf` (usada por `governo_couto`, `comissao_orcamento`,
  `proveniencia_manchetes`) e `pericia_contabil.mascarar_doc` mostram `123.***.***-01` (D1–D3 + DV): o mesmo CPF
  exibido pelos dois formatos fica inteiro. Unificar muda texto já exibido e expectativas de teste
  (`test_pericia_contabil`, `test_territorio`, `test_osint_vinculos`) — Testes = não; decisão do dono.
- **Módulos construídos e testados que nada em produção chama** (regra 8 da casa): `osint/timeline`,
  `osint/qsa_certame` (e por ele `osint/direcionamento_consumado`), `knowledge/doutrina`, `knowledge/subsuncao`
  (só o hash do prompt em `nucleo/prompt_versao`), `nucleo/autoconsistencia`. Apagar leva o teste junto (Testes =
  não); ligar é decisão de produto. `qsa_certame` ainda rotula o documento mascarado da Receita como `cpf` e o
  `direcionamento_consumado` o usa como `pf:<6 dígitos>` com força 0,95 (funde homônimos) — se for ligado, isso
  precisa mudar antes.
- **Bases curadas com número que o código não confere.** Os 10 acórdãos TCE-RJ no formato "N.NNN/AAAA — Pleno"
  (`1.234/2021`, `2.891/2022`, `5.102/2023`, `3.445/2022`, `7.801/2023`, `4.222/2023`, `6.330/2021`, `8.100/2024`,
  `1.980/2022`, `9.244/2024`) não são verificáveis offline (o índice é só do TCU) e destoam da numeração real do
  TCE-RJ que a própria base traz nos outros 5 (`25279/2022 — PLENV`, `125132/2022 — PLENV`…). Os 23 do TCU
  resolvem no acervo oficial (15 `confirmado`, 8 `confirmado_acervo`). `contexto_jurisprudencial_para_prompt`
  repete números à mão (`TCE-RJ 1.234/2021; TCU 2.470/2008`…) em vez de derivar de `TODOS_ACORDAOS`. Conferir
  em fonte primária e decidir — não se mexe em citação sem o dono.
- **Dispositivo citado como texto livre em quatro bases** (`catalogo_vicios.dispositivos`, `INDICE_CLAUSULA`,
  `fraudes_licitacao.base_legal`, `doutrina.dispositivos`) contra `base_legal.DISPOSITIVOS` com 24 artigos:
  61 de 67 dispositivos do catálogo/índice não resolvem pela regra de `subsuncao._verificar_norma` (grafia
  "art. 75, II" × "art. 75 II", "8.666/93" × "8.666/1993", e artigos que a base curada não tem: 105–111, 124–126…).
  Dar uma chave canônica ao dispositivo é a correção, mas é curadoria jurídica.
- `nucleo/indicadores._aditivo_excessivo` aplica 25% também a reforma (50% no art. 125) e não exclui reajuste;
  `limites_aditivo.estouro/tipo_objeto` já fazem isso — trocar muda disparo.
- `nucleo/parametros.bdi_limite` (nenhum indicador lê; o loop de autoaprimoramento o perturba à toa) e
  `teto_remuneratorio_rj` (cópia de `acima_do_teto.TETO_CF_37_XI`; um teste o usa como exemplo de "lei").
- Referência da perícia (`ob:`, `ct:`, `siafe:<ob>:<ug>:<ex>`) montada em `adaptador_db`, `ciclo`, `telegram_nucleo`
  e lida por regex em `telegram_nucleo`: `/veredito` e `/promover` só aceitam `ob:`/`ct:`, então a perícia do
  ciclo diário (chave `siafe:`) não se confirma pelo número da OB.
- `memoria_pericial._conectar` e o SQL cru sobre `pericias` usados por `ciclo` e `autoaprimoramento`;
  `adaptador_db._tem_sancao_vigente` usado por `empresa_fantasma` (e, falhando, responde "não sancionado" sem
  rastro); `telegram_nucleo._sessao` usado por `cruzamentos_intel`.
- Arquivos de estado corrompidos lidos como `{}`/`[]` e depois sobrescritos (`aprendizado`, `parametros`,
  `avaliacao`, `autoaprimoramento`): perde histórico calado.
- `osint/contato_compartilhado`: `telefone2` é procurado só na coluna `telefone1` (o vizinho que cadastrou o
  número em `telefone2` não aparece). Consertar exige índice em `receita_estab.estabelecimentos(telefone2)` —
  sem ele a consulta varre 6 milhões de linhas por empresa.
- `osint/qsa_certame_municipal.cruzar_certames(limite=)` só sai do laço de dentro: a lista passa do limite.
  Truncar direito muda `n_certames_com_achado`/`taxa_de_achado_pct` (calculados da lista) — decidir se o limite
  corta a lista ou o cálculo.
- `osint/interposicao` casa `socios_reverso.nome_norm` gravado por `tools/socios_reverso_build` sem tirar
  pontuação; a faixa etária da RFB está em `interposicao`, `parentesco` e `identidade_pessoa`; cinco chaves
  diferentes para "a mesma pessoa mascarada" (`fonte_grafo`, `qsa_certame_municipal`, `parentesco`,
  `interposicao`, `qsa_certame`).
- `receita_estab.db` com caminho montado à mão em mais de 15 módulos e duas variáveis de ambiente concorrentes
  (`JFN_DB_RECEITA`, `JFN_RECEITA_DB`); `osint/parentesco` e `fonte_grafo` importam o privado
  `reporting.intel_base._DB`.

## 6. Fora do escopo (anotado)

- "Ente público": `contato_compartilhado.explicacao_estrutural` usa natureza jurídica `1xxx`; as demais
  definições estão fora daqui (`entidades_gov`, `esfera_orgao.NATUREZA_PUBLICA`, `pericia_sweep`, `rules/engine`,
  `credor_generico`, `cruzamentos_intel._SQL_NAO_PUBLICO`) — ver `rules.md` §7.
- `knowledge/economicidade` importa `reporting.intel_base.moeda` (knowledge → reporting; `intel_base` é folha leve).

## 7. Verificação

- Testes casados antes (761bd35a): 644 passed, 18 skipped (48 arquivos de nucleo/knowledge/osint + catraca de
  `except`). Depois: knowledge 240 passed/1 skipped; nucleo+osint+qualidade+padroes+sei+catracas/regras (115
  arquivos) 1.222 passed/22 skipped; rodada final osint/nucleo 364 passed/8 skipped. Nenhuma linha de teste mudou.
- Não rodou: `gitnexus detect_changes` (o worktree não tem índice `.gitnexus`); o pre-commit avisou "validate/gen
  capabilities falhou" e "ruff ausente" em todos os commits (ambiente do worktree, não o diff).
