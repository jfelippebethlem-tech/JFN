# Decision log — untangle de `compliance_agent/sei/` (20/11/2026)

Escopo: os 27 módulos de `compliance_agent/sei/` (porta do acervo, leitores de manifesto/cache, classificadores,
extratores e detectores sobre os documentos do processo). Escolhas do dono: **Comentários = sim** (só os que
repetem o código saem; medição datada, decisão do dono e porquê de workaround ficam — o SEI tem muitas armadilhas
registradas), **Testes = não**. Restrições da casa: formato do manifesto e dos arquivos do acervo não muda; o que o
painel e as filas leem não muda; comportamento igual salvo defeito provado; validação empírica no acervo real
antes e depois (só leitura; nenhum acesso ao SEI).

Formato igual a `rules.md`: o fix fica acima dos problemas que resolve. `[feito]` = aplicado nesta passada;
`[pendente]` = precisa de decisão do dono ou muda número publicado; `[fora do escopo]` = anotado só.

Prova de equivalência: `harness.py` (caixa de areia só-leitura, cópia do código ANTES e DEPOIS com `data/`
apontando para o acervo real) roda, em 42 pastas reais — 30 sorteadas + os controles citados nos módulos
(070002/006145/2024 com 791 documentos, 070002/000991/2022 com órfãos, 080001/000744/2024 com documentos
alheios, 270131/000548/2023, 080007/001365/2024, 460001/000779/2023), as 2 pastas de nome antigo
(`330020_0007`, `SEI_330020_0007`), uma pasta sem manifest e uma com `docs: []` — os leitores e extratores
tocados: `arquivos_declarados`/`orfaos`/`docs_com_conteudo`, `manifesto_norm.carregar`/`normalizar`/
`captura_integra`, `encerramento.situacao_do_processo`, `dossie_fracionado.carregar_documentos`,
`relacionados.relacionados_de`/`textos_do_relacionado`, `reuso_documento_execucao.documentos_de_execucao`/
`contratos_do_processo`/`textos_de_contrato`, e sobre os documentos montados como no `processo_360`:
`conferencia_captura.conferir`, `instrumento_assinatura.avaliar`, `fiscalizacao.avaliar`,
`sintese_global.sintetizar`, `doc_juizo.alvo_ordenado`, `documentos_alheios.separar_alheios`. Saídas comparadas
campo a campo (texto por sha256). Resultado por lote: lote 1 (porta do acervo) — 36 das 36 pastas de nome padrão
IGUAIS nos 21 campos; muda só o rótulo `processo` do `encerramento` nas 6 pastas de nome fora do padrão (ver §1);
lote 2 (doutrina do parecer) — 0 diferença; lote 3 (quais N do pai) — iguais as 30 pastas com até 40
documentos, mudam as 12 com mais (o que o conserto pretende); lote 4 (código morto) — sem leitor; lote 5 (cópias restantes) — 0 diferença; lote 6 (número de contrato) — 1
diferença, a do I5 no controle positivo (§6).
Testes casados (61 arquivos: os que importam os módulos tocados + catracas): 792 passam com o lote 1, 843 da
seleção do lote 2; a única falha (`test_sei_contexto_unico`, logins do `tools/`) já falhava antes.

## 1. Uma porta só para o acervo em disco: `acervo_texto`  `[feito]`

`acervo_texto` já era a "porta única para o TEXTO"; passa a ser também a única para o que o texto pressupõe:
`RAIZ` (absoluta; `JFN_SEI_ARQUIVO` redireciona), `numero_para_pasta`/`pasta_para_numero`, `manifesto(pasta)`
(`None` = ausente, ilegível ou não-objeto — quem chama declara o que faz com isso) e `declarados(pasta)`, os
pares `(entrada do manifesto, .txt)` de que `arquivos_declarados` é a projeção. Os apelidos `manifesto_norm._BASE`
e `encerramento.ACERVO` ficam (os testes os redirecionam), mas apontam para `RAIZ`.

- Raiz do acervo definida três vezes, de três jeitos:
  - `manifesto_norm._BASE` relativo ao módulo e surdo a `JFN_SEI_ARQUIVO` — quem redirecionava o acervo
    (teste do `sei_consultar`, réplica) via `encerramento` e `sei_consultar` num lugar e o 360 noutro;
  - `encerramento.ACERVO = Path("data/sei_arquivo")` relativo ao DIRETÓRIO CORRENTE: chamado de fora da raiz do
    repo, todo processo saía "INDISPONÍVEL: sem manifest no acervo" — falha de caminho vestida de ausência
    de dado (hoje o único chamador, `tools/sei_analise_em_serie`, roda da raiz, então não disparou);
  - `reuso_documento_execucao.BASE_ACERVO` relativo ao módulo (mantido: é só o padrão da CLI `--base`).
