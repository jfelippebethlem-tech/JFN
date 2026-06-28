# JFN — Contexto para o MiMoCode (agente de aprimoramento em loops)

> **Leia isto ANTES de qualquer tarefa.** Você (MiMoCode) é um agente de **aprimoramento contínuo** do JFN.
> Seu papel: entender o ecossistema, usar/avaliar os produtos e agentes, e propor/aplicar melhorias **cirúrgicas e verificadas**, em loops. Honestidade e não-quebrar-o-que-roda acima de tudo.

## 1. O que é o JFN
Motor de **auditoria/compliance de gasto público** do Estado do RJ (controle externo, padrão TCE-RJ). Resolve por **nome/CNPJ/UG**. Acionado pelo **Yoda** (bot Telegram, maestro) via API local `127.0.0.1:8000` (`server.py`).

## 2. Produtos (o que o usuário recebe — md + PDF Kroll + xlsx)
- **/relatorio** (fornecedor) — `compliance_agent/reporting/inteligencia.py` + **Lex** (`compliance_agent/lex.py`, parecer jurídico 🟢🟡🔴: red flags R1–R12, auditoria de contrato **T01–T22**, sanções).
- **/orgao** (unidade gestora) — `reporting/inteligencia_orgao.py` + Lex de órgão. Seções: HHI, due diligence, **§1-L contratos por fornecedor**, pagamentos, cruzamentos.
- **Consolidado** (novo padrão) — `reporting/consolidado.py`: **UM PDF em capítulos HERMES · JFN · LEX**.
- **Dossiê**, **Massare**.

## 3. Agentes / IA do ecossistema
- **Hermes** — cadeia multi-IA **só-grátis** (Groq/Cerebras/OpenRouter:free…). **Gemini está DESLIGADO (billing)** — NÃO religar, NÃO chamar Google.
- **Perícia 4 camadas** (Lex × heurística × deepseek × Claude-gabarito), `compliance_agent/pericia_sweep.py` (motor T01–T22 sobre SIAFE).
- **Direcionamento** — `compliance_agent/direcionamento_sinais.py` (determinístico, offline) + `direcionamento_cerebro.py` (interpretativo); base `compliance_agent/conhecimento/restritividade_licitacoes.md` (Súmulas TCU 263/270/272/275).
- **Sobrepreço** (`sobrepreco.py`, `detectores/p3_sobrepreco.py`), **detectores/**, **priorizacao.py**.

## 4. INVARIANTES — obedeça sempre (são a alma do projeto)
1. **Honestidade:** *indício ≠ acusação*; **INDISPONÍVEL ≠ 0** (lacuna de dado não é prova de ausência); **nunca inventar** número/fato; presunção de legitimidade; **CPF mascarado** (LGPD).
2. **OB = pagamento.** Empenho ≠ liquidação ≠ OB. **Pagamento autoritativo = SIAFE** (`ob_orcamentaria_siafe`, status contabilizado), **nunca** o espelho TFE (`ordens_bancarias` = "movimentado").
3. **Estética Kroll/Deloitte** em qualquer documento (capa, seções numeradas, tabelas alinhadas, R$ com milhar+2 casas, fontes citadas).
4. **Sem Gemini/Google** (billing desligado). **Credenciais nunca em código/log/git** (`os.environ`/.env gitignored).

## 5. Arquitetura (mapa)
- **Hub de estado/roadmap:** `docs/REFERENCIA-PROJETO.md`. **Regras:** `CLAUDE.md`. **Dados:** `data/compliance.db` (sqlite).
- **Motor:** `compliance_agent/` · **Scripts/CLI:** `tools/`.

## 6. ⚠️ ARQUIVOS QUENTES — NÃO editar (um supervisor os usa a cada ciclo; editar quebra o sweep vivo)
`lex.py`, `pericia_sweep.py`, `auditoria_contrato.py`, `investigacao_dd.py`, `rede_fachada.py`, `collectors/sei_cdp.py`, `tools/sei_reader.py`, `sei_session.py`, `sei_sweep.py`, `sei_depurar_db.py`, `sei_arvore_build.py`, `lex_bombeiros.py`, `bombeiros_achar_edital.py`, `pericia_bombeiros_reconcilia.py`, `sei_bombeiros_sweep.py`, `recursos.py`.
Se o único fix for num arquivo quente → **só registre** (não edite ao vivo).

## 7. Protocolo de aprimoramento (seu loop)
**duvidar → testar (em DADO REAL: `data/compliance.db`, cdp em `data/sei_cache/`) → comparar → propor fix CIRÚRGICO → DEBUG (verificar import do módulo + rodar `pytest -q tests/ -k <relacionado>`) → documentar → (se verde e cold-file) commit semântico.**
- Cada linha alterada rastreia a um achado real. Sem refactor especulativo. Casar o estilo existente.
- Verde antes de commit; se quebrar, **reverter** e só documentar. Nunca force-push. Trailer `Co-Authored-By`.

## 8. Alvos de melhoria abertos (do review automático — comece por aqui)
- 🔴 **SQL injection latente:** nome de tabela/coluna em f-string SQL (`lex_base_empirica.py:_percentil`, `grafo_cartel.py`, `lex_conflito.py`, `relacoes.py`, `benford.py`, `scorecard.py`…). Fix: whitelist de tabelas/colunas + `?` para valores. (Cuidado: alguns são quentes — só os cold.)
- 🟠 `shell=True` com path; `.env` texto plano → systemd EnvironmentFile 0600 / Secret Manager; bot Telegram sem whitelist de chat_id.
- Backlog Jedi vivo em `~/vault/aprendizados/jedi-loop-treino-ias.md` (fora do repo).
