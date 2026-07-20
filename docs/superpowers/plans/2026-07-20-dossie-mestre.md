# DOSSIÊ MESTRE — Arquitetura (2026-07-20)

> Objetivo do dono: dossiê mestre completo de contratos/licitações do **Estado (TCE-RJ)** e da
> **Prefeitura do Rio (TCM-RJ)** — flags certos × suspeitos; índice de restritividade por cláusula
> (IRC) e global (IRG) integrando **o que de fato ocorreu** no certame (ex.: eliminações por motivo
> trivial); interpretação subjetiva isolada em IA mais fraca; auditoria de acatamento de **pareceres**
> (setorial/CGE-PGE); e **avaliação de conjunto** dos processos. Padrão profissional máximo.

## 0. Princípio reitor — epistemologia em camadas

Cada afirmação do dossiê carrega o SEU grau de certeza, nunca misturado:

| Grau | Nome | O que é | Quem produz | Exemplo |
|---|---|---|---|---|
| A | **FLAG CERTO** | Fato objetivo verificável com número+fonte+teto legal | código determinístico | garantia 3% > teto 1% (art. 58 §1º); prazo útil < art. 55; homologado > estimado (art. 59 III); parecer com ressalva ignorado sem despacho motivado (art. 53) |
| B | **INDÍCIO FORTE** | Convergência de ≥2 famílias independentes | pipeline (convergência multiplicativa) | cláusula rara (peer) + inabilitação seletiva NELA + vencedor com sinal societário |
| C | **FLAG SUSPEITO** | Juízo interpretativo | LLM (lentes/rubrica), SEMPRE com citação verbatim + refutador | "pontuação subjetiva parece talhada ao incumbente" |
| D | **NÃO-AFERÍVEL** | INDISPONÍVEL ≠ 0 | — | ata sem motivos de inabilitação legíveis |
| E | **EXCULPADO** | Guard anti-FP disparou | código | desconto baixo mas preço tabelado |

Regra de exibição: A e B podem fundamentar peça; C só acompanha A/B ou vira diligência; D/E sempre
declarados. Implementação: `grau_flag()` — mapeia (status, score, teste, corroboração) → A-E.

## 1. IRC — Índice de Restritividade da Cláusula (0-100, auditável)

Por cláusula candidata (do coletor/E7), com **breakdown publicado** (citação por célula):

- **F — força finalística** (0-1): tier E7 da categoria (fraco .3 / médio .6 / forte .85).
- **T — teste objetivo**: `teste_finalistico` → violado=1.0 · nao_aferivel=0.5 · dentro_do_teto=0.15.
- **R — raridade peer** (0-1): `peer_diff.raridade()` — fração dos editais-pares SEM a exigência.
- **L — colegiado** (0-1, SUBJETIVO): score do enxame/10 (entra só no IRC_total, nunca no objetivo).

`IRC_obj = 100·(0.40·F + 0.35·T + 0.25·R)`, com piso 70 se T=violado (teto legal excedido é grave
por si). `IRC_total = 0.8·IRC_obj + 20·L`. Violado → flag A; IRC_total alto sem T → flag C.

## 2. IRG — Índice de Restritividade Global do certame

Integra **DESENHO × EXECUÇÃO × RESULTADO × GOVERNANÇA**, por convergência multiplicativa
(`1−Π(1−w·s)`, padrão `base.score_processo`; dentro de família = MÁXIMO, nunca soma):

1. **Desenho** (cláusulas): máx(IRC)/100 + bônus efeito combinado (≥3 categorias distintas — doutrina E7).
2. **Execução** (o que OCORREU — ata):
   - taxa de inabilitação (inabilitados/participantes);
   - **trivialidade** dos motivos (classificador §3): inabilitação por motivo TRIVIAL sem diligência
     de saneamento = violação objetiva (art. 64 §1º + art. 12 III) → flag A;
   - **acoplamento desenho→execução** (a prova finalística): inabilitação fundada EXATAMENTE na
     cláusula de IRC alto = a barreira FUNCIONOU → multiplicador;
   - cascata (vencedor mal classificado sobe após inabilitações) — já no cérebro/J7.
3. **Resultado**: <3 propostas válidas (J4), desconto irrisório/negativo (J3), perfil do vencedor (C/C6).
4. **Governança**: parecer ignorado/ausente (§4), retificação sem reabertura (E2).

Saída: IRG 0-100, classe 🟢<25 🟡25-50 🟠50-75 🔴≥75, e o **porquê** decomposto com citações.
Relação com `indice_certame` (6 famílias): IRG É o índice de certame ESTENDIDO — reusar, não duplicar
(decisão final após mapa de integração do Explore).

## 3. Classificador de motivo de inabilitação (trivial × substancial)

Gabarito NO CÓDIGO (lição: gabarito em código > LLM fraca):
- **TRIVIAL/SANÁVEL** (inabilitar sem diligência = flag A): assinatura/rubrica faltante; certidão
  vencida verificável online; falha de numeração/formatação; declaração-modelo ausente mas suprível;
  cópia sem autenticação com original verificável (rol do art. 64 §1º c/ art. 12 III).
