# Decision log — untangle dos módulos soltos da raiz de `compliance_agent/` (20/11/2026)

Escopo: os 179 módulos `.py` soltos na raiz de `compliance_agent/` (não os subpacotes). Escolhas do dono:
**Comentários = sim** (só saem os que repetem o código; medição datada, decisão do dono e norma ficam),
**Testes = não**. Restrições da casa: títulos de alerta, chaves lidas pelo painel/rotas e esquema de banco não mudam;
OB/pagamento só pela régua `cruzamentos_intel._ob_paga`; comportamento igual salvo defeito provado.

Formato igual a `rules.md`/`padroes.md`: o fix fica acima dos problemas que resolve. `[feito]` = aplicado nesta
passada; `[pendente]` = muda número/saída, pede decisão do dono ou é redesenho; `[fora do escopo]` = anotado só.

Grafo de dependências (script `ast` sobre o repo inteiro, 20/11): 179 módulos; os mais importados são
`cruzamentos_intel` (88 importadores), `direcionamento_cerebro` (36), `siafe_ob_orcamentaria` (33),
`limites_dispensa` (23), `processo_360` (22), `envfile` (22), `limites_aditivo` (20). 264 imports de símbolo
privado entre módulos da raiz (67 deles de `cruzamentos_intel._ob_paga`, a régua canônica — aceito). 8 módulos
sem nenhum import (ver §9).

Prova de equivalência: amostra só-leitura do `compliance.db` real (800 credores de `ob_orcamentaria_siafe`,
metade CPF e metade CNPJ, 500 nomes de credor — 200 com 11 dígitos no nome, 300 valores) + 600 sequências
aleatórias de 11/14 dígitos + bordas (`None`, vazio, pontuação, máscara); cada função tocada rodada com o código
de antes e o de depois, saída comparada item a item.

## 1. CPF/CNPJ: dígito verificador e máscara PAD-04 numa fonte só (`cpf_cnpj.py`)  `[feito]`

- `cpf_cnpj` ganha `mascarar_cpf` (PAD-04, dígitos 4–9), `mascarar_doc` (CPF mascarado, o resto como veio) e
  `mascarar_cpf_no_texto` (todo CPF solto num texto). `qualidade/verificadores` reexporta `mascarar_cpf`;
  `reporting/intel_base.fmt_doc` importa de `cpf_cnpj` (relatório não precisa depender de `qualidade`).
  - `periodo.mascarar_doc` e `foto_quantitativo._cnpj_mascarado` eram a mesma função (os nomes ficam: `periodo_fontes`
    e `tests/test_foto_quantitativo` os chamam).
  - `cpf_corpus.sem_cpf` e os dois `log` de `cpf_externo` montavam a máscara à mão.
  - `triagem_alertas.mascarar_cpf` e `padroes/_comum.mascarar_cpf`: mesma regex e mesmo corpo, duas cópias.
  - `rodizio_grafo._cnpj_dv_ok` era o quinto módulo 11 do CNPJ; `detectores/coletor_ata` o importava (privado de
    outro módulo). Os dois usam `cpf_cnpj.cnpj_valido` (as regex dos dois só deixam passar 14 dígitos crus, então
    a pontuação que `cnpj_valido` ignora nunca chega).
  - `cpf_corpus.cpf_valido` recalculava o DV por `resolucao_cpf._dv_cpf` (privado) → `cpf_cnpj.cpf_valido`;
    `_digitos` vem de `cpf_cnpj` (em `cpf_corpus` e `cpf_externo`).
- **Defeito (LGPD, PAD-04):** máscara de CPF em DOIS formatos — `***.456.789-**` (PAD-04, a da casa e a do QSA)
  e `123.***.***-01` (D1–D3 + DV). O mesmo CPF exibido nos dois formatos fica inteiro. Usavam o segundo:
  `pericia_contabil.mascarar_doc`/`mascarar_textos` (PDF da perícia contábil e `vinculo_ob_contrato`, que grava
  `objeto` mascarado), e — via `osint/vinculos.mascarar_cpf` — `governo_couto.mascarar_texto`,
  `comissao_orcamento._doc` e `proveniencia_manchetes.mascarar_nomes` (que se dizia PAD-04). Todos passam a PAD-04.
  - `pericia_contabil.mascarar_textos` continua mascarando só CPF formatado (não amplia o que casa).
  - `tests/test_pericia_contabil.py`: quatro asserções trocam `123.***.***-01` por `***.456.789-**` (o defeito
    corrigido; nenhuma regra nova).
