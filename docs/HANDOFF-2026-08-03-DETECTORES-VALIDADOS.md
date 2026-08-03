# Handoff — 2026-08-03 · leitura de originais, síntese global e validação caso a caso

> **O método que rendeu tudo nesta sessão:** abrir o processo, ler os documentos e comparar com o
> que o sistema concluiu. Todo achado real e todo falso positivo saiu daí — nenhum de ajustar
> limiar. Teste verde não pegou nada disso; ler a saída sobre o acervo real pegou.

---

## 1. Estado dos detectores — taxas MEDIDAS em 2.175 processos

| Detector | Disparos | Validado caso a caso? |
|---|---:|---|
| `C1_DOCUMENTO_CITADO_NAO_CAPTURADO` | 364 (16,7%) | ✅ sim — volume é real (teto de 40 docs/processo) |
| `I4_ORDINAL_INCOERENTE_COM_PRAZO` | 23 (1,1%) | ✅ com ressalva declarada no próprio achado |
| `I1_ORDINAL_DIVERGENTE` | **3 (0,1%)** | ✅ **sim — os 10 disparos abertos um a um (§2-A)** |
| `I2_AUTORIZACAO_ANTES_DO_PARECER` | **1 (0,0%)** | ✅ **sim — os 15 disparos abertos um a um (§2-A)** |
| `I6_QUANTITATIVO_DIVERGENTE` | 7 (0,3%) | ✅ sim (aeronaves 3×4 e 6×7) |
| `I7_APROVADOR_NAO_ASSINOU` | 5 (0,2%) | ✅ sim (Atos de Designação) |
| `I3_ATO_SEM_ASSINATURA_DA_AUTORIDADE` | 2 (0,1%) | ✅ sim |
| `I5_DECLARACAO_DE_OUTRO_CONTRATO` | 2 (0,1%) | ✅ sim |
| `G2_DOCUMENTO_DE_OUTRO_PROCESSO` | 384 (17,7%) | ✅ sim (TR e Autorizo de outro processo na pasta) |
| `G3_MESMA_PESSOA_CONTROLA_E_DECIDE` | 2 (0,1%) | ✅ sim |
| `G1_PAGAMENTO_ANTES_DO_CONTRATO` | 0 | armado; nenhuma OB anterior ao contrato no acervo |

**Não há mais detector amostrado.** A pendência declarada no handoff anterior (I1 e I2 lidos por
amostra, não documento a documento) foi fechada — é o §2-A.

> `I4` subiu de 16 para 23 porque passou a ler o ordinal por extenso ("SEGUNDO TERMO ADITIVO"),
> não porque afrouxou. Só 17 estão gravados em `processo_avaliacao`: a reavaliação desta sessão
> foi bounded aos 25 processos que carregavam I1/I2; o resto entra na próxima passada do `360`.

## 2. Falsos positivos derrubados — todos por leitura

| Detector | Antes | Depois | O que a leitura mostrou |
|---|---:|---:|---|
| G3 | 73 | 2 | "Parecer de Análise para Emissão DL" não é controle prévio; checklist não é parecer |
| G2 | 305→976 | 384 | dono adivinhado por frequência; sem âncora do rodapé, citação virava documento alheio |
| G1 | 202 | 0 | sobreposição de fases é rotina — paga-se ENQUANTO se executa |
| **I2** | **15** | **1** | §2-A |
| **I1** | **10** | **3** | §2-A |
| I3 | 3 | 2 | documento intitulado "MINUTA" é rascunho, não ato |
| C1 | 370 | 364 | "Telefone: 23809230" virava documento; ID citado que ESTÁ na pasta era cobrado |
| I6 | 9 | 7 | "5 (cinco) dias" lido como quantitativo do objeto |
| I7 | 7 | 5 | "de acordo com a legislação" e "meio do Processo Admi" lidos como nome de aprovador |

### 2-A. I1 e I2 abertos documento a documento

Cada linha abaixo é um documento que foi ABERTO e lido — não uma hipótese. Todos viraram teste de
regressão em `tests/test_instrumento_assinatura.py`.

**I2 · autorização antes do parecer — 15 → 1.** Seis causas distintas, nenhuma jurídica:

1. **A etiqueta do arquivo provava o documento.** O arquivo compacto prepõe ao `.txt` a linha
   `[título] (fase: … · tipo: parecer_juridico)`. A palavra `juridico` entrava no TEXTO, e o
   "Parecer de Análise para Emissão DL" (Fundação Saúde, Diretoria Administrativa Financeira,
   corpo inteiro: *"Procedida a Revisão do processo"*) passava no teste de manifestação jurídica
   pela própria etiqueta que se queria conferir. **O documento provava a si mesmo.**
   → ⚠️ **A etiqueta contamina qualquer regex que leia esses `.txt`.** Foi neutralizada dentro de
   `instrumento_assinatura`; os demais leitores do acervo NÃO foram auditados.
