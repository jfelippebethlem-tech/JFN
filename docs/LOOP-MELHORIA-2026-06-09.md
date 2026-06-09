# Loop de Melhoria Contínua do Ecossistema JFN — log por checkpoint

> Meta (dono): 5 loops de **backtest → análise total → reavaliação → planejamento (best practices/benchmarks)
> → execução**, com checkpoints/commits e documentação de **erros & acertos** para as próximas IAs.
> Visão-norte: outputs perfeitos · ecossistema integrado, baixa fricção · grátis (respeita a VM) · rápido,
> fluido, belo, sem ruído · **sistema pensante** nos relatórios JFN, pareceres Lex e previsões Massare.
> Branch: `feat/lista-limpa` (mudanças pequenas, isoladas, verificadas com o artefato real).

## Princípios herdados (da V2 revertida — ver [[licao-v2-revertida-2026-06-08]])
1. Gerar o **artefato real** (relatório/parecer) como baseline e comparar a cada mudança.
2. **Wiring mínimo**: ligar uma peça nova só nos pontos certos; nunca LLM síncrono no hot-path sem cache+bound+verificação.
3. Mudança **pequena, isolada, verificada** > camada grande.

---

## ✅ Loop 1 — checkpoint (2026-06-08/09)

**Plano:** re-aplicar os ganhos de qualidade da V2 **sem a fragilidade**; começar pelo "sistema pensante" do Lex (onde/por quê).

**Execução (commits em `feat/lista-limpa`):**
1. `/lista` curado — 7426→1011 chars (10 funções/3 grupos vs 47 itens crus). Catálogo completo no `/skills`.
2. Sumarizar OBs — top-12/exercício no MD e PDF (fornecedor FPDF + órgão); lista completa na planilha XLSX.
   ITERJ: PDF 253KB→**63KB**. (O PDF-HTML do fornecedor já era agregado.)
3. LLM do motor robusto — rotação do pool de **9 chaves** (`~/.hermes/.env`, as do JFN/.env estavam mortas)
   + **multi-modelo** (flash→2.0-flash→flash-lite) + backoff + bridge `gerar_sync` (loop dedicado). 3/3 ao vivo.
4. **Análise DISCURSIVA do Lex** — `_trecho` captura o excerpt; `analise_discursiva` (1 chamada LLM, bounded
   45s, degrada honesto) escreve 2-4 frases **onde+por quê (mecanismo)** ancoradas no texto real; render no parecer.
5. Guard `_eh_interface_sei` — rejeita a tela/menu do SEI como conteúdo.

**ACERTOS:**
- O pipeline discursivo funciona e é **honesto** (o LLM flagrou sozinho que o trecho era menu, não documento).
- Relatórios enxutos + `/lista` limpo = menos ruído, mais beleza (alinha com a visão).
- LLM agora resiliente (multi-modelo+pool) sem bolar no hot-path de tudo — wiring mínimo (só no Lex, sob flag).

**ERRO/ACHADO CRÍTICO (avaliação do artefato real):** a **leitura do SEI retorna o MENU** ("Controle de
Prazos / Processos recebidos (N registros)"), não o inteiro teor → a análise "onde/por quê" fica sem input
real. O parecer chegava a "analisar o menu". Mitigado com o guard (agora honesto: "não lido"). **A RAIZ é o
coletor SEI** (`collectors/sei_cdp.py` / `sei_reader`): loga mas não navega até o documento do processo.

**Benchmark de referência:** due diligence padrão Kroll/Deloitte/Control Risks — prosa analítica que cita
**onde** (cláusula/§) e **por quê** (mecanismo: quem foi eliminado, qual o efeito). Só alcançável com o
documento real em mãos → depende do coletor SEI.

**→ Alvo do Loop 2:** consertar o coletor SEI para extrair o **inteiro teor do processo** (não o menu).
Sem isso, o "sistema pensante" do Lex fica honesto porém sem matéria-prima.

---

## ✅ Loop 1 — wiring Yoda↔JFN (teste end-to-end)
**Teste:** `hermes -z "qual o status da coleta do SIAFE? quantas OBs?"` (one-shot, sem mexer no bot vivo).
**ANTES:** Yoda respondia *"comando `status` desconhecido"* — `siafe_stats` existia mas o `quando_usar` só
cobria "quantas OBs"; não havia capability para `/api/siafe/status`.
**FIX:** enriqueci `siafe_stats.quando_usar` (status/cobertura/quanto coletamos) + registrei `siafe_status`
(lockfile). Regenerei os derivados (`~/.hermes/jfn_tools.json` lido pelo gateway).
**DEPOIS (verificado):** Yoda retorna OBs/ano (2016-2026), total R$ 20,16 bi, fonte SIAFE-Rio 2. ✅
**Aprendizado:** rota existir no `server.py` ≠ Yoda saber usá-la. O wiring real é o `capabilities.yaml`
(+ derivados regenerados) com `quando_usar` que casa a linguagem natural do dono. Testar com `hermes -z` pega
gaps que o curl não pega.

⚠️ **Pendente:** o `jfn.service` vivo ainda roda código anterior aos commits OB-enxuta/LLM/Lex-discursivo —
fazer `systemctl --user restart jfn.service` num momento ocioso (não durante geração de relatório do dono).

## Loop 2 — (planejado) coletor SEI: navegar até o documento
Alvo: `collectors/sei_cdp.py`/`sei_reader` extrair o INTEIRO TEOR (não o menu). Desbloqueia o "onde/por quê"
do Lex. Verificar com parecer real (CNPJ com SEI lido) — a análise discursiva deve citar trecho de documento,
não de interface. (a executar)