- Medição: `periodo.mascarar_doc`, `cpf_corpus.cpf_valido`/`sem_cpf`, `qualidade.verificadores.mascarar_cpf`,
  `intel_base.fmt_doc`, `triagem_alertas.mascarar_cpf` e o DV de CNPJ (`_cnpj_dv_ok` × `cnpj_valido`, 701 entradas):
  **iguais** em 100% da amostra. `pericia_contabil.mascarar_doc`: mudam as 703 entradas de 11 dígitos (o formato
  corrigido), as 707 restantes iguais. `foto_quantitativo._cnpj_mascarado`: mudam só 2 entradas inteiras (int) que
  antes levantavam `TypeError` (o caller passa texto do banco).
- Fica (ver §8): `osint/vinculos.mascarar_cpf` e `territorio/api._doc` (subpacotes) ainda mostram `123.***.***-01`.

## 2. "R$ 1.234,56" tem um dono: `reporting/intel_base.reais`  `[feito]`

- Seis cópias literais de `_moeda` (mesmo `try`/`except`, mesmo formato) em `auditoria_contrato`, `rodizio_temporal`,
  `investigacao_orgao_dd`, `rede_fachada`, `investigacao_dd`, `sede_google` → `from …intel_base import reais as
  _moeda` (o padrão que `reporting/detector_tac` já usava). O nome `_moeda` fica porque `tools/endereco_sweep` e
  `tools/dd_sweep_orgao` o importam de `investigacao_orgao_dd`/`investigacao_dd`.
- Medição: as seis, 307 valores reais + bordas (`None`, vazio, texto, negativo, 1e12): **iguais**.

## 3. Natureza jurídica estatal (2011/2038) só em `credor_institucional`  `[feito]`

- `credor_institucional.NATUREZA_ESTATAL` (código → rótulo) passa a ser a fonte; `_NATUREZA_EXATA` a estende.
  - `esfera_orgao.NATUREZA_ESTATAL = {"2011", "2038"}` e `ordem_cronologica_siafe._NAT_ESTATAL` eram cópias
    (pendência de `rules.md` §8). O nome `esfera_orgao.NATUREZA_ESTATAL` fica (importado de lá).
- Medição: os conjuntos são iguais (`2011`, `2038`); só membership (`in`) é usado nos dois.
- Fica: `tools/agente_publico_reverso.e_estatal` (tools/ não importa o pacote; anotado em §8).

## 4. Caminho do banco pela porta da casa (`collectors/arquivos`), não pelo diretório corrente  `[feito]`

- A casa já tem `collectors/arquivos.dir_dados()`/`caminho_db()` (JFN_DB > JFN_DATA_DIR > `<repo>/data`). Na raiz,
  76 módulos montam o caminho do `compliance.db` à mão, de cinco jeitos. Os que dependiam do DIRETÓRIO CORRENTE
  (`Path("data") / "compliance.db"` ou `"data/compliance.db"`) passam pela porta:
  - constante de módulo → `dir_dados() / "compliance.db"` (`cpf_corpus`, `acumulo_cargos`, `relacoes`,
    `resolucao_cpf`, `investigacao_orgao_dd`). `dir_dados` e não `caminho_db` de propósito: resolvida no import,
    `caminho_db` congelaria o `JFN_DB` temporário que o conftest põe em quatro módulos de teste;
  - `JFN_DB` com cauda relativa → `caminho_db()` (`fachada_doubt._DB`, `varredura_certames.DB_LEITURA`,
    `ponte_compra_contrato._ro`, `lex_render` na leitura de `sei_agentes`); `varredura_certames.DB_ACHADOS`
    (banco que ele ESCREVE) idem com `dir_dados() / "achados.db"`;
  - `rodizio_grafo.coletar_atas_do_corpus`/`_nome`/CLI: o padrão `"data/compliance.db"` vira `None` → `caminho_db`.
