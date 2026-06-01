# JFN Compliance Agent — Checklist de Funções

Auditoria contínua das finanças do Estado do RJ (SIAFE2 + DOERJ), autônoma,
controlada pelo celular. Última revisão: 01/06/2026.

---

## ✅ 1. Coleta de dados (SIAFE2 + DOERJ)

| Função | Onde | Status |
|---|---|---|
| Ler OB Orçamentária (lista completa) | `collectors/siafe_ob.py` → `collect_ob_day` | ✅ |
| Abrir cada OB e ler abas (Detalhamento, Processo) | `siafe_ob.py` → `collect_ob_details` | ✅ |
| Extrair favorecido, valor, processo SEI | `siafe_ob.py` → `_extract_ob_fields` | ✅ |
| Navegação ADF sem crash (menu, nunca goto direto) | `siafe_ob.py` → `_navigate_to_ob` | ✅ |
| **Login automático no SIAFE2** | `siafe_ob.py` → `_fazer_login` | ✅ |
| **Re-login quando a sessão expira (~1h)** | `siafe_ob.py` → `_check_session_and_recover` | ✅ |
| Coletar DOERJ do dia + edições extras | `collectors/doerj.py` | ✅ |
| DOERJ via Chrome (sem bloqueio 403) | `collectors/doerj.py` | ✅ |

## ✅ 2. Inteligência e análise

| Função | Onde | Status |
|---|---|---|
| Regras fixas de compliance | `rules/engine.py` → `MotorCompliance` | ✅ |
| Análise de OBs com Groq (IA) | `llm/groq_agent.py` → `analisar_obs_com_groq` | ✅ |
| Análise do DOERJ com Groq | `groq_agent.py` → `analisar_doerj_com_groq` | ✅ |
| Navegação autônoma do SIAFE2 com IA | `groq_agent.py` → `navigate_autonomous` | ✅ |
| Detecção estatística de anomalias | `analysis/anomaly_detector.py` | ✅ |
| Fracionamento, concentração, rajada fim de mês | `anomaly_detector.py` | ✅ |
| Grafo de corrupção (servidor→empresa←UG) | `analysis/graph_analyzer.py` | ✅ |

## ✅ 3. Fontes externas gratuitas (super auditor)

| Função | Onde | Status |
|---|---|---|
| CEIS/CNEP — empresas sancionadas | `collectors/ceis.py` | ✅ |
| CNPJ — situação cadastral (BrasilAPI) | `enrichers/cnpj_enricher.py` | ✅ |
| PNCP — contrato publicado? | `collectors/pncp.py` | ✅ |
| Querido Diário — histórico no DOERJ | `collectors/querido_diario.py` | ✅ |
| CAGED — múltiplos empregos | `collectors/caged.py` | ✅ |
| TSE — doações × contratos | `collectors/tse.py` | ✅ |
| **Pesquisa na INTERNET (pessoas/CNPJs)** | `collectors/web_research.py` → `investigar` | ✅ |
| DuckDuckGo + notícias + detecção de risco | `web_research.py` | ✅ |
| Investigação automática de OBs alto valor | `web_research.py` → `investigar_obs_alto_valor` | ✅ |
| **SEI-RJ — consulta de processos** | `collectors/sei_portal.py` (ligado ao Telegram + pipeline) | ✅ |

## ✅ 3b. Dashboard profissional (web)

| Função | Onde | Status |
|---|---|---|
| Painel institucional (PC e celular) | `static/dashboard.html` | ✅ |
| KPIs: OBs hoje, valor, alertas | `server.py` → `/api/compliance/painel` | ✅ |
| Lista de alertas com severidade | dashboard | ✅ |
| OBs recentes + maiores favorecidos | dashboard | ✅ |
| Investigar pessoa/CNPJ pela web | `server.py` → `/api/compliance/investigar` | ✅ |
| Lições aprendidas exibidas | dashboard | ✅ |
| Atualiza sozinho a cada 30s | dashboard | ✅ |
| Sobe junto com o agente | `JFN.bat` passo 7 | ✅ |

## ✅ 4. Memória e aprendizado (Hermes + contextual)

| Função | Onde | Status |
|---|---|---|
| Memória persistente no banco | `database/models.py` → `MemoriaAprendizado` | ✅ |
| Aprender fatos (confiança cresce com repetição) | `llm/memoria.py` → `aprender` | ✅ |
| Conhecimento-base da administração pública RJ | `memoria.py` → `CONTEXTO_INICIAL` | ✅ |
| Injetar conhecimento nos prompts da IA | `memoria.py` → `contexto_para_prompt` | ✅ |
| **Reflexão diária com Hermes-3 405B** | `memoria.py` → `refletir_com_hermes` | ✅ |
| Perfil acumulado de empresas/pessoas | `memoria.py` → `registrar_entidade` | ✅ |

