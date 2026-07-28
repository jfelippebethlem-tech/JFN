# Sessão 2026-07-28 (B) — A leitura que via 5% do processo, e a suíte que só passava nesta máquina

> Documento de fechamento. Registra o que passou a existir, o que foi medido, e — com o mesmo
> peso — os erros meus, inclusive os que outra máquina precisou me apontar. Um relatório que
> só lista acertos não serve para a próxima sessão decidir em que confiar.

---

## 1. O achado que orientou a sessão

A ficha de **SEI-070002/006145/2024** (INEA, desassoreamento, Contrato 36/2023, R$ 38,1 mi)
concluía:

> "o trecho fornecido não inclui a documentação da licitação que originou o contrato, nem
> comprovante de pagamento efetivo (Ordem Bancária)"

O processo tem **294 documentos arquivados aqui, 30 deles Ordens Bancárias**. A árvore tem
791 documentos; a leitura viu 36; a ficha citou 2.

### As três causas, todas de código

| # | causa | correção |
|---|---|---|
| 1 | `documentos[:40]` — corte por POSIÇÃO, e a árvore começa nos despachos de abertura | `ordenar_para_leitura`: os 40 são os de maior valor fiscalizatório |
| 2 | `classificador_doc` não conhecia **Ordem Bancária** → `outros` → texto descartado | tipo `ordem_bancaria`, valor médio |
| 3 | `encaminhamento` mandava **recapturar** processo já capturado em disco | `encaminhamento_com_acervo`: separa `reanalisar` de `recapturar` |

**Medido em 473 processos onde o corte de 40 morde:**

    documentos decisivos lidos ....... 3.032 → 6.472   (2,1×)
    peças de tramitação lidas ........ 15.888 → 12.448
    processos que PERDEM algo ........ 0

Cobertura do acervo: mediana 80%, mas **1.080 processos abaixo de 50%**, e os piores são os
maiores (700–950 documentos, ~5% lidos). Total: 105.888 documentos na árvore, 64.925 lidos.

**A lição, que não é sobre o SEI:** o bound de 40 estava certo e documentado; o que ninguém
tinha escolhido era o CRITÉRIO. Limite sem critério é amostragem por acaso — e uma amostra
dos despachos iniciais sempre vai concluir que "falta documentação". Onde a casa corta lista,
perguntar **quais** N, nunca só **quantos**.

## 2. Melhorar a régua não conserta o que ela já escreveu

O indício DV parou de contar o rótulo do roteiro às 14:34. Às 13:50, a nota de
SEI-420001/004984/2025 já dizia "4 divergência(s)" — três falsas: duas inconsistências que o
próprio texto declara **corrigidas por Termo de Rerratificação**, e uma "cláusula de
contraditório", que casou porque *contraditório* contém `contradi`. **81 das 145 notas**
nasceram antes do conserto.

`tools/sei_reindiciar.py` reavalia com as réguas de hoje, a custo ZERO de cota (o dossiê está
em `output/dossies/`; as réguas são código sobre o texto já citado). **43 notas saneadas,
nenhuma para mais.**

E o erro que isso expôs em mim: a 1ª versão comparava o NÚMERO de indícios e deu a
nota-motivadora como inalterada (3 antes, 3 depois), enquanto o DV dentro dela caía de 4 para
1. Só apareceu porque fui abrir o PRODUTO em vez de acreditar no meu próprio relatório.
Contagem igual não é conteúdo igual.

## 3. A suíte só passava nesta máquina — e isso escondia falha real

A VM-2 montou uma venv limpa e rodou. O que ela achou não é "problema de ambiente dela":

