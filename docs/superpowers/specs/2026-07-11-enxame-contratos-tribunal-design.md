# Design — Enxame de Contratos "Tribunal de Contas" (Spec 2)

**Data:** 2026-07-11 · **Status:** aprovado (design) · **Autor:** Claude Fable 5 + JFN
**Escopo:** superfície **CONTRATOS** plugada no enxame-núcleo (Spec 1). Emite **parecer técnico estilo Tribunal de Contas** por contrato, compondo os detectores X + Lex + jurisprudência + preços de mercado + sinais cruzados, com **memória** e **inteligência progressiva**. Execução física (SEI) = Spec 3.

## 1. Objetivo e princípio

Avaliar contratos da Prefeitura do Rio como um tribunal de contas — aditivos (art. 125), prorrogação perpétua, sobrepreço/jogo de planilha, execução financeira — e emitir um **parecer fundamentado** (relatório → fundamentação → conclusão → voto).

**Princípio-mãe (pedido do dono): não-monólito.** Não é um módulo novo de análise; é uma **câmara de pensamentos que se cruzam** sobre um **dossiê compartilhado do contrato**. Cada "cabeça" (detector, Lex, âncora de preço, lente-auditor) lê o dossiê, escreve seus achados com proveniência e pode referenciar a saída das outras. **Memória** evita re-acusar o refutado; o loop de **auto-melhoria** calibra o método com o uso. Inteligência progressiva, não estática.

Honestidade dura (regras da casa, sempre-on): indício ≠ acusação; presunção de legitimidade; ausente ≠ 0; empenho ≠ liquidação ≠ pago (só OB é pago); proveniência por número; CPF mascarado; LLM só free-tier; VM 2 vCPU (funil determinístico antes do enxame).

## 2. Fontes — TODAS validadas ao vivo (2026-07-11)

| Fonte | O quê | Endpoint / acesso | Estado |
|---|---|---|---|
| `pcrj_contratos` (4.219) | contrato base: fornecedor, objeto, valor_inicial/global, vigência, seq PNCP | local | ✅ |
| **PNCP termos aditivos** | por contrato: `valorAcrescido`, `valorGlobal`, `prazoAditadoDias`, `objetoTermoContrato`, `qualificacaoAcrescimoSupressao/Vigencia/Reajuste`, `fundamentoLegal` | `GET api/pncp/v1/orgaos/{cnpj}/contratos/{ano}/{sequencialContrato}/termos` (200=tem, 204=sem) | ✅ **RESOLVIDO** (cobre 2021→hoje) |
| **Painel de Preços** (compras.gov.br dados abertos) | preço unitário de mercado por CATMAT | catálogo: `GET /modulo-material/3_consultarPdmMaterial?nomePdm=<kw>` → `codigoClasse`; `/4_consultarItemMaterial?codigoClasse=<c>` → `codigoItem` (CATMAT). preço: `/modulo-pesquisa-preco/1_consultarMaterial?codigoItemCatalogo=<CATMAT>` → `precoUnitario`. Serviços: `3_consultarServico`/`3_consultarPdmMaterial` análogo. Paginação 10–500. | ✅ **RESOLVIDO** (público, sem WAF; preço real retornado no teste) |
| `pncp.buscar_itens` | preço UNITÁRIO estimado do item no próprio contrato | local/PNCP | ✅ |
| `pcrj_despesa` (78.595) | pago por credor — execução FINANCEIRA | local | ✅ |
| ContasRio família Contratos (2021-23) | valor atualizado + acréscimo (cross-check secundário do aditivo) | `contasrio.carregar_contratos_csv` (existe) | ✅ (secundário) |
| Detectores **X1/X2/X3/X5** | crescimento aditivo, prorrogação perpétua, execução financeira, jogo de planilha (spec V2 validada) | `detectores/` | ✅ |
| **Lex** `lex_indicadores_fraude.triagem` / `sinais_do_contexto` / `parecer_indicadores_md` | nota 🟢🟡🔴 + indicadores R2–R12 | local | ✅ |
| `hermes_rag.consultar(pergunta, k)` | RAG Lei 14.133 + jurisprudência + vault | local | ✅ |
| `memoria_aprendizado` / `llm/auto_melhoria.auto_melhorar` | memória progressiva + metacognição | local | ✅ |
| Enxame-núcleo `compliance_agent/enxame/` | orquestrador + lentes adversariais | Spec 1 | ✅ |

Nota do WAF: o **front** `paineldeprecos.planejamento.gov.br` dá 403; a **API de dados abertos** `dadosabertos.compras.gov.br` é o acesso público correto (verificado).

## 3. Arquitetura — dossiê compartilhado = barramento anti-monólito