2. **Rótulo de campo de formulário lido como decisão.** Toda Nota de Autorização de Despesa traz
   impresso `39 - APROVO E AUTORIZO ORDENADOR / AUTORIDADE DELEGADA` como cabeçalho de campo —
   presente na NAD assinada e na não assinada. A NAD do setor de orçamento ("Apresentamos a
   dotação orçamentária solicitada") virava o ato do ordenador. 5 disparos.
3. **Peça que não é controle prévio.** Checklist (2×), Declaração de Conformidade com a
   minuta-padrão da PGE assinada por quem redigiu a minuta (3×), Ato de Designação de Servidor,
   Correspondência Interna sobre troca de marca. Mesma doutrina que já derrubara 71 do G3 — que
   agora vive num lugar só (`instrumento_assinatura`, importada pela `sintese_global`).
4. **Pedido lido como decisão.** "Despacho de Solicitação de Análise da NAD" = *"Encaminho o
   presente processo para confecção de NAD"*. O título mente nos dois sentidos: o "Despacho de
   Solicitação de Reserva Orçamentária" do INEA traz *"AUTORIZO a despesa"* e **é** o ato. Agora
   o critério é o verbo em 1ª pessoa, não o título nem o tipo.
5. **Comparação min×min em processo longo.** Um processo de 2022 a 2026 tem dezenas de NADs e
   vários pareceres: a NAD mais antiga é naturalmente anterior ao parecer mais recente. Rotina,
   não inversão.
6. **Parecer sem data legível ⇒ INDISPONÍVEL.** A afirmação é sobre o PRIMEIRO parecer; havendo
   parecer cuja data não se lê, o primeiro pode ser ele. 6 dos disparos eram disto — **e a causa
   é o §3**: o rodapé de assinatura mora no FIM da peça, e o corte em 20.000 caracteres o comeu.

**O que sobrou:** `270131/000548/2023` — o caso-semente, o único. Declaração do Ordenador de
16/05/2024 × Parecer 462 de 22/05/2024, ambos lidos por inteiro.

**I1 · ordinal divergente — 10 → 3.** Cinco causas:

1. **Ordinal colhido em qualquer passagem do texto.** O Contrato 36/2023 do INEA cita "PRIMEIRO
   TERMO ADITIVO" numa cláusula e era contado como o 1º aditivo, colidindo com o aditivo
   verdadeiro. Agora o ordinal é o que abre a fórmula de celebração — e, havendo fórmula sem
   ordinal antes dela, o documento é o contrato original, ponto.
2. **Extrato publicado no D.O. e apostilamento** contados como instrumento assinado (4 processos
   da UG 420001). Publicação é extrato; apostilamento é registro unilateral.
3. **Instrumento sem rodapé tratado como ausente.** Em `070002/001289/2022` o 2º aditivo estava
   na pasta, sem rodapé de assinatura eletrônica, e a minuta do 2º era acusada de órfã. Ausência
   de rodapé não prova ausência de ato.
4. **Minuta pendente e minuta superada tratadas como atropeladas.** Três situações que o achado
   confundia numa só: *atropelada* (minuta do 1º, assina-se o 2º dezoito dias depois — é o
   achado); *superada* (minuta do 2º, minuta do 3º, assina-se o 3º — a correção veio ANTES da
   celebração, é o controle funcionando); *pendente* (a minuta é a peça mais recente e nada foi
   assinado depois — processo em curso não é processo viciado).
5. **A mesma peça anexada duas vezes.** O 1º aditivo está na pasta como `Anexo SEI_…` e como
   `Anexo …_eDO`, com as MESMAS três assinaturas nas mesmas datas.

**O que sobrou:** `270131/000548/2023` (o caso-semente), `270099/000714/2022` (minuta do 1º em
11/03/2024, 3º TA assinado em 14/03/2024) e `270003/000382/2025` (duas cópias do 3º TA em
20 e 23/06/2025 — o achado agora DECLARA a hipótese de reemissão para colher assinatura faltante,
porque os assinantes de uma cópia contêm os da outra).

## 3. 1.969 documentos do acervo estão cortados em 20.000 caracteres — sem marca nenhuma

Medido nesta sessão: **1.969 documentos em 426 processos** têm exatamente ~20.000 caracteres —
o teto que o `sei_reader` usava antes de `SEI_MAX_CHARS_DOC` subir para 60.000. O texto acaba no
meio da frase e `chars=20000` no manifest é indistinguível de documento completo. Como o rodapé
de assinatura mora no fim, **estes documentos não têm data de assinatura legível** — foi o que
produziu 6 dos 15 falsos positivos do I2.

- Existe tratamento: `data/recaptura_cap21k.json` + `tools/sei_reparar_truncados --cap`, no cron
  às 05:40, 40 processos/dia, 154 já em quarentena.
- ⚠️ **A lista está defasada:** ela declara 1.660 docs em 375 processos (curada em 2026-08-01) e a
  medição de hoje, com janela MAIS ESTREITA, acha 1.969 em 426. Regenerar a lista excluindo o que
  já foi reparado é o próximo passo — não foi feito para não refilar processo já recapturado.
- ✅ **Bug corrigido nesta sessão:** o cron abortava com `FileNotFoundError` quando o compactador
  trocava `.json` por `.json.zst` entre a varredura e o `move`. A exceção matava a rodada DEPOIS
  de já ter afastado caches, e o progresso — escrito só no fim — nunca era gravado: os processos
  ficavam **sem cache E marcados como lidos**, exatamente o que o comentário do próprio arquivo
  adverte. Agora o move tolera o sumiço, conta e segue.

## 4. Regras da casa que eu violei e o sistema me pegou

- **Empenho ≠ Liquidação ≠ OB.** No G1 eu havia contado empenho e liquidação como "pagamento".
  Reservar dotação antes de assinar é correto; PAGAR antes, não. Só OB entra.
- **Ordenar data como texto.** `dd/mm/aaaa` ordenado lexicalmente ordena pelo DIA — a fase saía
  "de 08/12/2025 a 28/11/2025". Mesma armadilha já registrada para o `data_emissao` do SIAFE.
- **Verificar a ação, não o efeito.** Declarei uma reavaliação "rodando" com base no `pgrep`, que
  casou o meu próprio comando. Só apareceu ao contar quantos processos tinham `sintese_json`: 1.
- **O dado que descreve o dado entra no dado.** A etiqueta que o arquivo prepõe ao `.txt` virou
  prova sobre o documento (§2-A.1). Metadado gravado dentro do texto contamina todo leitor.

## 5. O que entrou em produção

**Leitura completa** — `_texto_de` cortava em 20.000 caracteres e alimentava acatamento, execução
e triagem: o Parecer 462 tem 54.900 e a CONCLUSÃO ficava fora. Agora
`TETO_CHARS_DETERMINISTICO=400.000` e `TETO_CHARS_LLM=20.000`, separados em constante.
⚠️ Isso conserta a LEITURA; não conserta os 1.969 documentos que o arquivo já guarda cortados (§3).

**Síntese global** (`sei/sintese_global`) — map-reduce: ficha por documento → redução por fase →
confronto do conjunto. Lê as FICHAS, nunca o texto cru; é o que faz 484 documentos e 3 milhões de
caracteres caberem em qualquer janela. Ligada ao 360, persistida em `sintese_json`, servida pela
rota `/api/processo`, no painel (aba Peças) e no PDF (seção II-B). **2.174/2.174 processos.**

**Naturezas novas** — `aditivo` (55), `pagamento` (697), `cancelado`: cada uma isenta as fases que
vivem no processo-pai. **Fase pelo tipo canônico**: 923 documentos ganharam fase.

**`NAO_AVALIAVEL`** — 202 processos sem uma letra lida deixaram de receber faixa de risco.

**Sinal invisível** — detectores de fornecedor pontuavam sem virar achado: 14 processos eram
EXTREMO com ZERO achados.

**I1/I2 validados** — §2-A. 16 testes de regressão novos, um por falso positivo LIDO. A doutrina
de "o que é controle prévio do art. 53" passou a ter uma implementação só, em
`instrumento_assinatura`, importada pela `sintese_global` (havia duas cópias prestes a divergir —
foi assim que o teto de dispensa ganhou uma terceira cópia divergente).

## 6. Próximos passos, em ordem

1. **Auditar quem mais lê os `.txt` do acervo com regex** — a etiqueta `(fase: … · tipo: …)` está
   dentro do texto de TODO documento arquivado (§2-A.1). Foi neutralizada em um módulo só.
2. **Regenerar `data/recaptura_cap21k.json`** excluindo o já reparado (§3): a lista conhece 375
   processos e existem 426.
3. **Recaptura**: `sei_sweep --recaptura` (login único) está pronto, e o teto subiu para 120 no
   `sweep_sei`. Falta drenar: **10.447 documentos** sem texto em 155 processos, e a última
   tentativa parou em `login itkava não venceu o WAF agora` — repetir pelo cron.
4. **`CONDICIONANTES_NAO_EXTRAIDAS` em 323 processos** — a extração ainda não alcança a maioria
   dos pareceres. É o gargalo do conjunto-ouro (só 2 processos com rótulo utilizável).
5. **Hermenêutica**: acurácia 0,43 · F1 0,48 contra baseline deôntico de 0,778 — o motor não
   supera um regex de uma linha. Prompt está em v1 e a catraca existe.
6. **Dívida anterior**: `data/nucleo_feedback.json` nunca existiu; 4.180 perícias com
   `veredito_perito` nulo; 224 casos presos em `status='novo'`.
