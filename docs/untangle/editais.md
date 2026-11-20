# Decision log — untangle de `compliance_agent/editais/` (20/11/2026)

Escopo: `compliance_agent/editais/` (22 arquivos — enxame de direcionamento por peer-diff, teste finalístico,
gradeador de flags, escalada/dosimetria, índice de certame e narrativa, screens de conluio, avaliação de
conjunto, CRI, ponte TCE-RJ, UG→CNPJ) e as réguas que ele lê (`limites_aditivo`, `catalogo_vicios`,
`esfera_orgao`, `standard_prova`, e a régua nova `limites_habilitacao`). Escolhas do dono: **Comentários =
sim** (saem só os que repetem o código; medição datada, decisão do dono, norma e porquê de workaround ficam),
**Testes = não**. Regras da casa acima da skill: título de achado/flag e chaves lidas pelo painel/vault não
mudam; constante normativa em fonte única; comportamento igual salvo defeito provado; escopo só RJ (Estado +
Prefeitura do Rio).

Formato (o de `detectores.md`): o fix fica acima dos problemas que resolve. `[feito]` = aplicado nesta
passada; `[pendente]` = precisa de decisão do dono, muda resultado de entregável ou é de outra área.

**Validação empírica** (sem rede, sem gravar no banco, `compliance.db` em `mode=ro`), antes × depois de cada
lote, com o código-base extraído de `a94f3d56`:
- *snapshot fino* — 45 editais RJ reais (30 amostrados por passo fixo em `edital_documento` das raízes 42498600 e
  42498733 + 15 com ata julgada/veredito do enxame): cláusulas → força E7 → teste finalístico → `grau_flag` →
  `escalada.recomendar` (com e sem grau) → `dosimetria`; `indice_certame.calcular`, narrativa (template, sem
  LLM) e o prompt montado, `screens`; 7 motivos de inabilitação reais; conjunto de 2 órgãos RJ + `ctx_secao`;
  `avaliar_unidades`; 20 certames TCE-RJ (`contexto_j4`) e CRI; 4 UGs → CNPJ;
- *varredura larga* — 500 editais RJ (768 cláusulas): teste finalístico pelo subtipo e pelo tipo E7, grau,
  ficha de matriz da cláusula (`relatorio_direcionamento._matriz_risco`) em 8 combinações de escore/raridade
  por cláusula; `recomendar`/`graduar` em toda a faixa S×V (−1..27); `matriz_sv` em 40 combinações; screens
  de conluio nos 40 certames com `proposta_item`.