- **Defeito (cwd):** chamados de fora da raiz do repositório, esses módulos abriam/criavam `data/compliance.db`
  relativo ao cwd (sqlite cria arquivo vazio em modo escrita) ou não achavam o banco. Em produção nada muda: os
  serviços exportam `JFN_DATA_DIR=%h/JFN/data` e o cron faz `cd ~/JFN` — o arquivo resolvido é o mesmo.
- Medição: com `JFN_DATA_DIR=/home/ubuntu/JFN/data` e cwd `/home/ubuntu` (fora do repo), `relacoes._DB` resolve
  para o banco real e `rodizio_grafo._nome` acha o nome de 3 de 3 CNPJs da amostra (antes: caminho inexistente).
- Fica `investigacao_dd` (6 caminhos `"data/compliance.db"` dentro de funções): `tests/test_investigacao_dd.py:277`
  depende do cwd (`monkeypatch.chdir` + `data/compliance.db` no tmp) — mudar exige reescrever o teste (Testes = não).

## 5. Import de símbolo privado entre módulos: o que tem dono vira público no dono  `[feito]`

- `governo_couto._mascarar_tudo` era importado (privado) por `cge_confronto`, `governo_couto_regras` (3×),
  `pericia_contabil_rotina` e `rotas/pericias_rotinas` — os dois últimos com um `_mascarar` que só repassava.
  É a máscara de CPF aplicada a um payload inteiro: mora em `cpf_cnpj.mascarar_payload`; os wrappers saem.
  `governo_couto.mascarar_texto` fica como nome (é `cpf_cnpj.mascarar_cpf_no_texto`; o teste o chama).
- `direcionamento_cerebro._parse_json` só repassa para `llm/json_resposta.parse_json_llm` (o parser único da
  casa); `execucao_cerebro`, `parecer_cumprimento` e `tools/lex_pesquisa_internet` o importavam (privado, e de um
  detector volátil) → importam `parse_json_llm` direto. O `_parse_json` fica (uso interno e `test_jfn2_direcionamento`).
- `direcionamento_cerebro._com_fusao` (fusão grau do LLM × grau determinístico, usada por `execucao_cerebro` e
  `parecer_cumprimento`) → `com_fusao` (público; nenhum teste o importava).
- Correção que faltou no lote 1: `tests/test_rotinas_automaticas.py:355,366` exigiam `"456.789" not in` — isto é,
  fixavam o formato `123.***.***-01`; com a PAD-04 os dígitos 4–9 são justamente os visíveis. As asserções passam a
  exigir que o CPF inteiro não apareça e que a máscara PAD-04 apareça.
- Medição: `mascarar_payload` tem o mesmo corpo de `_mascarar_tudo`; `parse_json_llm` é o que `_parse_json` chamava
  (sem lógica própria). `mascarar_cpf_no_texto` passa a aceitar não-texto (`str()`), igual para texto.

## 6. Código sem chamador  `[feito]`

- Prova: script `ast` lista toda função/classe de topo da raiz cujo nome aparece UMA vez (a própria definição) em
  todo `.py/.js/.html/.yaml/.sh/.json/.toml/.service` do repo (incluindo `tools/`, `rotas/`, `static/`, `tests/`);
  depois `grep -w` nos `.md`/`.txt` e no crontab/systemd do usuário. Dez candidatos; apagados os sete sem papel:
  `detector_iss_retido._tem_moeda`, `parecer_cumprimento.para_json` (e o `import json` que só ele usava),
  `siafe_adf.adf_settle` (atalho de `wait_adf_sync`), `triagem_alertas.valor_do_alerta`,
  `analise_remotes.ler_analise`, `captcha_solver.solve_captcha_pil`, `fachada_doubt.coord_do_endereco`.
- Ficam (decisão de produto — "construído, nunca chamado", regra 8 da casa): `limites_de_fonte.explica_vazio`
  (o antídoto do "nada encontrado" que nenhuma peça usa), `lex_sancoes.calcular_multa_mora` + `MULTA_MORA`
  (norma curada), `cpf_externo.ProviderSituacaoCadastral` (citado em `docs/REFERENCIA-PROJETO.md`).
