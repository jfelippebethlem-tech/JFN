# SEI — Protocolo de Operação SEGURA (anti-bloqueio)

> Acesso LEGÍTIMO do Mestre Jorge (deputado, login interno ITERJ) para auditoria/compliance.
> Objetivo: operar como um HUMANO cuidadoso — nunca martelar o servidor, nunca ser bloqueado.
> Credenciais ficam SÓ no ~/.hermes/.env (SEI_USUARIO/SEI_SENHA/SEI_ORGAO). Nunca no git/chat/log.

## Regras de ouro (ritmo humano)
1. **1 requisição por vez** — NUNCA em paralelo. Nada de disparar 10 buscas juntas.
2. **Pausa entre ações: 4 a 9 segundos ALEATÓRIOS** (não fixo — fixo parece robô).
3. **Pausa maior entre processos: 15 a 40 s** aleatórios.
4. **Limite por sessão**: no máx. ~30–50 buscas, depois descansar 10–20 min.
5. **Horário**: preferir fora de pico (madrugada/fim de semana) pra não pesar no sistema.
6. **Sessão/cookies reaproveitados** — logar uma vez, manter a sessão (não relogar a cada busca).
7. **Se aparecer CAPTCHA ou bloqueio: PARAR.** Esperar bastante (horas) e avisar o Mestre Jorge.
   NUNCA tentar quebrar proteção à força nem em loop rápido.
8. **Respeitar robots/limites** e nunca burlar TLS/SSL (regra do ecossistema).

## Plano de teste INCREMENTAL (do mais seguro pro mais completo)
- **Fase 0 (já existe):** busca PÚBLICA de processo (`sei_portal.buscar_processo`) — sem login. Validar com 1–2 números reais, com pausas.
- **Fase 1:** pegar uns números de processo a partir do **SIAFE 2 Rio** (empenhos/contratos) e buscar cada um no SEI público, devagar.
- **Fase 2:** **cruzamento de dados** — casar processo SEI ↔ contrato/empenho SIAFE (mesmo nº, fornecedor, valor) e gerar relatório de red flags.
- **Fase 3 (só se necessário):** acesso AUTENTICADO (login ITERJ) para processos restritos — com TODO o protocolo acima, e só após o Mestre Jorge validar a Fase 2.

## Pipeline (esboço)
SIAFE 2 (empenhos/contratos) ──► extrai nº processo SEI
        │
        ▼
SEI público (devagar, com pausas) ──► metadados + documentos + partes
        │
        ▼
Cruzamento (nº/fornecedor/valor/datas) ──► red flags ──► relatório .pdf/.docx + alerta Telegram

## Como o agente deve rodar (instrução pra modelo limitado)
- Faça UMA busca, espere 4–9s, faça a próxima. Nunca apresse.
- Se der erro/captcha, PARE e reporte. Não fique tentando rápido.
- Salve resultados em arquivo (cache) pra não repetir busca à toa.
- Trabalhe sempre a partir de uma LISTA de números (do SIAFE), não varrendo tudo.
