# Decision log — untangle de `compliance_agent/padroes/` (20/11/2026)

Escopo: os 24 detectores de `compliance_agent/padroes/` (rodados por `tools/padroes_varrer.py` e, no it-campo, por
`tools/padroes_no_itcampo.sh`) e as bases de família `_aditivos_comum`, `_pagamento_comum` (+ `_mrosc_comum`) e
`_carona_comum`. Escolhas do dono: **Comentários = sim** (só os que repetem o código saem), **Testes = não**.
Restrições da casa: comportamento pretendido igual; chaves dos JSON de `data/padroes/` (lidos pelo painel e pela
propagação) não mudam; OB/pagamento só por `cruzamentos_intel._ob_paga`; constante normativa com fonte única.

Formato igual a `rules.md`: o fix fica acima dos problemas que resolve. `[feito]` = aplicado nesta passada;
`[pendente]` = precisa de decisão do dono ou é redesenho de detector; `[fora do escopo]` = anotado só.

Prova de equivalência (além dos 152 testes casados): caixa de areia só-leitura com 137 processos (os controles
positivos citados nos detectores/fichas + 60 sorteados do arquivo + 10 só da íntegra, por symlink) e um
`compliance.db` mínimo (5.368 OB e 781 NE desses processos, `ob_reemitida` inteira); os 25 `varrer()` rodados com o
código de antes e o de depois (PNCP desligado nos dois) e os JSON comparados chave a chave: os 24 IGUAIS
(universo, cobertura, funil, achados, provas, valores). A amostra não tem credor pessoa física nem CPF em trecho de
prova; o mascaramento da seção 1 foi conferido à parte com entradas sintéticas.

## 1. Uma base para as três famílias: `padroes/_comum.py`  `[feito]`

- `_comum` guarda o que não depende de família e tem de mudar junto: conexão só-leitura ao banco, `trecho` da prova
  (com CPF mascarado), LGPD do credor (`credor_publico`, `documento_publico`), `ORDEM_GRAU`/`ordenar` da saída.
  Os caches de `data/padroes/` gravam por `rotina_base.gravar_json` (temporário único por `mkstemp`).
  - `RAIZ`/`DB`/conexão `mode=ro` copiados nas três bases (`_aditivos_comum._con`, `_pagamento_comum.con_ro`,
    `sqlite3.connect` em linha em `_carona_comum.ob_pagas`).
  - `trecho` em três cópias; só a do pagamento mascarava CPF. A ficha do contrato (`docs/PADROES-DE-IRREGULARIDADE.md`,
    "CPF mascarado") vale para todos, mas aditivos e carona punham o trecho cru na `prova` (termo, NE e contrato
    trazem CPF de representante e de signatário).
  - Ordem dos achados (forte → fraco, maior valor pago) escrita 9 vezes: dentro do `resultado` de duas bases, em
    cinco `varrer` da carona e (como dicionário local) na ordenação de sinais da carona e dos hits de
    `despesa_estranha_ao_objeto`.
  - Gravação atômica dos caches feita à mão 4 vezes; o conserto de 35ca9f54 (temporário por pid, `--paralelo`)
    chegou a três e não a `carona_acima_do_limite._salvar_cache` (`.tmp` fixo). `_pagamento_comum.grep_candidatos`
    gravava o cache direto, sem temporário: processo morto no meio deixava JSON truncado, que a rodada seguinte
    lia sem `try` por 12 h.
  - Credor pessoa física: `_pagamento_comum.credor_nome` omitia o nome de PF, mas os três detectores MROSC juntavam
    `nome_credor` cru; a carona punha `credor` (nome) e `obs[].cnpj` — que, para PF, é o CPF inteiro (medido hoje:
    credor de 11 dígitos em `ob_orcamentaria_siafe` é CPF com DV válido em 200 de 200 linhas de amostra); o
    `info_credor` dos aditivos punha o nome cru; `iss_declarado_retido_nao_retido` repassava `credor`/`nome_credor`
    do `detector_iss_retido` sem filtro. Agora: nome de PF "pessoa física (nome omitido)", CPF mascarado, nas três
    famílias. O nome cru continua disponível dentro do detector (a carona casa o nome do credor no extrato).
  - Nome de MEI/EI traz o CPF do titular ("NOME SOBRENOME 12345678900"): medido na revisão, 235 de 236 credores
    CNPJ com 11 dígitos no nome em `ob_orcamentaria_siafe`. `credor_publico` mascara o CPF dentro do nome; a razão
    social da Receita que `compra_fora_do_siafe` põe em `emitentes[].razao_social` também.
  - Efeito colateral aceito: `mascarar_cpf` mascara qualquer sequência solta de 11 dígitos no trecho (ex.: celular
    com DDD sem separador). Caches de `data/padroes/` passam a ser gravados com `indent=1` (maiores; chaves iguais).