## ✅ 5. Operação contínua + autonomia

| Função | Onde | Status |
|---|---|---|
| **Cérebro orquestrador (IA grátis decide o que investigar)** | `llm/orquestrador.py` → `loop_investigador_autonomo` | ✅ |
| Escolhe alvos suspeitos sozinho (24/7) | `orquestrador.py` → `escolher_proximo_alvo` | ✅ |
| Investiga a fundo com 22 ferramentas + web | `orquestrador.py` → `investigar_alvo` | ✅ |
| Aprende cada investigação na memória | `orquestrador.py` | ✅ |
| Alerta no Telegram quando acha risco | `orquestrador.py` → `_alertar_investigacao` | ✅ |
| Respeita rate limit do LLM grátis | `orquestrador.py` (pausa 10min entre alvos) | ✅ |
| **Monitoramento contínuo (a cada 15 min, 7h-20h)** | `scheduler.py` → `loop_monitoramento` | ✅ |
| **Relatório completo só às 08:00** | `scheduler.py` → `loop_relatorio` | ✅ |
| Análise rápida de OB nova (alerta na hora) | `scheduler.py` → `_analisar_ob_rapida` | ✅ |
| **Auto-restart se um loop cair** | `scheduler.py` → `_loop_resiliente` | ✅ |
| **Auto-restart se o Python cair** | `JFN.bat` → loop `:rodar_agente` | ✅ |
| Aviso "estou online" no Telegram ao subir | `scheduler.py` → `_ping_inicio` | ✅ |
| Aviso de erro/queda no Telegram | `scheduler.py` → `_loop_resiliente` | ✅ |

## ✅ 6. Controle pelo celular (Telegram)

| Comando | O que faz | Status |
|---|---|---|
| **conversa livre** | pergunta em português, IA responde com dados reais | ✅ |
| `/status` | situação do sistema | ✅ |
| `/obs` | últimas OBs coletadas | ✅ |
| `/alertas` | alertas de alta severidade | ✅ |
| `/buscar NOME` | pesquisa empresa/pessoa no banco | ✅ |
| `/top` | ranking dos maiores favorecidos | ✅ |
| `/sancoes` | atualiza e verifica CEIS/CNEP | ✅ |
| `/agora` | dispara ciclo completo agora | ✅ |
| `/relatorio` | envia PDF do dia | ✅ |
| `/aprendi` | lições que o Hermes extraiu | ✅ |
| `/memoria NOME` | perfil acumulado de uma entidade | ✅ |
| `/investigar NOME` | pesquisa na INTERNET (notícias, riscos) | ✅ |
| `/sei NUMERO` | consulta processo no SEI-RJ | ✅ |
| `/painel` | link do dashboard web (PC e celular) | ✅ |
| `/chrome` | como abrir o Chrome no modo correto | ✅ |
| Alertas urgentes empurrados na hora | `notifications/telegram.py` | ✅ |
| Relatório diário automático às 08:00 | `scheduler.py` | ✅ |

## ✅ 7. Inicialização com um comando

| Função | Onde | Status |
|---|---|---|
| **Abrir tudo num clique** (cadeia de 7 passos) | `JFN.bat` | ✅ |
| Carrega .env, valida credenciais | `JFN.bat` passo 1 | ✅ |
| git pull automático | `JFN.bat` passo 2 | ✅ |
| Instala dependências se faltar | `JFN.bat` passo 3 | ✅ |
| Abre Chrome modo debug no SIAFE2 e espera subir | `JFN.bat` passo 5 | ✅ |
| Cada passo só avança se o anterior deu certo | `JFN.bat` | ✅ |
| **Início automático quando o PC liga** | `configurar_tudo.bat` | ✅ |
| **Integração Chrome Remote Desktop** | `configurar_tudo.bat` | ✅ |
| Relatório/PDF do banco | `reports/pdf.py` | ✅ |
| Dashboard web (opcional) | `server.py` | ✅ |

---

## Como usar (resumo)

1. **Uma vez só:** duplo clique em `configurar_tudo.bat`
   (início automático + acesso remoto pelo celular)
2. **Para ligar:** duplo clique em `JFN.bat`
3. **Pelo celular:** abra o Telegram, mande `/start`, depois fale à vontade
   ("tem alerta grave hoje?") ou use os comandos.

O agente roda sozinho, aprende a cada dia, re-loga quando precisa e avisa
você no celular se achar algo grave ou se ele mesmo tiver algum problema.
