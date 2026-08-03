# Handoff — 2026-08-03 · leitura de originais, síntese global e validação caso a caso

> **O método que rendeu tudo nesta sessão:** abrir o processo, ler os documentos e comparar com o
> que o sistema concluiu. Todo achado real e todo falso positivo saiu daí — nenhum de ajustar
> limiar. Teste verde não pegou nada disso; ler a saída sobre o acervo real pegou.

---

## 1. Estado dos detectores — taxas MEDIDAS em 2.175 processos

| Detector | Disparos | Validado caso a caso? |
|---|---:|---|
| `C1_DOCUMENTO_CITADO_NAO_CAPTURADO` | 364 (16,7%) | ✅ sim — volume é real (teto de 40 docs/processo) |
| `I4_ORDINAL_INCOERENTE_COM_PRAZO` | 16 (0,7%) | ✅ com ressalva declarada no próprio achado |
| `I2_AUTORIZACAO_ANTES_DO_PARECER` | 15 (0,7%) | ⚠️ **amostrado, não conferido documento a documento** |
| `I1_ORDINAL_DIVERGENTE` | 10 (0,5%) | ⚠️ **idem** |
| `I6_QUANTITATIVO_DIVERGENTE` | 7 (0,3%) | ✅ sim (aeronaves 3×4 e 6×7) |
| `I7_APROVADOR_NAO_ASSINOU` | 5 (0,2%) | ✅ sim (Atos de Designação) |
| `I3_ATO_SEM_ASSINATURA_DA_AUTORIDADE` | 2 (0,1%) | ✅ sim |
| `I5_DECLARACAO_DE_OUTRO_CONTRATO` | 2 (0,1%) | ✅ sim |
| `G2_DOCUMENTO_DE_OUTRO_PROCESSO` | 384 (17,7%) | ✅ sim (TR e Autorizo de outro processo na pasta) |
| `G3_MESMA_PESSOA_CONTROLA_E_DECIDE` | 2 (0,1%) | ✅ sim |
| `G1_PAGAMENTO_ANTES_DO_CONTRATO` | 0 | armado; nenhuma OB anterior ao contrato no acervo |

**Pendência honesta:** I1 e I2 foram amostrados (a saída lida, os casos plausíveis) mas **não
abertos documento a documento** como o G3 e o I3 foram. É a primeira coisa a fazer.

## 2. Falsos positivos derrubados nesta sessão — todos por leitura

| Detector | Antes | Depois | O que a leitura mostrou |
|---|---:|---:|---|
| G3 | 73 | 2 | "Parecer de Análise para Emissão DL" não é controle prévio; checklist não é parecer |
| G2 | 305→976 | 384 | dono adivinhado por frequência; sem âncora do rodapé, citação virava documento alheio |
| G1 | 202 | 0 | sobreposição de fases é rotina — paga-se ENQUANTO se executa |
| I3 | 3 | 2 | documento intitulado "MINUTA" é rascunho, não ato |
| C1 | 370 | 364 | "Telefone: 23809230" virava documento; ID citado que ESTÁ na pasta era cobrado |
| I6 | 9 | 7 | "5 (cinco) dias" lido como quantitativo do objeto |
| I7 | 7 | 5 | "de acordo com a legislação" e "meio do Processo Admi" lidos como nome de aprovador |

## 3. Regras da casa que eu violei e o sistema me pegou

- **Empenho ≠ Liquidação ≠ OB.** No G1 eu havia contado empenho e liquidação como "pagamento".
  Reservar dotação antes de assinar é correto; PAGAR antes, não. Só OB entra.
- **Ordenar data como texto.** `dd/mm/aaaa` ordenado lexicalmente ordena pelo DIA — a fase saía
  "de 08/12/2025 a 28/11/2025". Mesma armadilha já registrada para o `data_emissao` do SIAFE.
- **Verificar a ação, não o efeito.** Declarei uma reavaliação "rodando" com base no `pgrep`, que
  casou o meu próprio comando. Só apareceu ao contar quantos processos tinham `sintese_json`: 1.

## 4. O que entrou em produção

**Leitura completa** — `_texto_de` cortava em 20.000 caracteres e alimentava acatamento, execução
e triagem: o Parecer 462 tem 54.900 e a CONCLUSÃO ficava fora. Agora
`TETO_CHARS_DETERMINISTICO=400.000` e `TETO_CHARS_LLM=20.000`, separados em constante.

**Síntese global** (`sei/sintese_global`) — map-reduce: ficha por documento → redução por fase →
confronto do conjunto. Lê as FICHAS, nunca o texto cru; é o que faz 484 documentos e 3 milhões de
caracteres caberem em qualquer janela. Ligada ao 360, persistida em `sintese_json`, servida pela
rota `/api/processo`, no painel (aba Peças) e no PDF (seção II-B). **2.174/2.174 processos.**

**Naturezas novas** — `aditivo` (55), `pagamento` (697), `cancelado`: cada uma isenta as fases que
vivem no processo-pai. **Fase pelo tipo canônico**: 923 documentos ganharam fase.

**`NAO_AVALIAVEL`** — 202 processos sem uma letra lida deixaram de receber faixa de risco.

**Sinal invisível** — detectores de fornecedor pontuavam sem virar achado: 14 processos eram
EXTREMO com ZERO achados.

## 5. Próximos passos, em ordem

1. **Abrir I1 e I2 documento a documento** (25 casos somados) — é a pendência declarada acima.
2. **Recaptura**: `sei_sweep --recaptura` (login único) está pronto, e o teto subiu para 120 no
   `sweep_sei`. Falta drenar: **10.447 documentos** sem texto em 155 processos, e a última
   tentativa parou em `login itkava não venceu o WAF agora` — repetir pelo cron.
3. **`CONDICIONANTES_NAO_EXTRAIDAS` em 323 processos** — a extração ainda não alcança a maioria
   dos pareceres. É o gargalo do conjunto-ouro (só 2 processos com rótulo utilizável).
4. **Hermenêutica**: acurácia 0,43 · F1 0,48 contra baseline deôntico de 0,778 — o motor não
   supera um regex de uma linha. Prompt está em v1 e a catraca existe.
5. **Dívida anterior**: `data/nucleo_feedback.json` nunca existiu; 4.180 perícias com
   `veredito_perito` nulo; 224 casos presos em `status='novo'`.