```
contrato ─► montar_dossie() ──► DOSSIÊ (dict, proveniência por campo)  ◄── cada thought lê/escreve
   │
   │ Camada determinística (funil barato/auditável):
   │   t_aditivo(X1·PNCP termos) · t_prorrogacao(X2) · t_execucao_financeira(X3·despesa)
   │   t_sobrepreco(X5 · peer + Painel de Preços) · t_lex(R2–R12) · t_sinais_cruzados
   ▼
  candidatos (dossiê com ≥1 achado ≥ limiar)
   │ Câmara de deliberação (enxame LLM free-tier, SÓ nos candidatos):
   │   lentes-auditor + RAG(fundamentação) + MEMÓRIA(não re-acusar refutado) + refutador-gate
   ▼
  síntese ─► PARECER TC {relatório · fundamentação · conclusão · voto} ─► PDF Kroll + índice XLSX
   │
   └► feedback: veredito → memoria_aprendizado → auto_melhorar (progressivo)
```

### Unidades (isoladas, uma responsabilidade, testáveis)
- `compliance_agent/contratos/db.py` — schema: `contrato_aditivo`, `contrato_dossie`, `contrato_parecer`, `preco_referencia_cache`.
- `compliance_agent/collectors/precos.py` — **âncora de mercado** (novo, reusável): `catmat_por_descricao(desc) -> [(codigo, nome, score)]` (PDM→classe→item, com cache + match textual), `preco_referencia(catmat) -> {mediana, n, min, max}` (cache em `preco_referencia_cache`, TTL 30d). Degrada honesto: sem CATMAT confiável → retorna `{disponivel: False}` e o sobrepreço fica só no peer.
- `compliance_agent/collectors/pncp.py` — **estender**: `async termos_contrato(cnpj, ano, seq) -> [dict]` (api/pncp/v1; 204→[]) e gravação em `contrato_aditivo`.
- `compliance_agent/contratos/dossie.py` — `montar_dossie(con, numero_controle_pncp) -> dict`: contrato + aditivos (PNCP termos) + pagamentos (pcrj_despesa) + itens/preços (PNCP + Painel) + sinais cruzados. É o barramento; proveniência por campo.
- `compliance_agent/contratos/thoughts.py` — os pensamentos determinísticos, funções puras `(dossie) -> [achado]`. Achado: `{dimensao, risco 0-10, texto, norma, proveniencia}`.
- `compliance_agent/enxame/memoria.py` (novo, reusável) — `contexto_memoria(con, categoria, chave) -> str` (vereditos anteriores da mesma dimensão/fornecedor, de `memoria_aprendizado` + casos vault) e `registrar_veredito(con, categoria, chave, veredito)`.
- `compliance_agent/enxame/lentes.py` — **estender** (não reescrever): as lentes recebem `rag_ctx` e `memoria_ctx` no dossiê; a lente-jurisprudência chama `hermes_rag.consultar`.
- `compliance_agent/contratos/parecer.py` — `deliberar(con, dossie, achados, gerar=None) -> parecer`; `render_parecer_ctx(parecer) -> ctx` (as 4 seções → `render_html`); `gravar_e_aprender(con, parecer)`.
- `tools/contratos_parecer.py` — runner: coleta termos (se preciso) → dossiês → funil → câmara → PDF por contrato + índice; `--telegram`, `--max-contratos`.

## 4. As dimensões (thoughts determinísticos) — completas

1. **Aditivo (X1 / art. 125)** — para cada contrato, soma `valorAcrescido` dos termos (PNCP) sobre `valor_inicial`. `acréscimo > 25%` (ou > 50% só se objeto for reforma de edifício/equipamento — o `objetoTermoContrato` diz) = achado. Distingue acréscimo de **valor** (art. 125) de aditivo só de **prazo** (`qualificacaoVigencia`, legítimo se dentro de art. 106/107). Norma citada e prazo aditado no achado.
2. **Prorrogação perpétua (X2)** — mesmo fornecedor (doc/nome_norm) + objeto (assinatura semântica) + órgão presente em ≥3 exercícios; vigência total (inicial + termos de prazo) > limite do tipo contratual. Serviço contínuo tem limite (art. 107 — até 10 anos); acima ou sem justificativa = achado.
3. **Execução financeira (X3)** — `pcrj_despesa.pago` do credor+órgão no período do contrato × `valor_global`. Pago > global (pagamento além do contratado) = forte; empenho/liquidação/pago sempre exibidos separados; ritmo (pago concentrado no início) = médio.
4. **Sobrepreço / jogo de planilha (X5)** — para cada item do contrato (PNCP `buscar_itens`, com `valorUnitarioEstimado`): (a) **peer** — mediana dos MESMOS itens (descrição normalizada + unidade) em outros contratos PCRJ; (b) **âncora Painel** — `precos.preco_referencia(catmat)` via `catmat_por_descricao`. Item com unitário > 1,3× a referência (peer ou Painel) = achado; se **peer barato mas Painel caro** (ou vice-versa) o parecer registra a divergência. Jogo de planilha = item superfaturado + item subfaturado no mesmo contrato de preço global.
5. **Lex (R2–R12)** — `triagem(sinais_do_contexto(dossie))` → nota 🟢🟡🔴 + indicadores entram no dossiê como um pensamento a mais (não duplica; complementa as dimensões X).
6. **Sinais cruzados** — fornecedor × emendas/doações/sanções/fantasma/rede (reuso D3/D4/D5/D8/D10). Amarra o contrato ao beneficiário; sem sinal, voto baixo (ausência não é indício).

