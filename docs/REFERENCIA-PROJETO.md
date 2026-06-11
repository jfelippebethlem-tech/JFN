# JFN — DOCUMENTO ÚNICO DE REFERÊNCIA

> **Único doc de referência do projeto** (decisão do dono). Mantido ENXUTO de propósito (contexto é caro):
> estado vivo + regras + lições duras + retomada. Histórico detalhado vai para o git (commits) e docs por tema.
>
> **Como trabalhar (loop de qualidade máxima):** (1) ler este doc + o código real → (2) pesquisar best-practice →
> (3) planejar com visão global → (4) executar pequeno/isolado/**verificado** → (5) testar e corrigir →
> (6) **gerar o produto real e medir se melhorou/piorou** (PDF entregue, não só MD) → (7) commit + atualizar este
> doc (1 linha no §10). Detalhismo proporcional à complexidade; **testar tudo, nunca às cegas**; ao fim avaliar
> storage/RAM/CPU. **Honestidade sempre:** indício≠acusação, INDISPONÍVEL≠0, nunca inventar número, CPF PF mascarado.

Última atualização: 2026-06-11.

---

## 1. NORTE
JFN = motor + barramento de **auditoria/compliance do Estado do RJ** (TCE-RJ/controle externo). Propósito legítimo:
o dono é **Deputado Estadual** no dever de fiscalizar/combater corrupção (base legal LGPD art. 7º,II/23). Ecossistema:
**JFN** (relatórios/risco) · **Lex** (parecer jurídico) · **Massare** (mercado/previsão) · **Yoda/Hermes** (bot
Telegram = maestro, aciona o JFN pela API `127.0.0.1:8000`). Padrão de saída: Kroll/Deloitte, grátis, honesto.
**Regra-mãe: OB (Ordem Bancária) = verdade de pagamento**, nunca empenho.

## 2. ESTADO VIVO
- **VM Linux GCP**, `~/JFN`. Branch **`feat/lista-limpa`** (não pushado; tudo commitado).
- **`jfn.service`** (user; `systemctl --user restart jfn.service`) → API `127.0.0.1:8000`. **`hermes-gateway.service`** =
  Yoda (`~/hermes-agent`). Ambos auto-start no boot.
- **DB** `data/compliance.db` (1,2G): `ordens_bancarias` (OB 2019-2026, 1,12M, 77% c/ CNPJ; `favorecido_cpf`=CNPJ(14)/
  CPF(11)) + `ob_orcamentaria_siafe` (95k). **UG 133100=ITERJ** (`data/ug_canonico.json`). WAL via cron dom 03:00.
- **Sweeps:** **SEI** vivo e supervisionado (`tools/sei_supervisor.sh`, cron-minuto relança; resumível por checkpoint
  `data/sei_cache/sei_sweep_progress.json`; reboot-safe — ver §8). **SIAFE 2** = varredura completa; incremental
  diário via cron 05:00 (`siafe_runner diario`). SIAFE 1 = conta ALERJ-only (pende chave do dono).
- **Cron:** manutenção dom 03:00; folha 06:00; siafe diário 05:00; massare 06:15 + backtest dom 04:30; `@reboot`
  limpa lock + relança SEI supervisor.

## 3. LLM — ALOCAÇÃO (isolamento de qualidade)
- **Sweep SEI** (triagem + raciocínio de fraude em massa) → **nous `stepfun:free`** (ilimitado/grátis). **Cerebras
  NUNCA no volume do sweep** (não é ilimitado). Modelo de raciocínio → `max_tokens` alto + ler `reasoning` se `content` vazio.
- **Produtos** (/relatorio, /orgao, Lex) → **gemini** (qualidade) + **cerebras** rede de segurança. LLM nos produtos só
  **assíncrono + bounded(45s) + degrada honesto + medido no PDF** (lição V2, §8).
- **Pool free_llm e Yoda** → cerebras + gemini (redundância). Chaves em `~/.hermes/.env`/`~/JFN/.env`/`auth.json`
  (pool gemini 10 chaves c/ rotação; cooldown 12h p/ billing esgotado; nous = rede de segurança grátis).

## 4. PRONTO (produtos · coletores)
**Produtos** (md+pdf+xlsx): **/relatorio** fornecedor (`reporting/inteligencia.py`) — perfil, rede sócio×OB×SEI×
endereço, pagamentos/ano, HHI, contratos, matriz P×I, red flags RF-01..05, sanções CEIS/CNEP via API, OSINT (Querido
Diário), §11-B análise raciocinada + **§II-E investigação fachada/laranja** (via Lex). **/orgao**
(`inteligencia_orgao.py`) — concentração, recorrentes idênticos, raciocínio, Lex de órgão. **Lex** (`lex.py`) — parecer
+ investigação DD (ver §7). **Dossiê** (`dossie.py`). **Massare** (backtest 356k pregões). **Yoda** — `/lista` curado,
"Bom dia" multi-fonte política.
**Coletores/base:** TFE OB (1,1M), SIAFE 1+2 (23 col.), TSE 542k doações, PNCP, correlação OB↔SEI, CEIS/CNEP/CEPIM (API),
GDELT, providers (registry/sanctions/ownership/leaks/links/gazettes/eleitoral — `compliance_agent/providers/`).
**Infra:** pyproject (ruff/pytest), golden numbers, scorecard, pre-commit lint.