- Número SEI → pasta calculado de dois jeitos: `manifesto_norm.carregar` (regex: tira `SEI-`, todo não-dígito
  vira `_`) e `relacionados.numero_para_pasta` (`replace("SEI-")`, `replace("/")`); pasta → número de dois
  jeitos: `relacionados.pasta_para_numero` (regex) e `encerramento` (`"SEI-" + replace("_", "/")`). Para número
  bem formado dão o mesmo; vale o mais robusto (o do `manifesto_norm`, que acha as pastas antigas
  `330020_0007` a partir de "SEI 330020/0007").
- `manifest.json` lido e parseado à mão em 9 lugares do pacote, cada um com o seu `except`:
  `acervo_texto.arquivos_declarados`, `manifesto_norm.carregar`, `encerramento.situacao_do_processo`,
  `dossie_fracionado.carregar_documentos` (lia o manifest DUAS vezes: uma para os títulos, outra via
  `arquivos_declarados`) e cinco funções do `reuso_documento_execucao` (`documentos_de_execucao`,
  `contratos_do_processo`, `credor_do_processo`, `_pastas_com_execucao`, `textos_de_contrato`). Manifest que
  fosse lista (JSON válido, não-objeto) derrubava `arquivos_declarados` e `carregar` com `AttributeError`/
  `TypeError` — hoje 0 casos no acervo; a porta devolve `None`.
- `dossie_fracionado` casava título por NOME-BASE do arquivo num dicionário à parte; agora o título vem da
  própria entrada do manifesto que aponta o arquivo.
- Efeito medido nas pastas de nome fora do padrão (`330020_0007`, `SEI_330020_0007`, `406_2025`,
  `_orfaos_residuo`, `_substituido`): `encerramento` rotulava "SEI-SEI/330020/0007", "SEI-/orfaos/residuo";
  agora devolve o nome da pasta como veio (regra do `pasta_para_numero`). Nenhum dos dois é número SEI, então
  não casa com `sei_arvore` em nenhum caso; encerrado/fonte/n_docs iguais. `numero_para_pasta("SEI_330020_0007")`
  passa a achar a pasta `330020_0007` (antes devolvia o nome intacto).

## 2. A doutrina do parecer num lugar só  `[feito]`