| achado | o que era |
|---|---|
| 8 erros de import na coleta | **10 pacotes** de produção não declarados, entre eles `fitz` — a leitura de PDF do SEI |
| suíte inteira morrendo antes do 1º teste | `asyncio.run(main())` solto no topo de **4 módulos**; dois deles mandam Telegram. Importar uma função pura abria Chromium e disparava captura real |
| `pytest` ausente | instalava `requirements.txt` com exit 0 e ainda assim não podia verificar nada → `requirements-dev.txt` |
| 4 falhas de `websocket`/`selenium` | extras OPCIONAIS por desenho; o TESTE é que transformava ausência em falha, soterrando a falha real |
| `ZeroDivisionError` em `bench_modelos:381` | código meu: com ZERO provas o piso virava 0, `len(notas) >= 0` dava "medido" |
| gate de citações em silêncio | sem o índice do TCU, "Acórdão 9999/2024" chegava ao destinatário **idêntico a uma citação conferida** |

O gate é o mais grave: `INDISPONÍVEL ≠ OK` acontecendo dentro do mecanismo que existe para
barrar citação fabricada, numa casa que já achou quatro acórdãos impossíveis por aritmética.

## 4. As 9 falhas crônicas: 8 eram o teste, não o código

Suíte permanentemente vermelha não é cosmético — foi ela que escondeu, hoje, a única falha nova
entre 24. Todas atacadas pela causa: comentário lido como comando (`systemctl --user` dentro de
`#`), golden de dado vivo revisado com conferência (2 OBs novas da EFATA, 197 fornecedores
inalterados = coleta incremental, não reescrita de histórico), teto do menu do Yoda (24→25,
depois de ler as 25 capacidades), dívida de `except: pass` (156→153, com 8 curados de verdade e
o `rglob` deixando de contar plugin de terceiro).

**Resta uma, e é bug real:** `test_ponte_cpf_mascarado_destrava_beneficio` passa isolada e falha
na suíte cheia — em DUAS máquinas. O traceback diz que `verificar_beneficios` nunca é chamado,
então o caminho morre antes, em `_wire_beneficios_pep`, que tem três saídas silenciosas.
Investigação em curso, dividida com a VM-2.

## 5. Capacidade sem tela é trabalho morto

`/api/responsaveis` nasceu ontem e nunca apareceu no painel. Exposta (aba **Responsáveis**,
esfera Estado), verificada com browser real: 7 responsáveis no processo do INEA, zero
`pageerror`. Três cuidados: **e-mail pessoal não vai para a tela** (o extrator deposita o
e-mail da assinatura no campo `cargo` — defeito à parte, registrado); ausência é **lacuna
declarada**, nunca "não há responsável" (em 97% dos processos a designação vive no processo de
contratação); e o render é declarado **antes** de `TABS`, porque `const` referenciado na
avaliação daria TDZ e mataria o boot em silêncio — foi assim que o cockpit ficou morto 13
versões.

## 6. Erros meus, registrados

- **`rsync -az tools/X.py vm2:~/JFN/` deposita na RAIZ.** Dei por entregue; a VM-2 rodou a
  suíte com código velho e eu ainda deixei 4 arquivos soltos na máquina dela. Protocolo novo,
  proposto por ela: caminho completo no destino e **confirmação por md5** antes de dizer
  entregue.
- **Guard de skip que mascarava.** A 1ª versão do guard do teste do systemd perguntava se
  `jfn.service` existe usando `_rodar`, que simula o ambiente pelado do cron — a doença que o
  guard cura. Resultado: skip numa máquina onde o serviço está ativo.
- **`logger` inexistente** no ramo de erro do extrator de preços: trocava a falha do gerador
  por `NameError`. Pego pelo teste do ramo de erro, antes do commit.

## 7. Commits

`da16392e` leitura por valor · `eec9d538` requirements · `6dda3036` import que abria browser ·
`309eb238` reindiciar · `6c70aad8` extra opcional · `+` bench/gate/cron, painel, catracas.

---

**Verificação:** cada correção tem teste que falhou antes. As 9 crônicas rodam juntas em 57
testes verdes. A suíte completa desta máquina fechou 3.786 passed / 9 failed antes das
correções; a da VM-2, 24 failed / 3.784 passed — e a diferença foi triada nome a nome.