## 5. ROADMAP (priorizado)
**P0:** proveniência/INDISPONÍVEL padronizada (modelo `providers/base.Resultado`) · resolução de entidade (Splink,
CNPJ-raiz) → destrava grafo/concentração + matriz+filial · score anomalia ensemble (PyOD) · DuckDB.
**P1:** circuit-breaker no enriquecimento · resolução de entidade · cruzamento SEI×OB + Docling/VLM · Mem0 no Yoda.
**P2:** grafo fornecedor-órgão (GNN) · SHAP no relatório · calibração por UG.
**Investigação DD (em curso):** Loop 1 feito (motor + Lex II-E). **Loop 2 (próximo):** coletor `beneficios_sociais.py`
(PETI/Safra/Seguro-Defeso por CPF, param `codigo`, header `chave-api-dados`) + `/peps` por cpf — só em CPF COMPLETO
(PF favorecida/SEI/TSE; QSA público=CPF mascarado=INDISPONÍVEL). Bolsa Família por-CPF descontinuado (só por NIS).

## 6. GAPS CONHECIDOS
Lex×SEI precisa input SEI real (sweep rodando aos poucos) · Massare hit-rate OOS (mitigado por backtest) · conluio
intra-licitação (PNCP só expõe vencedor) · quarentena de ingestão stale mas base já limpa (baixa alavancagem) ·
god-files (server.py 1959, inteligencia.py ~1800, lex.py ~1100 — split só oportunístico) · server.py possível leak
de browser Playwright (investigar guard).

## 7. INVESTIGAÇÃO DE DUE DILIGENCE (fachada/laranja) — o Lex conduz e apresenta
`compliance_agent/investigacao_dd.py::investigar(cnpj, cadastral, pagamentos, usar_rede, geocode)` → hipóteses
`{codigo,titulo,status,nivel,evidencia,fonte,base_legal,peso}` com **status CONFIRMADO/INDICIO/AFASTADO/INDISPONIVEL**
(INDISPONÍVEL≠achado), score+grau com corroboração. Hipóteses: endereço residencial/baldio (markers + Nominatim opc.),
co-endereço, capital ínfimo, recência, situação irregular, porte, sócio único. O **Lex** chama no `_analise` → cada
hipótese vira achado `DD/*` (entra no grau) + seção **II-E** dedicada no parecer (status/evidência/fonte/base legal +
cobertura honesta). Degrada honesto (try/except). Best-practices: TCU; OECD Bid Rigging 2025; ACFE; corroboração ≥2.

## 8. LIÇÕES DURAS (não repetir)
- **⛔ V2 (2026-06-08):** LLM síncrono no hot-path + mudar o que funcionava = regressão. Gerar o **artefato real cedo**
  como baseline; perfeição = perfeiçoar o existente.