- Blocos repetidos por detector viram uma função da base da família.
  - `mrosc_atesto_contra_relatorio`, `mrosc_execucao_igual_limiar`, `gestor_recebe_da_osc`: o mesmo bloco
    "OB pagas do processo → `valor_pago_ob` + `credor`" três vezes → `_pagamento_comum.completar_com_ob`.
  - Os cinco detectores da carona montavam `orgao`/`credor`/`valor_pago_ob`/`obs` à mão → `_carona_comum.campos_ob`.

## 2. Detector não importa detector  `[feito]`

- O que dois detectores usam mora na base da família.
  - `carona_acima_do_limite` importava `carona_aderente_vedado` para o universo (`base_adesao`) e chamava o
    `avaliar` inteiro dele (cláusulas, vedação, gerenciador) só para ler `r["adesao"]`. Agora `_carona_comum` tem
    `base_adesao`, `provas_de_adesao` e `tipo_adesao`; os dois detectores usam a base.
  - `RX_NE_EXTERNO` (acima) era cópia literal de `RX_EXTERNO` (vedado) → `_carona_comum.RX_ADESAO_EXTERNA`.
  - `ob_antes_da_entrega` importava `data_do_atesto` de `atesto_antes_do_periodo` → `_pagamento_comum.data_do_atesto`
    (com `MES`, `mes_num`, `data_ymd`, que o detector de atesto também usa).

## 3. Família aditivos: sobras e cópias  `[feito]`

- `_aditivos_comum.ler_leve` só repassava para `ler` → apagado.
- `aditivo_absorve_outro_lote.varrer` reimplementava `termos_do_processo` (o mesmo laço com as contagens de alheio e
  sem texto) → usa a base. `_norm_contrato` era cópia de `C.norm_contrato` → usa a base.
- Duas definições de "declaração de acréscimo que é reajuste": `acrescimo_colado_no_teto._RE_REAJUSTE` e
  `acrescimo_medido_pelo_objeto._RE_REAJ` (esta sem "correção monetária" e sem `\b` em IPCA/INCC) →
  `C.RE_REAJUSTE`. O "objeto dos termos" (início dos três primeiros) também era escrito nos dois →
  `C.objeto_dos_termos`.
- `diario_de_obra_copiado` usava `reuso_documento_execucao._sem_acento` (privado de outro módulo) →
  `C.sem_acento(...).lower()` (mesma normalização NFKD).
- `despesa_sem_previo_empenho` alcançava `C.acervo_texto.sem_etiqueta` pelo import de outro módulo → importa
  `sei.acervo_texto.sem_etiqueta` direto.
- `obra_renovada_como_continuo` recalculava `any(r["manutencao"] …)` duas linhas depois de guardá-lo em `manut`.

## 4. Lista vazia é universo vazio  `[feito]`

- `_mrosc_comum.universo(so, limite)` e `_pagamento_comum.pastas(so)` tratam `so=[]` como nenhum processo.
  - `so = so or tags_parceria(limite)` + `pastas(so)` com `if so:`: sem parceria na amostra (lista vazia) os três
    detectores MROSC varriam o ACERVO INTEIRO (o filtro `eh_parceria` dentro do laço deixava o resultado igual, mas
    a varredura custava a de 10 mil manifestos, e `cobertura["pastas"]` contava todas). `grep_candidatos` usava o
    mesmo teste para decidir se lia/gravava o cache.

## 5. Pendente — muda número no painel ou pede medição  `[pendente]`

