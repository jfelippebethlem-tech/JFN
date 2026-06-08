# CAPACIDADES (gerado de capabilities.yaml — NÃO editar à mão)

Versão 2.1.0 · base HTTP `http://127.0.0.1:8000` · CLI `cd ~/JFN && PYTHONPATH=. .venv/bin/python -m`

| id | agente | tipo | rota/comando | status | quando usar |
|---|---|---|---|---|---|
| `anomalias` | jfn | http | `/api/anomalias` | PRONTO | triagem de risco; 'algo estranho em X' |
| `cartel` | jfn | http | `/api/cartel` | PRONTO | conluio/cartel/combinacao |
| `conflito_doador_contrato` | lex | http | `/api/conflito` | PRONTO | 'quem me doou ganhou contrato', conflito de interesse |
| `cruzamento` | jfn | http | `/api/cruzamento` | PRONTO | 'cruze os dados da empresa X' |
| `missao_autonoma` | jfn | http | `/api/hermes/missao` | PRONTO | pedido complexo/aberto |
| `relatorio_inteligencia` | jfn | http | `/api/relatorio/inteligencia` | PRONTO | relatorio/auditoria/due diligence de empresa, CNPJ |
| `relatorio_orgao` | jfn | http | `/api/relatorio/orgao` | PRONTO | auditoria de orgao/UG/secretaria |
| `sobrepreco` | lex | http | `/api/sobrepreco` | PRONTO | 'esta caro?', superfaturamento, R4 |
| `enriquecer_socios` | jfn | cli | `tools.enriquecer_socios_ob` | PRONTO | apos novo sweep |
| `siafe_atualizar` | jfn | http | `/api/siafe/atualizar` | PRONTO | 'atualize o SIAFE' |
| `siafe_coletar_ug` | jfn | cli | `compliance_agent.siafe_runner ug <UG> [ANO]` | PRONTO | backfill de UG |
| `siafe_stats` | jfn | http | `/api/siafe/stats` | PRONTO | 'quantas OBs temos' |
| `dossie` | jfn | http | `/api/dossie` | PRONTO | 'monte um dossie sobre X' |
| `grafo_poder` | jfn | http | `/api/grafo` | PRONTO | 'quem esta ligado a X', 'a N saltos do deputado Y com contrato' |
| `busca_juridica` | lex | cli | `compliance_agent.collectors.lexml_fetcher --termo "<TERMO>"` | PRONTO | 'qual a lei sobre...', jurisprudencia |
| `buscar_direcionamento` | lex | http | `/api/sei/direcionamento` | PRONTO | 'ache editais restritivos na UG X' |
| `consultar_pncp` | lex | http | `/api/pncp` | PRONTO | analisar licitacao SEM SEI; editais por UF/orgao/fornecedor; preventivo (abertos) |
| `instrumento_mandato` | lex | http | `/api/mandato/minuta` | ONDA 10 | 'faca um requerimento sobre esse contrato' |
| `ler_processo_sei` | lex | cli | `tools.sei_reader "<NUMERO>"` | PRONTO | ler/analisar um processo SEI especifico. FORMATO do numero: 'SEI-UUUUUU/NNNNNN/AAAA' (ex.: SEI-070002/008633/2022) ou 'E-NN/NNN/AAAA' (ex.: E-12/345/2026) — unidade/sequencial/ano. Aceita com ou sem o prefixo SEI-. |
| `parecer_juridico` | lex | cli | `compliance_agent.lex "<empresa|cnpj>"` | PRONTO | 'tem direcionamento?', parecer |
| `massare_calendario` | massare | http | `/api/massare/calendario` | ONDA 8 | 'agenda da semana', 'tem dado importante hoje?' |
| `massare_carteira` | massare | http | `/api/massare/carteira` | ONDA 9 | 'como esta minha carteira' |
| `massare_cenarios` | massare | http | `/api/massare/cenarios` | PRONTO | 'como esta o mercado', 'dolar/bolsa/ouro hoje' |
| `massare_focus` | massare | http | `/api/massare/focus` | ONDA 8 | 'o que o mercado espera de juros/inflacao' |
| `massare_fundamentos` | massare | http | `/api/massare/fundamentos` | ONDA 8 | 'fundamentos da PETR4' |
| `massare_placar` | massare | http | `/api/massare/placar` | PRONTO | 'o Massare acerta?' |
| `massare_prever` | massare | http | `/api/massare/prever` | PRONTO | 'previsao do Ibovespa', 'BTC vai subir?' |
| `massare_teses` | massare | http | `/api/massare/teses` | ONDA 9 | 'quais as teses agora', 'o que move o mercado' |
| `radar_status` | jfn | http | `/api/radar/status` | PRONTO | 'o que voce monitora', 'teve alerta hoje' |
| `vigiar` | jfn | http | `/api/radar/vigiar` | PRONTO | '/vigiar <cnpj|ug|nome>' |
| `skill_detalhe` | yoda | cli | `telegram /skill <id>` | PRONTO | 'como funciona a skill X', detalhe de uma capacidade |
| `skills` | yoda | cli | `telegram /skills [filtro]` | PRONTO | 'o que voce sabe fazer', 'quais skills', 'capacidades' |
| `skills_reload` | yoda | cli | `telegram /skills_reload` | PRONTO | apos editar o YAML na VM |
| `skills_sync` | yoda | cli | `telegram /skills_sync` | PRONTO | apos git push do repo |
| `skills_validate` | yoda | cli | `telegram /skills_validate` | PRONTO | antes de sync/reload, sanidade do contrato |
| `status_jfn` | jfn | http | `/status` | PRONTO | diagnostico |
| `trace` | jfn | http | `/api/trace/{correlation_id}` | ONDA 0 | debug |

> Regra do roteador: o Yoda só chama `id` com status **PRONTO**. Fora do registro = erro explícito ('não tenho ferramenta para isso'), nunca invenção.