- **Auto-pkill:** `pkill -f "x"` com o padrão no próprio comando se auto-mata → usar colchete `x[_]y` ou PID.
- **Verificar o dono do processo antes de matar/concluir** (o Chromium vivo era do server.py, não de sweep).
- **Reboot-safe lock:** lock por PID não basta (PID reusado após boot parece vivo) → ancorar no boot time
  (`/proc/stat btime`): lock anterior ao boot = obsoleto na hora (`recursos._lock_obsoleto`).
- **Ler a doc da API (swagger) > adivinhar:** param de filtro varia por endpoint (CEIS `codigoSancionado` vs CEPIM
  `cnpjSancionado`); endpoint pode morrer (Bolsa Família por-CPF). Distinguir verificado=False (INDISPONÍVEL) de "limpo".
- **Ler o código real > confiar no handoff/doc** (a doc envelhece; medir o produto/código cedo revela o gap real).
- **Notícia robusta = RSS de seção dos veículos** (URL real), não Google News (`batchexecute` quebrado) nem GDELT (429 da VM).
- **Verificar o PDF ENTREGUE** (3 renderizadores): glifos fora da fonte DejaVu viram tofu; emoji nunca cru p/ DejaVu.

## 9. PENDÊNCIAS DO DONO
SIAFE 1 (liberar chave p/ todas as UGs) · SEI de outras unidades (acesso do itkava) · repor/rotacionar billing das
chaves Gemini sem saldo e renovar tokens OAuth "AQ." manuais quando expirarem (caem no nous até lá).

## 10. CHANGELOG (1 linha/sessão — detalhe no git)
- **06-11 cont.13:** **Verificação de realidade do endereço** (`verificacao_endereco.py`): geocode-match (bate município? Nominatim) + **edificação/baldio** (Overpass/OSM — sem prédio no ponto + landuse vago = indício de terreno não edificado; ressalva honesta de cobertura OSM incompleta) + hook imagem→VLM (ativa com chave Street View/Mapillary). Plugado no H-END-EXISTE. Back-off 429/5xx + cache 30d → **sweep `endereco_sweep --todos`** avalia TODAS as fornecedoras da UG (resumível/reboot-safe, educado). Rodando no Fundo 036100. Co-endereço = H-COEND (já existia). +6 testes.
- **06-11 cont.12:** **Alvo 2** — triagem de DD priorizada por órgão (`investigacao_orgao_dd.py`): ranqueia top fornecedores PJ da UG por grau/score + lista processos SEI a priorizar; CLI + render_md; 3 testes. Medido ao vivo TJRJ 030100/Fundo 036100: **top-por-valor = grandes prestadores legítimos (todos 🟢)** — achado honesto: **fachada/laranja mora na CAUDA, não no topo** (varredura de cauda = trabalho de background). Regra de corroboração confirmada (CAPITAL isolado score-8 não sobe a 🟡).
- **06-11 cont.11:** **Alvo 1 fechado** — `beneficios_sociais` wired no motor DD + Lex: **H-PEP** (PEP por nome do sócio = relação política) + **H-BENEFICIO** (benefício de subsistência por CPF = laranja), bounded/cacheado/honesto, seção II-E. Verificado ao vivo (PEP real, 2.9s). **br-acc avaliado/agregado** (`docs/AVALIACAO-BR-ACC.md`): NÃO Neo4j; **adotada a ponte de CPF mascarado middle-6** (`resolucao_cpf.py`, corpus 59,6k PF favorecidos) que **destrava H-BENEFICIO de sócio mascarado** (semente da resolução de entidade P0). +16 testes.
- **06-11 cont.10:** **FIX conceitual OB≠contrato≠processo** (`cardinalidade_contratual` honesta: TJRJ 1598 OBs/41 proc; Fundo 47895/338; nota + frase no relatório + skill Yoda) `4fff8bd`. Coletor **benefícios sociais (laranja) + PEP (relação política)** `beneficios_sociais.py` (DD Loop 2 base). br-acc entendido (grafo Neo4j de dados públicos — referência p/ fontes+entidade). Doc/MEMORY enxutos.
- **06-11 cont.9:** Lex seção II-E (apresenta a investigação DD) + sweeps reboot-safe (`recursos` boot-time + `@reboot` cron). `8c6c7e4`,`4981323`.
- **06-11 cont.8:** motor `investigacao_dd` (fachada/laranja, Loop 1) + wiring no Lex + BrasilAPI capital/porte. `63070cd`.
- **06-11 cont.7:** bom dia multi-fonte política + sempaywall; **CEIS/CNEP** corrigido (3 bugs, API); relatórios raciocinados (/relatorio+/orgao) + OSINT Querido Diário.
- **06-11 (1–6):** Cerebras em todos os pools; /orgao rico (sumário+geográfica+P×I); SEI sweep destravado (bug supervisor back-off infinito); rotação de chaves LLM (cooldown 12h billing); erros do Yoda mapeados/corrigidos.
- **06-09:** 23 loops de benchmark (pyproject/scorecard/golden, ruff 733→37, 4 bugs reais); frente SEI (reader funciona, `sei_sweep`/`sei_ficha`); /UG + busca de órgão; Lex de órgão; glifos do PDF corrigidos; este doc criado.
- **Anterior:** SIAFE 1+2 sweeps supervisionados + correlação OB↔SEI↔CNPJ; JFN 2.0 (12 ondas); Yoda/Hermes na VM.