- Módulos sem nenhum import (`briefing`, `calibrar`, `coletar_obs_sessao`, `eval_groundtruth`, `sei_driver`,
  `siafe_login`, `siafe_ppr`, `siafe_session`): todos são CLI (`python -m …`, com "Uso:" no docstring), sem cron nem
  unit nesta VM; podem rodar à mão ou em outra máquina — não apagados (ver §8). `siafe_ppr` importa
  `coletar_obs_sessao._navegar_ob` por `__import__` (link escondido).

## 7. "Favorecido PJ" pela régua `intel_base.SQL_FAVORECIDO_PJ`  `[feito]`

- `ordens_bancarias.favorecido_cpf` traz CPF mascarado como `999.***.***-99` — também 14 caracteres. A régua da
  casa (`reporting/intel_base.SQL_FAVORECIDO_PJ`, criada no untangle de `reporting/`) exclui o `*`; a raiz ainda
  usava `length(favorecido_cpf)=14` sozinho em sete consultas (pendência de `reporting.md` §3):
  `cruzamentos_intel` (alvos "top favorecido" e capital irrisório), `rede_societaria.cnpjs_top`,
  `ninho_sala`, `rede_fachada` (raízes "nossas"), `relacoes._orgao` e `cruzamento.cidades_de_orgao` (este com
  alias `ob.`, filtro escrito no lugar).
- **Defeito medido (compliance.db real, 20/11):** `cruzamento.cidades_de_orgao` sem filtro de UG contava
  39.769 "fornecedores" e R$ 141.091.219.049,96 como universo da cobertura geográfica; 24.568 deles eram CPF
  mascarado. Com a régua: 15.201 fornecedores e R$ 138.517.225.784,81 — a cobertura por cidade estava subestimada.
  `ninho_sala`: 24.459 dos 39.591 "recebedores" eram CPF mascarado (trabalho jogado fora; o lookup de endereço
  não casava). `cruzamentos_intel` capital irrisório: 391 de 4.334. Top 300 de `cruzamentos_intel`/`rede_societaria`
  e top 20 de `relacoes._orgao` (15 maiores UGs + ITERJ): nenhum mascarado — saída igual.
- `rede_societaria.cnpjs_top` roda em DuckDB (não executado aqui, por regra da VM); a cláusula é SQL padrão.

## 8a. "Só os dígitos" escrito 20 vezes  `[feito]`

- Vinte módulos da raiz tinham `re.sub(r"\D", "", str(x or ""))` com nome próprio (`_dig`, `_digits`, `_digitos`,
  `dig`). Script `ast` conferiu corpo idêntico (um argumento, uma linha) antes de trocar cada um por
  `from compliance_agent.cpf_cnpj import digitos as <nome local>` — o nome fica porque outros módulos e `tools/` os
  importam (`investigacao_dd._digitos`, `identidade_pessoa._dig`, `governo_couto_regras.dig`).
  `ob_processo._dig` não tinha uso: saiu. Cinco `import re` ficaram sem uso e saíram.
- Fica: as outras 14 cópias estão em subpacotes (`providers/`, `osint/`, `detectores/`, `collectors/`…).

## 8. O que ficou da raiz, por prioridade  `[pendente]`

A passada parou por orçamento de tempo; a etapa 5 da skill (subagentes procurando o que sobrou) NÃO foi feita.

1. **Máscara fora da PAD-04 nos subpacotes** (LGPD — o mesmo defeito do §1): `osint/vinculos.mascarar_cpf` e
   `territorio/api._doc` mostram `123.***.***-01`; `tests/test_osint_vinculos.py:186` e `tests/test_territorio.py:459`
   fixam esse formato. Corrigir = trocar por `cpf_cnpj` e mudar as duas asserções.
2. **Quarta lista de "ente público"** `cruzamentos_intel._SQL_NAO_PUBLICO` (por NOME, em SQL) × `credor_institucional`
   (por natureza jurídica) × `engine._PREFIXOS_ENTE` × `pericia_sweep._fora_da_bateria` (importado como privado por
   `varredura_orgaos`, `tools/reprocessar_nao_avaliavel`, `tools/triagem_amarelos`). Unificar muda quem entra nos
   detectores de fracionamento — redesenho com medição de antes × depois por detector; decisão do dono.
