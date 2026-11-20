# Decision log — untangle de `compliance_agent/detectores/` (20/11/2026)

Escopo: `compliance_agent/detectores/` (47 arquivos: `base.py`, `__init__.py`, 41 detectores do REGISTRO, P7 e
EST fora dele, dois coletores) e as réguas que eles importam (`limites_dispensa`, `limites_aditivo`,
`cruzamentos_intel._ob_paga`). Escolhas do dono: **Comentários = sim** (saem só os que repetem o código; medição
datada, decisão do dono, norma e porquê de workaround ficam), **Testes = não**. Regras da casa acima da skill:
título de alerta, id de detector e chave de `valores`/evidência lida pelo painel não mudam; constante normativa
com fonte única; OB paga só pela régua `cruzamentos_intel._ob_paga`; comportamento pretendido igual.

Formato (o mesmo de `rules.md`): o fix fica acima dos problemas que resolve. `[feito]` = aplicado nesta
passada; `[pendente]` = precisa de decisão do dono ou é redesenho de detector; `[fora do escopo]` = só anotado.

## 1. OB paga pela régua da casa  `[feito]`

- `est_valor_contratual.varrer` passa a ler a OB do SIAFE com `WHERE credor = ? AND _ob_paga(con)`.
  - `est_valor_contratual.py:61` (`_pago`) decidia "pago" por `status.startswith("contabiliz")` em Python e a
    consulta da linha 164 trazia toda OB do credor. Somava, portanto, a OB devolvida pelo banco ('Erro no
    Pagamento'), o 'Pagamento Complementar' (que a OB principal já paga — dobro), a OB reemitida e a OB sem número:
    exatamente o que `_ob_paga` exclui desde 18–19/11. O detector roda em cron (domingo 06:50, `--gravar` em
    `achado_detector`) e a docstring dizia "Pago = só OB Contabilizada". As catracas
    `test_catraca_ob_so_contabilizada`/`test_catraca_ob_devolvida` não o viam (não casa o regex `'Contabilizado'`).
  - `avaliar` continua descartando o não-Contabilizado para quem lhe passa OB crua (o teste passa uma lista com
    'Anulado'); a régua decide na consulta, que é o único caminho de produção.
  - **Muda comportamento** (defeito): `pago_ob_contabilizada` cai onde havia OB complementar/devolvida/reemitida, e
    com ele disparos de `EST-VALOR-EXCEDIDO`. Não medido na base (a varredura inteira leva até 30 min; a VM estava
    em load 15).

## 2. Uma pergunta ao LLM por rubrica, num lugar  `[feito]`

- `base.perguntar_rubrica(gerar, prompt, sistema, escala)` faz o protocolo inteiro (chama o LLM, degrada para
  `nao_avaliavel` se ele cai, parseia, aplica a rubrica fechada) e devolve `(nível da rubrica, motivo, resposta)`;
  `base.nivel_rubrica(resposta, escala)` é o mesmo juízo para a rubrica já pronta (atalho de teste). Os
  detectores só montam o `sistema`/`prompt` — que são deles — e leem o nível. Títulos, chaves de `valores` e
  textos de motivo ficam iguais.
  - O bloco `try: gerar → except Exception → import _parse_json → avaliar_rubrica → isinstance(dados, dict) →
    dados.get("nivel").strip().lower()` e o ramo do atalho de teste ao lado estavam escritos à mão 45 vezes em 22
    arquivos (C6, E1–E6, J2, J4–J7, P1, P2, P4, P5, X1–X6), com a mesma mensagem "LLM indisponível (…)" em cada
    cópia.
  - As cópias já tinham divergido num ponto: o ramo do atalho lia `nivel or classificacao`, o ramo do LLM lia só
    `nivel`. `avaliar_rubrica` aceita os dois campos, então um LLM que respondesse `{"classificacao": …}` passava
    na rubrica e saía com status `""` — não casava com nenhum nível e a rubrica sumia sem aviso. Agora os dois
    ramos leem o mesmo. **Muda comportamento** só nesse caso (antes: status vazio — no X2, `nao_avaliavel`, porque
    a classe era barrada por `_CLASSES_VANTAJOSIDADE`; agora: o nível respondido). X7, que já tinha protocolo
    próprio com `fonte=`, gravava em `valores["rubricas_alea"]` só o campo `nivel` (None com `classificacao`);
    passa a gravar o nível respondido.
  - `isinstance(dados, dict)` depois de `avaliar_rubrica` era verificação repetida (ela já devolve `None` para o
    que não é dicionário). `X2` conferia `classe in _CLASSES_VANTAJOSIDADE` depois da rubrica pelo mesmo motivo
    (e quebrava com `AttributeError` se a rubrica injetada não fosse dicionário).
  - `base._parse_json` era repasse puro de `llm/json_resposta.parse_json_llm`, importado como nome privado,
    dentro de função, por 22 detectores e pelos dois coletores. Saiu; quem precisa do JSON cru (E5, E6, X6,
    coletores) importa o parser da casa direto. Nenhum teste fazia monkeypatch dele.
- Ficam como estavam (registrado, não mexido): X7 e X11 já usavam `parse_json_llm` e passam `fonte=` para
  conferir a citação. **Nenhum** dos outros detectores passa `fonte=` a `avaliar_rubrica`, então a citação do
  LLM nunca é conferida contra o texto (o motivo declara "[citação não conferida]"). Ligar exige decidir qual
  texto é a fonte de cada rubrica e descarta classificações que hoje pontuam — ver §8 (pendências).

## 3. Uma leitura de data  `[feito]`

- `base.para_datahora(v)` / `base.para_data(v)`: date, datetime ou texto ISO/BR, com ou sem hora → data; o que não
  é data → `None` (≠ 0). A lista de formatos (com a ordem que o E2 aprendeu em produção) mora em
  `base.FORMATOS_DATA`. E2, P4, P5, X1, X2, X3, X7, X8 e X13 deixam de ter parser próprio. Os testes de E2 e P5
  importam `_to_date`/`_to_datetime` pelo nome — ficam como apelidos de importação (Testes = não).
  - Oito parsers para a mesma pergunta, com quatro comportamentos: X1/X2/P4 (idênticos, sem `strip`), X3 (com
    `strip`), E2/P5 (formatos com hora + recurso só-data) e X8 (`str(v)[:10]`), mais X7 (`str(data)[:4]` como
    "ano") e X13 (`date.fromisoformat`, só ISO).
  - **Defeitos que somem** (mudam o resultado):
    - X1, X2, X3 e P4 devolviam `None` para ISO sem segundos (`2026-07-03T17:00`, o formato do PNCP): o aditivo,
      a prorrogação, o pagamento ou a dispensa perdiam a data e saíam do cálculo calados. Passam a contar.
    - X7 tirava o "ano" com `str(data)[:4]`: para data BR (`15/03/2024`) o ano era `"15/0"`, e o teste de dupla
      correção no mesmo exercício agrupava por dia/mês. Passa a agrupar pelo ano.
    - X13 só aceitava ISO: data BR virava "sem janela" (`_dias` → None). Passa a medir.
    - X8 e P4 devolviam o `datetime` intacto quando recebiam um (`datetime` é subclasse de `date`); comparado com uma
      `date` levanta `TypeError` e o detector inteiro virava `nao_avaliavel` no pipeline. Os produtores de hoje
      passam texto, então estava latente.
  - Diferenças de borda declaradas: X13 deixa de ler ISO compacto (`20240315`, que `date.fromisoformat` aceita no
    Python 3.12); nenhum produtor manda esse formato. X7 mantém o prefixo de 4 caracteres como ano quando o texto
    não é data (só o ano, `"2024"`, ou data impossível de OCR, `2024-02-30`) — como antes.
- Única linha de teste tocada até aqui: `tests/test_catraca_excepts.py` `BASELINE 1626 → 1600`. A catraca exige
  abaixar quando a contagem de `except` cai mais de 25 ("só anda numa direção"); caiu 26 com os lotes 2 e 3.

## 4. Constante normativa lida da régua, não recopiada  `[feito]`

- `p4_fracionamento.limite_dispensa` passa a ler o valor de `limites_dispensa.limite_dispensa`; fica nele só o que
  é do P4 (exercício ausente → `_DEFAULT_EXERCICIO`; exercício anterior a 2021 → `None`/nao_avaliavel, porque a
  régua devolve o teto mais recente para ano fora da tabela). O nome continua exportado: `tools/sweep_fracionamento_tcerj`
  e o teste de fonte única o importam.
  - Era uma segunda implementação da busca na tabela (`in LIMITES`, `max(anteriores)`, `fator 2` do §2º) — a
    docstring da régua diz "NUNCA duplicar… as cópias divergentes em p4_fracionamento foram o motivo deste
    módulo". Conferido: as 64 combinações (8 exercícios × 4 grafias de tipo × duplicado) dão o mesmo valor.
- X1: sai o repasse `teto_art125` (só chamava `limites_aditivo.teto_acrescimo`) e o import no meio do arquivo com
  `# noqa: E402`. A chave `valores["teto_art125"]` fica. `config/qualidade_detectores.yaml` apontava a hipótese
  inocente "reforma tem teto de 50%" para `x1…:teto_art125`; passa a apontar para `limites_aditivo.py:teto_acrescimo`.
- C9: as faixas de TAC (≥50% ou ≥30% com R$ 100 mi → crítico; ≥30% ou ≥10% com R$ 50 mi → médio) eram cópia de
  `reporting/detector_tac._severidade` — a docstring dizia "espelha". Passa a chamar a régua do relatório
  (ALTO → crítico, MÉDIO → médio, BAIXO → descartado); conferido em 66 pares (pct × total) sem divergência.
  `_brl` (nome privado de `coerencia_valores`) → `intel_base.moeda`, mesma saída.
  - O import é de um nome privado (`_severidade`), porque os testes de `detector_tac` o importam por esse nome;
    torná-lo público é mexer no módulo do relatório — anotado em §9.

## 5. O peso do detector é o da família dele  `[feito]`

- `PESOS_DETECTOR` passa a ser derivado: `{id: PESOS_FAMILIA[família]}` para todo detector do REGISTRO, mais os
  sub-ids `C1`/`C2`/`C3/C5`/`C4` da `CFachada` com o peso da família de `C`. Conferido antes: as 40 entradas
  literais eram todas iguais ao peso da família (nenhuma "decisão editorial" diferente, ao contrário do que o
  comentário dizia), e as que faltavam (`C`, `C7`, `C9`, `E8`, `P6`) já entravam pelo `setdefault`. Mesmo mapa.
  - `__init__.py:110` dicionário literal de 40 linhas + laço `setdefault` que existia porque detector novo ficava
    sem peso (C7 e P6 pesaram 0,6 em vez de 1,0 até 07/2026).
  - 26 comentários `familia = "…"  # … peso 0.85 (conluio) …` repetiam o peso de `PESOS_FAMILIA` — e 4 erravam
    (J2, J3, J4, J9 diziam 0,85; conluio pesa 0,9). Saíram os números; ficou o que não está no código (E2 é
    agravante, P2 contamina o preço de referência, P4 é violação objetiva do art. 75 §1º…).
  - `base.PESOS_FAMILIA`: comentários "J1–J7", "C1–C6", "X1–X12", "E1–E6" — listas de membros que já tinham
    envelhecido (há J8, J9, C7–C9, X13, E7, E8).


## 6. Sobras sem razão própria de mudar  `[feito]`

- P4: o clusterizador antigo (`_STOP`, `_norm_objeto`, `_similar` com `difflib`, `_grupo_objeto`) ficou sem
  chamador quando `clusterizar` passou a delegar a `objeto_similaridade` (24/07); `_RE_INCISO` nunca foi lido;
  `contratacoes_do_orgao` (montava o contexto do P4 a partir de `ordens_bancarias` TFE, sem filtro de OB
  anulada, por DuckDB) não tem chamador em código, teste, yaml ou shell. `_todos_idxs` desempacotado e não lido.
- X7: `_evidencias` era repasse com import tardio de `base.evidencia`; `import re` repetido dentro de
  `_norm_indice`; `t.startswith(chave) or chave in t` (o primeiro implica o segundo).
- X4: `_avaliar_rede` só chamava `_rubrica_rede` (que os testes usam).
- E1: `import re` repetido dentro de `_chave_exig`. E2: `from datetime import timedelta` dentro de duas funções.


## 7. Comentários e docstrings  `[feito]`

- Saíram os que só repetiam a linha seguinte: `c_fachada` "ordena por score desc", `e4` "dedup preservando
  ordem", `x1` "aditivo precoce: 1º aditivo…", `x4` "agrega adesões por item…".
- Os que mentiam passam a dizer o que o código faz:
  - `base.py`: o "MAPA DOS 30 DETECTORES" do docstring (o REGISTRO tem 41) marcava 🟡 "falta o card" em P1, P2,
    E1, E6, J2–J4, J6, J7, X1 e X6, todos prontos; passam a ✅ com o arquivo do detector, e a base reusada fica
    anotada. (O lote 7 tinha tirado o mapa inteiro, por ser segunda lista do REGISTRO; a suíte casada final
    mostrou que `tests/test_mapa_detectores_honesto.py` trava o mapa como artefato desejado — que liste todo id do
    REGISTRO e não declare "a construir" o que existe. O mapa voltou na segunda volta, corrigido.)
  - `base.verificar_adversarial` e o mapa diziam que o motor é `direcionamento_cerebro.gerar_sync`
    (Gemini→Groq→Cerebras); o código usa `llm.comotor.juizo`, e o Cerebras está desligado.
  - `p4_fracionamento`: docstring citava "similaridade ≥ 0.8" (o critério de antes de 24/07), "QSA cruzado" (é
    raiz do CNPJ/grupo econômico) e uma regra "Sequência pós-limite … 0.60" que não existe no código.

## 8. Pendente — decisão do dono ou redesenho de detector  `[pendente]`

Medidas e regras jurídicas que a refatoração achou e não pode decidir sozinha (corrigir muda resultado ou exige
escolher a regra):

- **C7 × `sancao_impeditiva` (régua que se declara fonte única).** C7 mantém lista própria (`_IMPEDITIVAS` +
  exceção "interdição"). Medido hoje nas 25.500 sanções de `sancoes_federais`, por categoria: as duas regras só
  divergem em duas categorias — "Suspensão/Interdição das atividades" (53) e "Proibição de receber incentivos,
  subsídios…" (23). Nas duas o C7 está certo (não vedam contratar) e a régua está errada; a régua é usada por
  `cruzamentos_intel._SQL_IMPEDITIVA` e `nucleo/adaptador_db`. Proposta: levar as duas exclusões para a régua
  (Python e SQL) e o C7 passar a importá-la — muda o resultado dos outros consumidores (76 sanções deixam de
  contar como impeditivas), por isso fica para o dono.
- **Citação da rubrica nunca conferida.** Só X7 e X11 passam `fonte=` a `avaliar_rubrica`; nos outros 22 a
  regra de ouro "citação literal" é só "campo não vazio". Ligar = decidir o texto-fonte de cada rubrica; descarta
  classificações que hoje pontuam.
- **Prompts de rubrica sem dado.** J2 (cobertura) não manda propostas nem valores; P2 (similaridade) manda só a
  quantidade de cotações; P2/P5 pedem `"<um nível da escala>"` sem listar os níveis; X3 (art. 141) não manda texto
  do processo. A rubrica responde sem base ou cai fora da escala. Redesenho dos prompts.
- **Score fora das âncoras.** E2 (`score + 0.10`) e P4 (proximidade temporal `+0.10`) produzem 0,4/0,95 — a spec
  §1.2 diz que o score é sempre uma âncora. Trocar por "subir um nível" muda scores.
- **Evidência como texto solto.** P6 (`res.evidencia = [("…")]` — os parênteses não fazem tupla) e X13 gravam
  `list[str]` em vez de `{fonte, trecho, hash, capturado_em}` (sem sha256). Os consumidores toleram texto; os
  testes de P6/X13 fazem `"…" in r.evidencia[0]`, então corrigir exige mudar 8 asserções.
- **Defeitos de lógica achados pela auditoria (não são refatoração):**
  - X7 T1 "dupla correção": `anos_reaj_indice ⊂ anos_recomp`, então `dupla` vale sempre que houver
    recomposição com índice; dá `forte` com ≥2 recomposições em anos diferentes.
  - X9 T2: supressão "rente" mas DENTRO do teto sobe a crítico com `anuencia is False`; a docstring diz que o T2
    vale só acima do teto.
  - X11: "rubrica de pertinência indisponível" entra na lista de sinais e conta para o `len(sinais) >= 2` —
    LLM fora do ar + dissimilaridade fraca viram `confirmado`.
  - X12: `int(abs(q)) % 5 == 0` conta 0,25 como redondo e 7,5 não.
  - X1: soma o acréscimo do art. 125 com regra própria (`_conta_no_teto`, inclui tipo "objeto") em vez de
    `limites_aditivo.acrescimo_computavel` (que X9 e EST usam) — duas regras para o mesmo número.
  - X13: nenhum produtor de `alteracoes_controle`/`cessao_contratual`/`recebido_ate_alteracao` (só os testes) —
    está no REGISTRO e sempre devolve `nao_avaliavel` ("construído, testado, nunca rodado").
  - C8: `montar_ctx_servidores` sem chamador e o rebaixamento "casou só por NOME" (linhas 196–212) inalcançável
    desde que 19/11 passou a descartar par não corroborado por CPF; o motivo `nao_avaliavel` ainda manda "usar
    `montar_ctx_servidores`". Apagar muda o texto do motivo — junto com a revisão do C8.
- **E1/E7 × `editais/teste_finalistico`**: os tetos de 10% (capital/PL), 50% (atestado) e 1% (garantia) existem
  nos três, citando normas diferentes ("art. 69 §3º" no E1; Súmula TCU 275/art. 58 §1º na régua). A auditoria
  leu o teto de 10% como §4º do art. 69 — conferir no texto oficial antes de unificar a citação.
- **E2 — tabela do art. 55**: `tecnica_e_preco`/`melhor_tecnica` está em 15 dias úteis; a leitura da auditoria
  é 35 (art. 55, IV); faltam contratação integrada (60) e semi-integrada (35). O próprio comentário pede
  "Confirmar". Não conferido na fonte.
- **`rodar_*` com listas de ids à mão** (`__init__.py`): detector novo precisa entrar no REGISTRO **e** na lista
  da fase. Redesenho natural: atributo `fases` em cada classe (P2 está em duas). Não feito nesta passada.
- **X4 — limites do art. 86** (`LIMITE_ADESAO_INDIVIDUAL`, `LIMITE_TOTAL_ADESOES`) moram no detector, e
  `padroes/carona_acima_do_limite.py` importa o detector para ler a norma (código estável dependendo do volátil).
  Mover para uma régua `limites_*` mexe em `padroes/` (fora do escopo).
- `base.painel_adversarial`: a variável `quorum` não tem efeito (`len(refutam) >= maioria` decide sozinho) e a
  docstring promete "quórum sobre as lentes que responderam". Sem chamador em produção.
- **Ano anterior à Lei 14.133 na régua de dispensa.** `limites_dispensa.limite_dispensa` devolve o teto mais
  recente para ano fora da tabela; P4 tem guarda própria (pré-2021 → None), P6 e P7 chamam a régua direto e
  aplicariam o teto de 2026 a uma dispensa de 2019. A guarda é da régua — mudar a régua muda P6/P7 (e
  `rules/generate_alerts`).
- **P4 sem exercício usa 2024** (`_DEFAULT_EXERCICIO`) em vez de `nao_avaliavel`.
- **C7 compara datas como texto** (`data_referencia.strip()[:10]` contra `data_inicio`/`data_fim` da sanção):
  certo só se tudo vier ISO; `date`/`datetime` levanta `AttributeError`. Passar por `para_data` depende de
  conferir o formato gravado em `sancoes_federais`.
- **C9 mede TAC sobre `ordens_bancarias` (TFE) sem excluir OB anulada** (`reporting/detector_tac.tac_por_cnpj`).
  A régua `_ob_paga` é do SIAFE; o TFE não tem os campos. A observação "TAC" só existe no TFE (docstring do C9).

## 9. Fora do escopo (anotado, não mexido)

- `compliance_agent/varredura_orgaos.py:140,306` importa `c8_servidor_socio._norm` (privado); `p7` e `est`
  importam `varredura_orgaos._persistir` (privado).
- `p7_direta_de_risco.py:41` importa `lex_redflags._eh_servico_continuo` (privado de módulo do Lex).
- `p3_sobrepreco.py:96` importa `precos_extract._norm` fora do `try` que protege o resto do módulo.
- `coletor_ata` importa `rodizio_grafo._PREAMBULO`/`_cnpj_dv_ok`, e `rodizio_grafo` importa de volta
  `coletor_ata._RX_ATA_MARCADOR` (ciclo por import tardio). `editais/clausulas.py` e
  `editais/coletor_propostas.py` importam funções privadas de `coletor_edital`/`coletor_ata`. Os dois coletores
  fazem I/O dentro do pacote de detectores; mover exige reexportar para 7 importadores e ~12 testes.
- `coletor_edital` importa `rodar_edital/julgamento/planejamento` no topo: quem só quer as regex
  (`editais/clausulas`) carrega os 41 detectores. Docstring cita `direcionamento_cerebro.gerar_sync`
  (Gemini→Groq→Cerebras); o caminho LLM do coletor só roda com `--llm` na CLI.
- `reporting/detector_tac._severidade` deveria ser pública (C9 e o relatório a usam).
- Normalizadores de nome/dígitos copiados (C6 `_norm_nome`, C8 `_norm`, E5 `_norm`, C7 `_limpa`, E4
  `_norm_cnpj`, J8 `_dig`, P2 `_norm_tel`) — há `identidade_pessoa.normalizar_nome`, `base.sem_acentos` e
  `intel_base.so_digitos`, mas as semânticas diferem (maiúsculas/minúsculas, pontuação, espaço) e unificar muda
  casamentos. Conversores `_num` (7 versões) idem: J2/J3 recusam texto, C6 devolve 0,0, X12 recusa ≤ 0 — são
  contratos diferentes, não cópias.
- As definições de "ente público" (`_PREFIXOS_ENTE`, `eh_orgao_publico`, `eh_nao_fornecedor`,
  `cruzamentos_intel._SQL_NAO_PUBLICO`) e as naturezas 2011/2038 copiadas (rules.md §7–8): **nenhum** dos 47
  arquivos de `detectores/` usa uma delas — a pendência não passa por esta área.

## 10. Segunda volta (revisão independente, etapa 5 da skill)  `[feito]`

- O atalho de teste da rubrica ainda estava escrito à mão em 7 lugares (X1 ×2, X4 ×2, E6 ×2, J5): passam a usar
  `nivel_rubrica`, mesmas chaves (`trecho`, `similaridade`, `precoce`). X7 grava em `rubricas_alea` o nível de
  `nivel` ou `classificacao` (ver §2).
- Log corrigido: o defeito do `datetime` intacto era também do P4; X13 perde ISO compacto; X7 mantém o prefixo
  quando o texto não é data (§3).
- Mapa do `base.py` restaurado e corrigido (ver §7).
- Comentário dos apelidos `_to_date`/`_to_datetime` (o próprio E2 também os usa) e linhas em branco que sobraram
  em `base.py` onde saiu `_parse_json`.
- A revisão não achou import quebrado (varredura `ast` de todo o repositório por nomes importados de
  `compliance_agent.detectores.*`) nem ciclo novo (`cruzamentos_intel`, `reporting.detector_tac` e
  `llm.json_resposta` não importam `detectores`).
