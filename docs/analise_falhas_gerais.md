# Análise de Falhas Gerais e Lições Aprendidas

Este documento consolida as observações e "armadilhas" encontradas durante a revisão exaustiva do repositório `JFN` e as interações recentes, com o objetivo de aprimorar futuras interações e o desenvolvimento do agente.

## 1. Comunicação e Interação com o Mestre Jorge

### 1.1. Estilo de Comunicação
*   **Problema**: Uso excessivo e repetitivo do nome "Mestre Jorge", resultando em uma comunicação pouco natural e formal demais.
*   **Lição Aprendida**: Priorizar a naturalidade, reservando o uso do nome para momentos de início de tarefa, confirmação crítica ou para evitar ambiguidade. Respostas devem ser curtas e factuais, sem prolixidade. (Referência: `JFN/docs/analise_modelo_sessao_atual.md`)

### 1.2. Gerenciamento de Requisitos e Alterações
*   **Problema**: Instruções do usuário podem mudar ou ser corrigidas durante o processo, exigindo adaptação rápida e atualização de informações já processadas.
*   **Lição Aprendida**: Manter flexibilidade e capacidade de reprocessar informações, garantindo que as fontes de verdade (como as preferências do Mestre Jorge) sejam sempre as mais atualizadas.

### 1.3. Prolixidade nas Respostas do Agente (Auto-avaliação)
*   **Problema**: Tendência a fornecer respostas muito longas, incluindo introduções e recapitulações desnecessárias antes de cada ação ou etapa, mesmo após a solicitação do Mestre Jorge por respostas curtas e factuais.
*   **Lição Aprendida**: Esforçar-se para ser mais conciso e direto. As atualizações devem ser breves, focando no progresso e resultados, e evitando justificativas internas ou descrições repetitivas, a menos que explicitamente solicitado. A meta é minimizar a verbosidade e otimizar o tempo do Mestre Jorge.

## 2. Desafios Técnicos e de Ferramentas

### 2.1. Leitura de Arquivos Grandes (`read_file`)
*   **Problema**: A ferramenta `read_file` possui um limite de 500 linhas/100KB, truncando arquivos maiores.
*   **Lição Aprendida**: Para arquivos extensos, usar o parâmetro `offset` para ler em partes, garantindo a cobertura total do conteúdo.

### 2.2. Contexto de Trabalho (`terminal` e `workdir`)
*   **Problema**: Comandos `git` e outros comandos de shell podem operar no diretório errado se o `workdir` não for explicitamente especificado.
*   **Lição Aprendida**: Sempre definir o `workdir` para `/home/jfelippebethlem/JFN` (ou `c:/JFN/jfn`) ao executar comandos que afetam o repositório, para evitar operações em locais inesperados.

### 2.3. Divergência de Branches Git
*   **Problema**: Arquivos foram commitados em `claude/yoda-deploy-relatorio-20260604` em vez do branch local `claude/rj-finance-agent-BYlhJ`, conforme a instrução original.
*   **Lição Aprendida**: Confirmar e aderir estritamente ao branch de trabalho especificado para todas as alterações de código e documentação. Se houver necessidade de um branch temporário para relatórios ou depuração, garantir que o merge para o branch principal seja feito ou que as informações críticas sejam transferidas corretamente.

### 2.4. Acesso a Redes Externas e Automação de Navegador
*   **Problema**: Bloqueios de rede (ex: `net::ERR_NAME_NOT_RESOLVED` para Facebook) e a necessidade de um Chrome em modo debug (porta 9222) para a automação do SIAFE/SEI.
*   **Lição Aprendida**: Reconhecer e reportar claramente as limitações de acesso à rede. Instruir o usuário sobre a configuração necessária do ambiente (ex: iniciar Chrome com `--remote-debugging-port=9222`) para funcionalidades de automação.

### 2.5. Instalação de Dependências Python
*   **Problema**: Falhas devido a bibliotecas Python ausentes (ex: `python-docx`, `fpdf2`, `httpx` no `groq_explorer.py`).
*   **Lição Aprendida**: Incluir verificações de dependências ou passos de instalação explícitos nos scripts ou na documentação de setup, e ser proativo na identificação e sugestão de instalação de pacotes quando erros de `ImportError` ocorrerem.

### 2.6. Automação de UI Complexa (Oracle ADF / Vaadin)
*   **Problema**: A complexidade das interfaces web do SIAFE2 e FlexVision, que usam frameworks como Oracle ADF e Vaadin, exige seletores CSS específicos, `page.evaluate()` com JavaScript, e `await` para a renderização da página.
*   **Lição Aprendida**: Utilizar os helpers JavaScript (`_js_click_exact`, `_js_click_contains`, `_js_dblclick_contains`, `_js_click_valo_span`) e as funções de espera (`_adf_wait`, `_vaadin_settle`) para garantir a estabilidade da automação.

## 3. Observações sobre o Código/Projeto JFN

### 3.1. Modularidade e Abstração
*   **Observação**: O projeto apresenta boa modularidade, com responsabilidades bem definidas entre coletores, regras, banco de dados e agentes. No entanto, o `compliance_agent/rules/engine.py` centraliza muitas regras e importa diversos modelos, indicando uma alta coesão, mas também um ponto de alta complexidade.
*   **Recomendação**: Continuar monitorando a complexidade do `engine.py` e, se necessário, considerar a refatoração de regras em módulos menores ou classes dedicadas se a manutenção se tornar um desafio.

### 3.2. Resiliência de LLMs
*   **Observação**: A implementação de cascata de modelos e retry em `compliance_agent/llm/free_llm.py` e `siafe_agent/agent.py` demonstra uma preocupação robusta com a resiliência e disponibilidade do LLM, utilizando fallbacks para outros provedores em caso de limite de taxa (`429`).
*   **Confirmação**: Esta abordagem é eficaz para garantir a continuidade da operação mesmo com modelos gratuitos que podem ter limites de uso.

### 3.3. Persistência de Dados
*   **Observação**: O uso de SQLite para armazenar alertas, ordens bancárias, publicações DOERJ, sessões de auditoria e memória de aprendizado é fundamental para a persistência do estado e conhecimento do agente entre as execuções.
*   **Confirmação**: A arquitetura com `compliance.db` centraliza o estado, permitindo a retomada de tarefas e o crescimento do conhecimento do agente.