3. **`llm/free_llm` importa `direcionamento_cerebro._gemini_keys`** (infra de LLM dependendo de um detector; é o
   kill-switch de cobrança do Gemini). Mover para `llm/` exige mudar os 7 `monkeypatch.setattr(DC, "_gemini_keys", …)`
   dos testes (senão o teste chamaria a chave real) — Testes = não.
4. **Caminho do banco**: ~60 módulos da raiz ainda montam `<repo>/data/compliance.db` à mão (absoluto, sem
   `JFN_DB`/`JFN_DATA_DIR`), e `_ro` (conexão só-leitura) tem 5 cópias (`cruzamentos_intel`, `grafo_comunidades`,
   `retro_auditoria`, `socio_na_folha`, `comparador_precos`). Os testes trocam `mod._DB` por `monkeypatch`; unificar
   pede resolver na chamada e reescrever esses testes. `investigacao_dd` (6× relativo ao cwd) preso a
   `test_investigacao_dd.py:277`.
5. **Família `lex_*`**: `lex`, `lex_render`, `lex_orgao`, `lex_analise_conteudo` importam ~25 privados de
   `lex_redflags` (`_RF`, `_ramo_objeto`, `_eh_servico_continuo`, `_grau`, `_anatomia`…), de `lex_sei_leitura` e
   de `lex_render`; `knowledge/catalogo_vicios` e `detectores/p7_direta_de_risco` também. É um pacote espalhado na
   raiz: o fix é `compliance_agent/lex/` com interface pública — vários testes importam os privados.
6. **Parsers de número BR** `float(s.replace(".", "").replace(",", "."))` em 11 lugares (`direcionamento_sinais`,
   `acervo`, `pulos_do_gato`, `execucao_fatos` 2×, `governo_couto`, `aditivo_autos`, `ob_processo`, `precos_extract`…);
   `collectors/formato.valor_br` devolve `None` onde estes levantam exceção — unificar muda o tratamento de erro.
7. **Normalizadores de nome**: `resolucao_cpf._norm` (importado como privado por `cpf_corpus`, `cpf_externo`,
   `reporting/conflito_pessoal_view`, `tools/desmascarar_cpf_externo`) tem 3 cópias idênticas (`relacoes`,
   `verificacao_endereco`, `acumulo_cargos`); `_sem_acento`/`_norm` idênticos em `direcionamento_sinais`,
   `execucao_sinais`, `objeto_similaridade`; `identidade_pessoa.normalizar_nome` é outra régua (só letras). Escolher a
   régua de nome da casa é decisão (muda casamento de nomes).
8. **Outros privados importados**: `resolucao_cpf._dv_cpf` (`cpf_externo`, `tests/test_cpf_corpus`),
   `cruzamentos_intel._norm_item`/`_mediana` (`comparador_precos`, `editais/indice_certame`),
   `varredura_orgaos._persistir` (`detectores/est_valor_contratual`, `p7_direta_de_risco`),
   `medida_item._norm` (`comparador_precos`), `investigacao_dd._marcadores_residenciais` (`fachada_doubt`).
9. **Sem chamador, decisão de produto**: `limites_de_fonte.explica_vazio`, `lex_sancoes.calcular_multa_mora`/
   `MULTA_MORA`, `cpf_externo.ProviderSituacaoCadastral`; módulos CLI sem import nem cron nesta VM: `briefing`,
   `calibrar`, `coletar_obs_sessao`, `eval_groundtruth`, `sei_driver`, `siafe_login`, `siafe_ppr`, `siafe_session`
   (conferir VM-2/it-campo antes de apagar).
10. Fora da raiz, anotado: `tools/agente_publico_reverso.e_estatal` (2011/2038, §3).

## 9. Riscos

- §1 e §7 mudam saída de propósito (formato de máscara; universo de "fornecedor PJ"). Linhas já gravadas com o
  formato antigo (`vinculo_ob_contrato.objeto`, JSON de rotina em `data/`) continuam com ele até a próxima rodada.
- §4: quem rodava esses módulos de fora da raiz SEM `JFN_DATA_DIR` e contava com o `data/` do cwd passa a ler o
  banco do repo. Nenhum caller assim foi achado (cron faz `cd ~/JFN`; serviços exportam `JFN_DATA_DIR`).
- Testes rodados só os casados com cada lote (VM com load 7–9); a suíte inteira em lotes (`tools/ci_lote.py`) não rodou.