## 5. Memória e inteligência progressiva (o coração do pedido)

- **Antes de deliberar**: `contexto_memoria(con, "contrato_<dimensao>", fornecedor)` injeta nas lentes os vereditos anteriores da mesma dimensão/fornecedor ("já foi analisado e REFUTADO no caso X porque…") — evita re-acusar o que a auditoria-ouro derrubou (lição dura: o RAG precisa carregar VEREDITOS, não só normas).
- **Depois**: `registrar_veredito` grava/atualiza `memoria_aprendizado` (categoria=`contrato_<dimensao>`, chave=fornecedor/objeto, valor=veredito, `n_observacoes++`, `confianca` ajustada).
- **Semanal**: `auto_melhorar` (loop existente) critica os pareceres contra desfechos conhecidos e propõe correções de método (limiares/prompts, categoria `metodo`), reinjetadas no prompt do enxame. O método melhora sozinho com o volume.

## 6. Saída — parecer estilo Tribunal de Contas
Por contrato flagueado, PDF Kroll com a estrutura clássica:
- **I. RELATÓRIO** — partes (órgão, fornecedor+doc), objeto, valores (inicial/aditado/atualizado/pago — milhar+2 casas), vigência e aditivos; proveniência (fonte+data) de cada número.
- **II. FUNDAMENTAÇÃO** — por dimensão marcada: os fatos, a norma (Lei 14.133 art. citado), a jurisprudência (via RAG, com aviso "verificar antes de citar" quando a âncora for fraca) e o voto do enxame (lentes + memória).
- **III. CONCLUSÃO** — escala explícita: **regular** / **baixar em diligência** / **indício de irregularidade** (com o score do enxame).
- **IV. VOTO** — recomendação: aprovar; diligência (o que exatamente pedir); ou representar ao TCM-RJ (com a base). Indício ≠ acusação; presunção de legitimidade.
Índice consolidado (XLSX) + caso em `~/vault/casos/` para conclusão "irregularidade" forte.

## 7. Testes (teste REAL — meta do dono)
- **Unit** (dossiês sintéticos): cada thought dispara no cenário certo e NÃO no legítimo — aditivo 30% de valor dispara, aditivo só de prazo não; prorrogação 3 exercícios; pago>global; item 3× a mediana peer; Lex integra a nota.
- **Painel de Preços** (fixture do payload real capturado): `catmat_por_descricao` e `preco_referencia` parseiam; cache não re-consulta.
- **PNCP termos** (fixture do termo real): parser extrai valorAcrescido/prazo/qualificação; 204→[].
- **Memória**: `contexto_memoria` recupera o veredito gravado; `registrar_veredito` incrementa `n_observacoes`.
- **Parecer**: `deliberar` com enxame mockado → parecer com as 4 seções; conclusão coerente com o voto; desempate pró-refutador herdado do Spec 1.
- **Integração viva (dado real)**: coletar termos de ≥1 contrato PCRJ com aditivo real, montar dossiê, emitir parecer, **revisar à mão** (anti-falso-positivo, como no Spec 1) antes de declarar pronto. Sobrepreço: ≥1 item real ancorado no Painel, revisado.

## 8. Restrições e critérios de aceite
- LLM só free-tier; funil antes da câmara; `coleta_lock` na coleta de termos; Painel best-effort com cache (degrada honesto se um item não casar no catálogo).
- Rate: PNCP termos ~1 req/contrato (só nos que têm aditivo — filtra por `num_aditivos>0` ou tipo Contrato); Painel com cache 30d por CATMAT.
- **Aceite**: (1) termos de aditivo coletados p/ ≥1 contrato real, valorAcrescido confere com o PNCP; (2) t_aditivo marca >25% e o número bate; (3) Painel retorna preço p/ ≥1 CATMAT derivado de descrição PCRJ; (4) t_sobrepreco acha ≥1 item fora da faixa, revisado à mão; (5) memória recupera+grava veredito; (6) 1 parecer TC real em PDF com as 4 seções e citação de norma/jurisprudência; (7) achado revisado à mão = plausível.

## 9. Fora de escopo (Spec 3)
Execução **física** (medição, entrega fantasma X6, atesto do fiscal) — depende do SEI (`sei_reader`), fica no Spec 3, plugando no mesmo dossiê/câmara.