`instrumento_assinatura` já era a casa da doutrina do controle prévio (o comentário dizia "a doutrina mora num
lugar só"); o conjunto de tipos que valem como parecer vira `TIPOS_PARECER` lá, e os padrões que outros módulos
importavam por nome privado viram públicos.

- `{"parecer", "parecer_juridico", "manifestacao_juridica", "cota_juridica"}` em três cópias
  (`instrumento_assinatura._TIPOS_PARECER`, `conferencia_captura._TIPOS_PARECER`,
  `sintese_global._TIPOS_CONTROLE_PREVIO`) e uma quarta fora do pacote (`parecer_cumprimento`).
- `sintese_global` importava `_RE_CONTROLE_JURIDICO` e `_RE_NAO_E_PARECER`, e `fiscalizacao` importava
  `_data` e `_norm` de `instrumento_assinatura` — dependência de internos de outro módulo, sem nada que avisasse
  quem os mexesse.

## 3. Quais N documentos do processo-pai  `[feito]`

`relacionados.textos_do_relacionado` (fonte dos responsáveis vindos do processo-pai, em `tools/sei_agentes_sweep`)
lia `arquivos_declarados(pai)[:40]` — os 40 PRIMEIROS da árvore, que começa pelos despachos de abertura. É a
lição registrada no PLAYBOOK ("quais N, nunca só quantos") que não chegou aqui.

Medido em 20/11/2026 em 300 processos sorteados do acervo com mais de 40 documentos (fiscal/gestor pela
`agentes_publicos.extrair_agentes`): em **28** o único fiscal/gestor identificável estava depois do 40º.
Regra nova: lê o pai inteiro do disco (é texto local, não browser), escolhe primeiro os documentos que citam
designação, fiscal, gestor, ordenador ou portaria, completa com os demais na ordem da árvore, corta em
`max_docs` e devolve na ordem da árvore (a ficha cita o primeiro documento em que o agente aparece). Comparada
com o corte antigo nos mesmos 300: fiscal/gestor achado em **153** processos contra 132 (+21), ordenador em
**32** contra 24 (+8), **zero** agentes perdidos. Arquivo ilegível deixa de ocupar vaga no orçamento.

## 4. Sem razão própria para existir  `[feito]`

- `indice.podar_cache` (e `_CACHE`): nenhum chamador desde que nasceu (o próprio `cache_arquivo` e
  `manutencao.comprimir_cache_sei` já o registravam). Se alguém o ligasse, apagaria PDF/HTML de
  `data/sei_cache/` com mais de 24 h — íntegras incluídas — contra a ordem do dono "nada é apagado; tudo em
  arquivos menores", que `comprimir_cache_sei` cumpre. O docstring do `indice` dizia o contrário da regra.

## 5. Cópias que sobravam depois da porta  `[feito]`

- `acervo_texto.normalizar` (sem acento, casefold, espaços colapsados) é a definição; `instrumento_assinatura`
  tinha cópia byte a byte idêntica e `fiscalizacao` a importava de lá por nome privado.
- `documentos_alheios.separar_alheios` convertia número/pasta à mão (`replace("_", "/").replace("SEI-", "")`);
  agora pela porta (`numero_para_pasta`).
- `reuso_documento_execucao.BASE_ACERVO` (padrão do `--base`) era uma terceira raiz, surda a `JFN_SEI_ARQUIVO`;
  agora `acervo_texto.RAIZ`. A porta, importada 4× dentro de funções, passa a ser importada no topo.

## 6. Número de contrato: um padrão, uma comparação  `[feito]` — defeito do I5

`instrumento_assinatura.RE_NUM_CONTRATO` e `num_contrato` são a fonte; `sintese_global` importa o padrão.

- O padrão `contrato … (\d{1,4}/\d{4})` estava copiado em `instrumento_assinatura._RE_NUM_CONTRATO` e
  `sintese_global._RE_CONTRATO`.
- A normalização divergia: `sintese_global._num_contrato` tirava o zero à esquerda ("016/2023" = "16/2023",
  falso positivo medido quando a síntese foi ligada ao 360) — e já não tinha chamador depois que o G2 saiu;
  `instrumento_assinatura._num` só tirava espaço. O I5 (`declaracao_de_outro_contrato`) seguia acusando
  "declaração de OUTRO contrato" pela grafia. **Medido em 20/11/2026 em 3.000 processos sorteados do acervo:
  29 disparos do I5, dos quais 13 (45%) eram só zero à esquerda** ("017/2022" × "17/2022", "88/2023" ×
  "088/2023", "15/2024" × "015/2024"…); comparando sem o zero, 16 disparos e **nenhum novo**. A comparação
  agora é por `num_contrato`; a evidência continua mostrando o número como está escrito.
- No próprio controle positivo do I5 (270131/000548/2023, Contrato 016/2023) o defeito trocava a prova: o I5
  antigo disparava na "Declaração do Ordenador de Despesas 74776383", que fala do contrato "16/2023" — o MESMO
  ajuste; o novo dispara na "Declaração segue minnuta padrão (74778812)", sobre o contrato 04/2022 — o achado
  real descrito no módulo. É a única diferença das 42 pastas do harness neste lote.

## 7. Pendente  `[pendente]`

- **Falha que vira "não consta"** — sem caso medido hoje, mas o consumidor leria como ausência:
  - `reuso_documento_execucao.exportar`/`documentos_de_execucao`: manifest ilegível → `([], [])`, a pasta some do
    corpus sem linha `INDISPONÍVEL` (0 manifests ilegíveis em 10.741 pastas hoje). `exportar` pula também pasta
    SEM manifest que `declarados()` leria pelo diretório.
  - `cotacoes_acervo.montar_cotacoes`: sem `receita_estab.db` devolve `[]`; no `processo_360` (`len(cot) < 2`)
    o P2 simplesmente não roda e nada entra em `indisponiveis`.
  - `relacionados.relacionados_de`: cache ausente/ilegível vira `[]` — `tools/sei_analise_em_serie --fila-pais`
    e `tools/sei_agentes_sweep` leem como "não tem pai"; `textos_do_relacionado` sem a pasta do pai devolve `{}`
    e "pai não capturado" fica igual a "pai sem fiscal". Pede um terceiro estado no retorno (muda a assinatura
    que dois `tools/` consomem).
  - `instrumento_assinatura.avaliar`: detector I1–I7 que levanta exceção vira "sem achado" (catraca de excepts
    conta a linha); `office_texto` devolve `""` tanto para "não é Office" quanto para falha do soffice;
    `ocr_docs.ocr_documento` devolve `""` para fonte inválida, lib ausente e documento em branco (documentado,
    22 chamadores).
  - `dossie_fracionado.carregar_documentos`: arquivo que dá `OSError` some sem entrar em `docs_vazios`, e o
    aviso "documento(s) sem texto" subconta.
- **Fallback morto com formato errado**: `man.get("processo") or pasta.name` em `doc_juizo.julgar_docs` e em três
  funções do `reuso` devolveria `270006_012971_2025` onde o resto usa `270006/012971/2025`; hoje 10.738 de
  10.738 manifests trazem `processo`, então nunca dispara.
- **Mais cópias que DIFEREM de propósito ou sem medição** (unificar muda o que casa):
  - número de processo SEI: seis regex com âncoras diferentes (`conferencia_captura` ×2, `documentos_alheios`,
    `relacionados`, `reuso`, `sintese_global`);
  - CPF: `extrair_cpf` (com contexto), `instrumento_assinatura._RE_CPF` (qualquer 11 dígitos), `reuso._RX_CPF`
    (aceita máscara);
  - valor R$: `sintese_global._valor` e `indicios_dossie` (teto de 15 caracteres só num), `extrator_precos._num_br`
    (aceita negativo); data: `sintese_global._data`/`_cmp` × `instrumento_assinatura.data_br`;
  - rodapé de assinatura: `instrumento_assinatura._RE_ASSINATURA` × `reuso._RX_ASSINATURA` (um captura cargo, o
    outro não);
  - normalizadores de texto com regras próprias: `fases._norm`, `classificador_doc._n`, `conluio_propostas._n`,
    `doc_juizo._norm_txt` (sem `strip`), `extrator_precos._norm_cab`, `reuso._sem_acento`,
    `agentes_publicos._sem_acento` (NFD/Mn);
  - conjuntos "instrumento/ato decisório": `instrumento_assinatura._TIPOS_INSTRUMENTO`/`_TIPOS_AUTORIZACAO`,
    `sintese_global._TIPOS_DECISORIOS`, `reuso._TIPOS_DO_CREDOR`; "tem preço": `cotacoes_acervo._TIPOS` ×
    `classificador_doc.DOCS_COM_PRECO`.
- **Só os testes chamam**: `cache_arquivo.eh_estado_vivo`, `classificador_doc.deve_guardar_texto`,
  `dossie_fracionado.prompt_reduce`, `indice.ja_indexado`. Com Testes = não, ficam (apagá-los quebra os testes).
- `manifesto_norm.captura_integra` devolve `n_txt` contando `texto/*` com órfãos (só evidência; diverge de
  `declarados`). `manifesto_norm._TIPOS_FINOS` lê `fases._REGRAS` (privado).
- `reuso.credor_siafe` importa `cruzamentos_intel._ob_paga` (privado, mas é a régua canônica de OB paga da casa).
- `navegador.abrir_processo` classifica `nenhum_resultado` procurando "nenhum resultado encontrado" no texto da
  página; o PLAYBOOK registra que essa frase é TEMPLATE ESCONDIDO na tela de busca. Se `texto` vier do HTML e
  não do texto visível, a falha da busca vira "processo não localizado". Coberto por teste; só
  `tools/pilot_sei_avaliar` usa. Medir num cache real antes de mexer.

## 8. Fora do escopo (anotado, não mexido)

- Fora de `sei/`: 62 arquivos de `compliance_agent/`, `tools/` e `rotas/` citam `manifest.json` e 18 usam
  `replace("/", "_")` (contagem por grep; nem todos sobre o acervo) — o próximo passo é apontá-los para
  `acervo_texto`.
  Exemplos: `processo_360.avaliar_pasta` relê e reparseia o manifest que `manifesto_norm.carregar` acabou de ler;
  `tools/sei_dossie_md` e `tools/sei_analise_em_serie` têm `ACERVO` relativo ao diretório corrente.
- `rotas/produtos.py`, `tools/sei_agentes_sweep.py` e `tools/sei_analise_em_serie.py` importam
  `numero_para_pasta`/`pasta_para_numero` de `relacionados` (que agora só os reexporta de `acervo_texto`).
- `parecer_cumprimento._TIPOS_CANONICOS_PARECER` é a quarta cópia de `TIPOS_PARECER`.
- `cotacoes_acervo._RECEITA` monta a raiz do repo por `parents[2]` (outro banco, não o acervo).
- `tests/test_sei_contexto_unico.py::test_todos_os_logins_usam_o_contexto_compartilhado` falha antes e depois
  (conta caminhos de login em `tools/`).