- Resultado: **idêntico byte a byte em todos os lotes**, salvo o único diff pretendido do lote 5 ("COMPARAÇÃO
  FRÁCA" → "FRACA", 1 evidência). Suíte casada: 588 testes antes e depois.

## 1. Tetos de exigência de edital em fonte única: `limites_habilitacao`  `[feito]`

- `compliance_agent/limites_habilitacao.py` (irmã de `limites_dispensa`/`limites_aditivo`/`limites_porte`):
  `ATESTADO_QUANTITATIVO_MAX_PCT` (50), `CAPITAL_PL_MAX_PCT` (10), `GARANTIA_PROPOSTA_MAX_PCT` (1),
  `VIGENCIA_CONTINUA_MAX_MESES` (60). Em percentual porque `x / 100` dá a fração exata e `fração * 100` não.
  - `teste_finalistico.avaliar` escrevia 10.0/50.0/1.0/10.0 (faturamento, por analogia ao capital) e 60.0 seis
    vezes (o teto de vigência ia em cada `_res`).
  - `clausulas._faixa` fixava a fronteira alto/baixo da assinatura em `0.50`/`50` — o teto do atestado, sem
    dizer.
  - `narrativa_certame._NORMA` (texto do prompt) repetia 1%, 25%, 50% e 10%. Agora é montado das réguas; o texto
    sai idêntico (conferido) e `montar_prompt` não mudou, então o hash do `nucleo/prompt_versao` é o mesmo.
- Ficam como pendência (§9): as cópias em `detectores/e1_barreira.py` e `e7_clausula_restritiva.py` e a
  divergência de CITAÇÃO do mesmo número.

## 2. Régua S×V única em `escalada`  `[feito]`

- `escalada` passa a ser a dona da régua 1-4/5-9/10-15/16-25: `nivel_sv(produto) → (nível, ação)`, `REGUA_SV`
  e `_degrau_por_sv` derivado da mesma tabela `_FAIXAS_SV`.
  - `indice_certame._matriz_sv` reimplementava a régua ("reimplementada mínima aqui em dict") e
    `relatorio_direcionamento._matriz_risco` tinha a terceira cópia, com os mesmos quatro textos de ação.
    Hoje os dois chamam `nivel_sv`; o relatório só acrescenta o emoji do nível.
  - `_matriz_sv` era importada como privada por `rotas/produtos` e pelo relatório: vira `matriz_sv`.
- `REINCIDENCIA_AUDITORIA_TEMATICA = 3` em `escalada`: `avaliacao_conjunto.REINCIDENCIA_AUDITORIA` era a
  segunda cópia do gatilho "≥3 certames do órgão → auditoria temática" (mesmo texto nos dois).
- Conferido: `_degrau_por_sv` novo = antigo para todo inteiro de 1 a 25; níveis/ações idênticos no snapshot.

## 3. Leitura do banco por um lugar: `editais/db`  `[feito]`

- `editais/db` ganha `DB_PADRAO`, `conectar_ro(db_path)` e `consultar(con, sql, params)` (query tolerante a
  tabela ausente: fonte não coletada = lista vazia, INDISPONÍVEL ≠ 0).
  - Cinco aberturas `mode=ro` escritas à mão: `indice_certame._conectar_ro`, `avaliacao_conjunto._ro`,
    `ug_cnpj._candidatos`, `coletor_propostas._ler_atas` e `backfill`.
  - Três cópias de `_q` (indice, narrativa, avaliacao_conjunto).
  - Quatro importações de `emendas.db._DB_PADRAO` (privado) — agora só `editais/db` toca nele.
  - `narrativa` e `rotas/produtos` importavam `indice_certame._conectar_ro` (privado de outro módulo).
- Saem três `try/except sqlite3.OperationalError` em volta de `_q` em `_f_competicao`, `_f_certame_ata` e
  `_f_execucao`: `_q` já engole a `OperationalError`, os `except` eram inalcançáveis. Fica o de `_f_conluio`
  (chama `screens`, que não é tolerante).

## 4. Limiar do veredito e piso da fonte com um dono  `[feito]`

- `editais/db.SCORE_DIRECIONAMENTO = 7` (junto do schema de `clausula_veredito`): o enxame
  (`enxame/orquestrador._veredito`) decide "direcionamento" com ele, e o índice (efeito combinado: "N cláusulas
  com escore ≥7/10"), a avaliação de conjunto (`SCORE_RESTRITIVA`, cópia) e o runner
  `tools/editais_direcionamento` (duas contagens `>= 7`) contam com ele. O enxame importa de `editais/db`
  (estável), não o contrário — `orquestrador` puxa as lentes LLM.
- `conluio_participacao.MAX_HOMOLOGADO_SOBRE_ESTIMADO` era cópia declarada ("mesmo piso do coletor") de
  `collectors/tcerj_licitantes`: importa de lá (o coletor mede o defeito da fonte; `tools/
  screen_coparticipacao_relacionados` já importava de lá).
- `parse_json_llm` direto em `narrativa_certame`: `direcionamento_cerebro._parse_json` era repasse puro.
- `peer_diff._SUBTIPO_PARA_TIPO_E7` era lido pelo relatório como privado: vira `SUBTIPO_PARA_TIPO_E7`.
- `avaliar_unidades(raizes_cnpj=...)` tinha as raízes 42498600/42498733 escritas à mão (e `rotas/produtos`
  repetia as duas na chamada): o default vem de `esfera_orgao.RAIZES_RJ` e a rota usa o default.
  `avaliar_portfolio(esferas=...)` copiava `("estadual-rj", "municipal-rio")`: vem de `esfera_orgao.NO_RJ`
  (a fonte única de "o órgão é do RJ?"; mesmos valores).
- `teste_finalistico`: o "5 anos" do texto de vigência sai de `VIGENCIA_CONTINUA_MAX_MESES / 12` (texto igual,
  conferido numa grade de 704 combinações de subtipo × cláusula × valor contra o código-base).

## 5. Defeitos consertados  `[feito]`

- **`avaliacao_conjunto.ctx_secao` levantava `TypeError`** (`None:.1f`) quando todo certame indexado do órgão
  tem `confianca = 0` — `avaliar_orgao` devolve mediana/p90 `None` nesse caso (de propósito, INDISPONÍVEL ≠ 0)
  e a seção do dossiê mestre caía. Na base de 20/11 há 1 órgão nessa condição. Agora a célula diz
  INDISPONÍVEL. Reproduzido no código-base antes do conserto.
- `indice_certame._f_preco` relia todo `pncp_resultado` com preço (75.852 linhas) e normalizava cada descrição
  **para cada item do vencedor**; agrupa por item normalizado numa leitura só. Mesmo resultado; o snapshot de
  45 editais caiu de 3 min 8 s para 51 s (a VM estava em load 8-11 nos dois).
- Texto: "COMPARAÇÃO FRÁCA" → "FRACA" (o único diff do snapshot); o "25%" da evidência de aditivo vem de
  `LIMITE_ADITIVO_LEGAL`; a docstring do índice dizia 6 famílias e `confianca = apuráveis / 6` — são 7
  (`certame_ata`), e o código sempre dividiu por 7.

## 6. Comentários  `[feito]`

- Saíram os que só repetiam o código: dois em `coletor_propostas` (repetiam a docstring dos guards), a nota
  histórica no import de `MODALIDADE_NOME` (o motivo já está em `_f_transparencia`) e a frase que relia
  `DIAS_DECISAO_MIN/MAX` em `cri`. O resto do pacote é medição datada, norma, decisão do dono ou porquê de
  workaround — ficou.

## 7. Casos especiais que ficam (o sistema ainda precisa deles)

- `peer_diff.candidatas`: cluster < 3 cai no catálogo E7 absoluto (só tier forte); limiar de raridade
  acompanha o teto `(n-1)/n` do cluster. Ambos documentados, ambos medidos.
- `indice_certame`: credenciamento (12) com valor próprio; código de modalidade fora da tabela do PNCP não
  afirma disputa. `teste_finalistico`: faturamento mínimo nunca rebaixa (fora do rol do art. 69); vigência
  indeterminada com monopólio vira não aferível (art. 109).
- `except Exception` que degradam para INDISPONÍVEL e estão declarados: `corpus.coletar_corpus` (1 edital
  ruim), `ata_para_julgamento.backfill` (1 ata ruim), `cri.calcular` (bandeira quebrada), `narrativa.narrar`
  e `motivo_inabilitacao.classificar_com_rubrica` (LLM fora → template/ambíguo).
- `db.init_schema` com `ALTER TABLE` em `try/except` (migração aditiva) e `narrativa.garantir_coluna` idem.

## 8. Testes

Suíte casada (editais, réguas, relatório de direcionamento, processo 360, catracas `test_regra_*`, catálogo):
**588 passed** antes; depois de cada lote, os testes casados com ele (47–192 por lote) e a suíte casada inteira
no fim. Nenhum teste foi alterado (Testes = não).

## 9. Pendências

Ordem sugerida pela revisão independente (etapa 5), do que mais mexe em número publicado para o que menos.
Todos **mudam entregável** salvo indicação — por isso não foram aplicados sem o dono.

1. **Dois vocabulários de `subtipo` na mesma coluna** (`peer_diff._FORTE/_MEDIO/SUBTIPO_PARA_TIPO_E7` ×
   `clausulas.rotular_eixo`). As exigências gravam nome curto (`capital`, `atestado`); as cláusulas restritivas
   do catálogo E7 gravam o tipo longo (`capital_patrimonio`, `marca_dirigida`, `visita_tecnica`,
   `vinculo_profissional`, `indices_contabeis`…). `forca_e7` só conhece o curto. Medido em 20/11 em
   `clausula_veredito`: `capital`/`patrimonio`/`atestado` saem "forte" (148), e **todos** os 233 de nome longo
   saem "fraco" e sem súmula — `capital_patrimonio` 42, `indices_contabeis` 73 (deveria ser "medio"),
   `visita_tecnica` 11, `vinculo_profissional` 4, `marca_dirigida` 2. No cluster < 3, o caminho "absoluto"
   descarta todos eles. Conserto de uma linha (`tipo = SUBTIPO_PARA_TIPO_E7.get(subtipo, subtipo)` e os tiers
   por tipo E7), mas muda quais cláusulas vão ao enxame (corte `max_candidatas`), a súmula gravada e a
   severidade da ficha (forte=4 × fraco=2) — exige controle positivo/negativo (regra 9) e decisão sobre
   reprocessar os 233.
2. **`indice_certame._f_execucao` soma `valor_acrescido` cru** e só importa o número 25% de `limites_aditivo`,
   que se declara fonte única da DECISÃO (natureza do termo: reequilíbrio/prorrogação não consomem teto; reforma
   50%). Usar `limites_aditivo` inteiro muda a família `execucao`, o score e os casos `direcionamento:*`.
3. **Vocabulário de peça divergente:** `escalada.PECAS` tem `diligencia_prioritaria`; a `ordem` de
   `standard_prova.rebaixar_peca` não tem → o degrau 2 (S×V 10–15) nunca é conferido contra o standard
   probatório (grau D/E com S×V 12 sai "diligência prioritária"); `escalada` ainda cai em `"diligencia"`
   quando a peça devolvida não está em `PECAS`. `catalogo_vicios.ESCALADAS` é um terceiro vocabulário (tem
   `auditoria_tematica`, não tem `diligencia_prioritaria`). Muda `escalada.peca` no `processo_360`.
4. **Índice sem família apurável sai `score 0.0`/`BAIXO`** e é persistido (`calcular`), contra o INDISPONÍVEL ≠ 0
   do próprio módulo; `avaliacao_conjunto` filtra `confianca > 0`, mas `casos_ancora = avaliados or rows` e a
   ficha ainda mostram "0/BAIXO". Muda faixa no painel e texto da ficha.
5. **Narrativa apagada pelo índice:** `calcular_e_persistir` faz `INSERT OR REPLACE` sem `narrativa_json` e
   zera a coluna gravada por `narrar_e_persistir`; o `INSERT OR IGNORE (certame)` da narrativa cria linha com
   score NULL. Hoje sem efeito (`narrar*` não tem caller de produção); consertar com UPSERT por coluna antes
   de ligar a narrativa.
6. **Falsos positivos de texto:** `teste_finalistico` (recorte temporal) pega o primeiro "N horas" da
   cláusula — "postos de 12 horas" vira prazo de 0,5 dia → `violado`; `motivo_inabilitacao` (substancial)
   casa `suspens` em "sessão suspensa" e, testado antes do trivial, rotula motivo trivial como lícito.
7. **Citação dos tetos diverge** para o mesmo número: capital/PL 10% = "Súmula TCU 275; Lei 8.666/93 art. 31
   §3º" (`teste_finalistico`), "art. 69 §3º" (E1), "art. 69 §§2º e 4º" (`catalogo_vicios`, verbatim). As
   cópias numéricas de 10%/50%/1% em `detectores/e1_barreira.py:186` e `e7_clausula_restritiva.py:71,80,120`
   devem passar a importar `limites_habilitacao` (área `detectores/`; mesma pendência em `detectores.md`).
   Conferir o dispositivo no texto oficial antes de unificar a citação.
8. **`dosimetria` cita "Lei 8.443/1992, art. 250, II/III"** — a Lei Orgânica do TCU não chega ao art. 250
   (é o Regimento Interno do TCU); para entregável do RJ a base é a LC estadual 63/1990 (TCE-RJ). Sem caller
   de produção hoje; corrigir antes de ligar.
9. **Construído, testado, nunca rodado** (sem caller fora de `tests/`, conferido em `compliance_agent/`,
   `rotas/`, `tools/`, `config/*.yaml`, `*.sh`): `certame_tcerj` inteiro (e `contexto_j4` duplica
   `collectors/tcerj_licitantes.contexto_certame`, que é o que J4/CRI consomem), `dosimetria.graduar`,
   `narrativa_certame.narrar*`, `motivo_inabilitacao.classificar_com_rubrica`,
   `screens_conluio.vetores_unitarios_similares`, os três screens de `screens_participacao` (o módulo declara
   isso desde 18/11; só `normalizar_nome` é usado, por `conluio_participacao` e `osint/grupo_economico`); `cri`
   só via `tcerj_licitantes.ranking_por_ente`, também sem caller. Apagar ou ligar é decisão do dono (apagar
   leva testes junto; Testes = não).
10. **Escopo RJ:** `conluio_participacao` (rodado pela propagação, `config/propagacao.yaml:707`),
    `screens_participacao`, `certame_tcerj` e o CRI leem `tcerj_licitante` — **91 municípios** jurisdicionados
    do TCE-RJ, quase todos fora de "Estado + Prefeitura do Rio". Decidir se esses screens seguem (são
    jurisdição do TCE-RJ) ou se filtram para o Município do Rio.
11. `conluio_participacao`: o denominador de Bonferroni conta pares com `k >= 3`, desacoplado de
    `MIN_ENCONTROS=4`/`MIN_JUNTOS=5`/`MIN_JUNTOS_RODIZIO=4` (a docstring diz "pares efetivamente testados");
    dois nomes que resolvem para a mesma raiz no mesmo certame contam o par em dobro; `ob_estado` casa
    `credor LIKE raiz%` (um CPF com os mesmos 8 primeiros dígitos casaria). Mudam `alfa_corrigido`, p-valores
    e contagens do JSON `data/conluio/participacao.json`.
12. **Cópias que não mudam número hoje** (higiene, áreas vizinhas): limiares 7/4/9 do escore 0-10 escritos à mão
    em `reporting/relatorio_direcionamento.py:350,376,390` (o 4 do "indício fraco" também em
    `enxame/orquestrador`); a régua S×V em texto fixo em `_matriz_risco` e no `fundamento` da escalada, e os
    pisos 10/16 em `dosimetria`; rótulo ALTO com duas escalas (capa do relatório ≥ 70 × índice ≥ 50) e
    `MEDIO`/`MÉDIO`, `EXTREMO`/`CRÍTICO`; `HHI_CONCENTRADO = 0.25` em `avaliacao_conjunto`,
    `screens_participacao` e `osint/grupo_economico`; o prazo de 2 dias (Acórdão TCU 871/2023) três vezes em
    `teste_finalistico`; `cri.PRAZO_MINIMO_DIAS = 8` é o menor prazo da tabela do art. 55 que o E2 mantém
    (`MINIMOS_ART55`) — ligar quando a tabela virar régua; `relatorio_direcionamento` diz "6 famílias" e
    usa `or 7` fixo.
13. **Imports de privado / direção** (fora deste pacote): `clausulas` ← 3 privados de
    `detectores/coletor_edital` (registrado em `detectores.md`); `avaliacao_conjunto` ←
    `lex_base_empirica._quantil`; `indice_certame` ← `cruzamentos_intel._mediana/_norm_item`;
    `conluio_participacao` ← `cruzamentos_intel._ob_paga` e dois scripts de `tools/`; `agrupar` ←
    `tools.hermes_rag._embed`; `corpus` ← `pncp._parse_id_pncp`; `coletor_propostas` ←
    `coletor_ata._extrair_propostas`; `editais/db` ← `emendas.db._DB_PADRAO` (o caminho do compliance.db mora
    em `emendas/`). `esfera_orgao` lê o banco por caminho fixo com `lru_cache` e ignora o `db_path` de
    `avaliar_portfolio` (só pesa em base alternativa/teste). `pcrj/esfera.classificar_esfera` é repasse de
    `esfera_orgao.esfera` com renome de rótulo.
14. Arredondamento do enxame: `int(round(mediana))` é bancário (6,5 → 6 "indício fraco"; 7,5 → 8) — implícito.