- **SUBSTANCIAL** (lícito): quantitativo de atestado não atingido, capital/PL insuficiente, objeto
  social incompatível, ausência de documento essencial (diligência não substitui documento essencial).
- Resíduo ambíguo → rubrica LLM-fraca (payload <8k, saída JSON 0-4, citação verbatim obrigatória,
  refutador adversarial) → no máximo flag C.

## 4. Auditoria de pareceres (setorial × CGE × PGE/PGM)

Cadeia esperada (art. 53): fase preparatória → **parecer jurídico obrigatório** (controle prévio de
legalidade; dispensa só por ato da autoridade jurídica máxima — §5) → autoridade acolhe OU decide
motivadamente em contrário. No Estado RJ: assessoria setorial + PGE + CGE; na PCRJ: PGM + CGM.

Pipeline por processo SEI:
1. **Tipagem de documentos** (determinística: título + cabeçalho + órgão emissor): parecer / promoção /
   nota técnica / despacho / manifestação de controle interno.
2. **Extração por parecer**: emissor, data, conclusão (favorável / favorável-com-ressalvas / contrário /
   inconclusivo), **ressalvas enumeradas** (regex: "ressalva", "recomend", "desde que", "condicion",
   "deverá ser ajustad", "sob pena").
3. **Rastreio de acatamento** por ressalva: procurar resposta em despacho posterior / versão seguinte do
   edital / termo ajustado. Determinístico: menção explícita + mudança textual; LLM-fraca: juízo de
   atendimento SUBSTANTIVO (rubrica, flag C).
4. **Veredito do processo**: `ACOLHIDO_INTEGRAL` · `ACOLHIDO_PARCIAL` · `CONTRARIADO_COM_MOTIVACAO`
   (lícito — LINDB art. 22) · `IGNORADO` (flag A: ressalva sem resposta e ato seguiu) ·
   `SEM_PARECER` (flag A se não enquadra na dispensa do §5) · `SEM_ACESSO` (≠ SEM_PARECER; honesto).

## 5. Avaliação de CONJUNTO (portfólio por órgão × esfera)

O salto de nível: os processos analisados **como conjunto**, não um a um.
- Por órgão: distribuição de IRG (mediana, p90, outliers), taxa de flag A por processo, taxa de
  inabilitação trivial, taxa de parecer ignorado, concentração de vencedores (HHI), reincidência por
  vício (≥3 → auditoria temática, `escalada.py` já sinaliza).
- **Peer-benchmark entre órgãos** (peer_diff um nível acima): órgão vs mediana dos órgãos da esfera.
- Casos-âncora: top-N processos que puxam o índice do órgão (com link para as fichas).
- Interpretação sistêmica (IA de produto, não de sweep): narrativa do padrão com rubrica-judge.
- Esferas ESTANQUES: Estado→TCE-RJ, Município→TCM-RJ (gate já existente no Lex).

## 6. Isolamento da IA fraca (regras duras, já validadas na casa)

- Sweep/volume → nous `stepfun:free` SOMENTE; produtos → gemini + cerebras. Cerebras nunca no volume.
- Payload <8k; limiar numérico NO CÓDIGO, nunca no prompt; saída JSON com escala 0-4; citação
  verbatim OBRIGATÓRIA (sem citação → descarte automático); refutador adversarial em todo achado
  subjetivo ≥ limiar; sem LLM disponível → degrada para `nao_aferivel` (nunca 0, nunca inventa).
- Fluxo de graus: LLM NUNCA produz flag A — teto de IA é flag C; a promoção C→B só por convergência
  com detector determinístico; C nunca vira A.

## 7. Produto final — Dossiê Mestre (pipeline Kroll)

Capa + sumário executivo (IRG-portfólio, top flags A) · metodologia transparente (fórmulas dos
índices) · mapa do conjunto (tabelas por órgão/esfera) · fichas dos top-N processos (tabela
cláusula-a-cláusula com IRC e citação por célula; linha do tempo; eventos da ata com motivos
classificados; pareceres e acatamento; flags SEPARADOS por grau; peça recomendada via
`escalada.recomendar`) · lacunas e INDISPONÍVEL declarados · anexo jurisprudencial verbatim.
Formatos: md + pdf (Kroll) + xlsx (tabular, uma linha por cláusula/flag).

## 8. Fases

- **F1** `editais/restritividade.py` — IRC/IRG determinísticos + classificador de motivo trivial + grau_flag. ✅ testes
- **F2** `compliance_agent/pareceres_audit.py` — tipagem+extração+acatamento determinísticos. ✅ testes
- **F3** `editais/avaliacao_conjunto.py` + `reporting/dossie_mestre.py` (renderer Kroll). ✅ testes
- **F4** wiring: rotas/produto `/dossie-mestre`, sweep de backfill (ata+pareceres nos processos já
  arquivados), rubricas LLM-fraca, painel. — fase seguinte, depois de F1-F3 estáveis.

Âncoras legais conferidas em fonte (2026-07-20): art. 12 III, art. 53 (§§ do parecer), art. 55, art. 58
§1º, art. 59 III, art. 64 §1º, arts. 66-69, arts. 106-111, art. 125. Não citar nada fora disso sem conferir.