## 11. ⏯️ RETOMADA (sessão nova: "continue pelo docs/REFERENCIA-PROJETO.md")
**Branch `feat/lista-limpa`, tudo commitado, serviços/sweeps vivos.** Instruções permanentes do dono:
1. Melhorar o projeto INTEIRO em **loops de qualidade máxima** (metodologia no topo deste doc).
2. **Testar tudo, nunca às cegas**; medir o **produto real** (PDF entregue) antes/depois.
3. **Honestidade** (§topo). **Isolamento de LLM** (§3). **Sweeps vivos** respeitando CPU (não rodar sweep+suíte+
   Playwright juntos — a VM já caiu por isso).
4. **Um só doc** = este, enxuto, 1 linha/sessão no §10. Detalhe no git.
5. Ao FIM de cada loop: debug + avaliar storage/RAM/CPU + registrar.

**Próximos alvos (maior alavancagem, pedidos do dono):**
1. **Wirar `beneficios_sociais` no motor DD + Lex** — H-PEP (PEP por NOME dos sócios do QSA, desmascarados →
   relação política) + H-BENEFICIO (benefício por CPF, só em CPF completo: PF favorecida; QSA mascarado=INDISPONÍVEL).
   Bounded+cacheado+honesto. Alimenta a seção II-E do Lex.
2. **Investigação priorizada TJRJ (030100) + Fundo Especial do TJ (036100)** — rodar a DD nos fornecedores dessas
   UGs (fachadas/laranjas) e priorizar o SEI sweep nesses processos. Considerar comando "investigar órgão".
3. **Cruzar OB+SEI+DD com inteligência** — agrupar OBs por processo/contrato (cardinalidade já medida em
   `cardinalidade_contratual`), seguir a árvore SEI (processo→atas/SRP→contratos→aditivos→OBs).
4. **br-acc** (github enioxt/br-acc): AVALIADO/AGREGADO → `docs/AVALIACAO-BR-ACC.md`. Já adotado: ponte
   CPF mascarado middle-6 (`resolucao_cpf.py`). PENDENTE: Splink (config br-acc = base) p/ resolução de
   entidade; ativar providers dormentes (GLEIF/OffshoreLeaks/OpenSanctions/TSE×contrato) nos produtos;
   ingerir CAGED/RAIS (anti-laranja por headcount) + PGFN. NÃO adotar Neo4j (SQLite/networkx).
5. proveniência/INDISPONÍVEL padronizada · resolução de entidade (Splink) · rodar SEI sweep aos poucos.
**Medir o produto antes/depois em cada um. Erros conceituais/conteúdo/código = NÃO permitidos (dono).**

---
*Doc enxuto de propósito. Conhecimento jurídico/operacional completo: `docs/CLAUDE-REFERENCIA-COMPLETA.md`.*