- **Três leitores do acervo.** Cada família tem o seu universo e a sua regra de texto:
  - universo: pagamento só `data/sei_arquivo`; aditivos e carona `sei_arquivo ∪ sei_cache/integra_*`;
  - árvore > 1.000 documentos: pagamento lê `NNN.ocr.txt` antes de `NNN.txt` e não tira a etiqueta; aditivos prefere
    `.txt` ≥ 200 caracteres, depois `.ocr_gpu`, `.ocr`; carona fica com o mais longo de `.txt`/`.ocr.txt` e ignora
    `.ocr_gpu.txt`;
  - a carona lê o `.txt` do arquivo COM a etiqueta da casa (`sei.acervo_texto` manda tirar: "só o que a fonte
    serviu prova algo sobre a fonte"); `regime()` conta "14.133"/"8.666" e os regex de cláusula podem casar o título
    que está na etiqueta.
  Unificar numa porta só (universo + texto) é a correção de fundo, mas muda o texto lido por 25 detectores — pede
  rodada comparada no acervo inteiro, não cabe numa refatoração.
- **Três "OB pagas do processo".** `_aditivos_comum.ob_por_processo` normaliza a grafia (`chave_processo`:
  "…/23" = "…/2023", zeros à esquerda); `_pagamento_comum.obs_pagas` casa a string exata "SEI-…"; `_carona_comum.ob_pagas`
  tenta três variantes. O mesmo processo tem `valor_pago_ob` diferente conforme a família. E `ob_mensal` (série do
  `acrescimo_medido_pelo_objeto`) usa `LIKE` com duas variantes, outra regra que a do total, numa varredura da tabela
  POR processo. A régua canônica já existe: `compliance_agent/ob_processo.obs_por_processo` (camadas processo exato →
  normalizado → OB/PD/NL dos autos, devolução descontada; medido na Seleta: regra exata 31 OB/R$ 35,58 mi × 35 OB/
  R$ 39,34 mi) — e o `iss_declarado_retido_nao_retido` já a usa pelo `detector_iss_retido`. Trocar as três funções
  das famílias por ela é a correção, mas sobe `valor_pago_ob` em parte dos achados e muda a ordem do painel
  (ordenada por valor) e o custo (camada dos autos lê os PDFs) — decisão do dono.
- `credor` tem dois sentidos na família pagamento: atesto, OB antes da entrega, despesa estranha e reserva técnica
  põem o PRIMEIRO credor com nome (`credor_nome`); os três MROSC põem TODOS, separados por "; " (`credores`). Mesma
  chave no painel, conteúdos diferentes — escolher um é decisão de exibição.
- `trecho` de cada família repassa para `_comum.trecho` com a sua folga (120 aditivos, 140 carona, 90 pagamento) e,
  no pagamento, corta em 400 caracteres; mantidos porque as provas já gravadas foram calibradas assim.
- `gerado_em`: carona grava ISO com fuso (UTC), as outras famílias hora local sem fuso. Quem lê compara?
- `funil`: o pagamento calcula (contagem por grau); aditivos recebe do detector (etapas do funil). Mesma chave,
  conteúdos de natureza diferente.
- `despesa_estranha_ao_objeto` e `reserva_tecnica_multiplicada` devolvem `universo = limite` mesmo quando há menos
  pastas; `iss_declarado_retido_nao_retido` recorta `pastas()[:limite]` à parte.
- `retificacao_altera_valor._RE_REAJ` é a terceira lista de "reajuste" (com "aniversário"); lá ela anota, não
  exclui — juntar com `C.RE_REAJUSTE` muda a anotação.
- `gestor_recebe_da_osc._RX` é global preenchido antes do `fork` do `Pool` (ordem de chamada implícita). Passar o
  regex por argumento faria o `Pool` recompilar a trie de milhares de nomes a cada lote — mantido, o comentário diz.
- `compra_fora_do_siafe.serie_cotas` tem a UG `'166100'` literal (a ficha yaml já traz `ugs_sedec`); `con`/`rec`
  nunca fecham; `_data` é mais um parser de data.
- `beneficio_para_conta_do_orgao` e `compra_fora_do_siafe` abrem `receita_estab.db` cada um à sua maneira (um falha
  se o arquivo faltar, o outro devolve `None`).
- Três `sem_acento` (aditivos NFKD, carona `str.translate` por desempenho, `reuso_documento_execucao`): diferem em
  caracteres fora do português (ex.: "º" vira "o" só no NFKD).

## 6. Fora do escopo (anotado, não mexido)

- Validador de CNPJ copiado em ao menos cinco módulos (`qualidade/catracas.cnpj_valido`, `cerebro_fts`,
  `nucleo/dossie`, `sei/cotacoes_acervo`, `compra_fora_do_siafe.cnpj_ok`).
- `mascarar_cpf` existe em `triagem_alertas`, `qualidade/verificadores`, `osint/vinculos` e agora `padroes/_comum`.
