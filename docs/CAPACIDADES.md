# CAPACIDADES (gerado de capabilities.yaml — NÃO editar à mão)

Versão 2.1.0 · base HTTP `http://127.0.0.1:8000` · CLI `cd ~/JFN && PYTHONPATH=. .venv/bin/python -m`

| id | agente | tipo | rota/comando | status | quando usar |
|---|---|---|---|---|---|
| `anomalias` | jfn | http | `/api/anomalias` | PRONTO | triagem de risco; 'algo estranho em X' |
| `cartel` | jfn | http | `/api/cartel` | PRONTO | conluio/cartel/combinacao; 'os concorrentes do fornecedor X tem socio em comum?' |
| `concentracao_grupo` | jfn | cli | `compliance_agent.grafo_cartel --vizinhanca <CNPJ>` | PRONTO | 'ha concentracao escondida por grupo na UG X?', 'esses concorrentes sao na verdade o mesmo grupo?', cartel oculto / concorrencia simulada numa UG |
| `conflito_doador_contrato` | lex | http | `/api/conflito` | PRONTO | 'quem me doou ganhou contrato', conflito de interesse |
| `contratos_parecer` | jfn | cli | `tools/contratos_parecer.py [--max-contratos N] [--telegram]` | PRONTO | 'analise/parecer dos contratos', 'esse contrato tem aditivo/sobrepreco irregular?', 'como um tribunal de contas' |
| `cruzamento` | jfn | http | `/api/cruzamento` | PRONTO | 'cruze os dados da empresa X' |
| `editais_corpus` | jfn | cli | `tools/editais_corpus.py [--limite N]` | PRONTO | 'atualizar editais', 'baixar editais da prefeitura' |
| `editais_direcionamento` | jfn | cli | `tools/editais_direcionamento.py [--clausulas] [--clusters] [--max-candidatas N]` | PRONTO | 'ha direcionamento nos editais?', 'compare os editais de X', 'quais exigencias reduzem competitividade' |
| `emendas_coletar` | jfn | cli | `tools/emendas_coletar.py [--anos 2019 ... 2026]` | PRONTO | 'atualizar emendas', 'coletar emendas do deputado X / destino Y' |
| `emendas_pericia` | jfn | cli | `tools/emendas_pericia.py [--telegram] [--sem-pdf]` | PRONTO | 'pericia/analise das emendas', 'quais emendas suspeitas' |
| `listar_ugs` | jfn | http | `/api/ugs` | PRONTO | '/ug', 'quais os codigos/nomes dos orgaos/UGs', 'listar UGs', 'qual o codigo da SEEDUC', 'que orgaos existem', ANTES de pedir o /orgao quando nao se sabe o codigo |
| `missao_autonoma` | jfn | http | `/api/hermes/missao` | PRONTO | pedido complexo/aberto |
| `missao_estado` | jfn | http | `/api/hermes/estado` | PRONTO | 'qual a missao', 'como esta o hermes/auditor', antes de trabalhar/parar |
| `missao_parar` | jfn | http | `/api/hermes/parar` | PRONTO | 'para/pare a missao', 'cancela a auditoria autonoma' |
| `missao_trabalhar` | jfn | http | `/api/hermes/trabalhar` | PRONTO | 'trabalha na missao', 'continua a auditoria' (pedido EXPLICITO do dono) |
| `nucleo_pericia` | jfn | http | `/api/nucleo/comando` | PRONTO | 'pericia a empresa X / OB Y', 'veredito confirmado/descartado', 'placar do nucleo', 'essa empresa e fantasma/laranja?', 'fantasma cnpj X', 'fases da contratacao' |
| `pcrj_gastos_coletar` | jfn | cli | `tools/pcrj_gastos_coletar.py [--ini AAAAMMDD --fim AAAAMMDD]` | PRONTO | 'atualizar gastos/contratos da prefeitura do Rio' |
| `pcrj_pericia_gastos` | jfn | cli | `tools/pcrj_pericia_gastos.py [--telegram] [--sem-pdf]` | PRONTO | 'pericia dos gastos da prefeitura', 'fracionamento na PCRJ' |
| `relacoes` | jfn | cli | `compliance_agent.relacoes "<CNPJ | nome do socio | UG>"` | PRONTO | 'onde a empresa/socio X se relaciona', 'que empresas tem socio em comum com Y', 'quem sao os fornecedores ligados na UG Z', rede societaria de um alvo |
| `relatorio_inteligencia` | jfn | http | `/api/relatorio/inteligencia` | PRONTO | relatorio/auditoria/due diligence de empresa, CNPJ |
| `relatorio_orgao` | jfn | http | `/api/relatorio/orgao` | PRONTO | auditoria de orgao/UG/secretaria |
| `rodizio` | jfn | http | `/api/rodizio` | PRONTO | rodizio/revezamento de vencedores; 'a UG X tem fornecedores que se alternam no 1o lugar?' |
| `sobrepreco` | lex | http | `/api/sobrepreco` | PRONTO | 'esta caro?', superfaturamento, R4 |
| `sobrepreco_interno` | lex | cli | `compliance_agent.precos_extract` | PRONTO | 'esse item esta caro comparado a outros orgaos?', dispersao de preco unitario do mesmo produto sem precisar de CATMAT/mercado, complemento interno ao /sobrepreco |
| `bond_captura` | bond | cli | `desktop: telegram /capturar (poller) ou captura_nodriver.py` | ONDA 0 | ver quem curtiu posts do IG / leaderboard de engajamento do gabinete; SO no desktop residencial, NUNCA na VM (= ban) |
| `cruzador` | jfn | cli | `bash tools/cruzador.sh` | PRONTO | rotina automatica noturna; acionar a mao so p/ recruzar apos coleta grande |
| `enriquecer_socios` | jfn | cli | `tools.enriquecer_socios_ob` | PRONTO | apos novo sweep |
| `siafe_atualizar` | jfn | http | `/api/siafe/atualizar` | PRONTO | 'atualize o SIAFE' |
| `siafe_coletar_ug` | jfn | cli | `compliance_agent.siafe_runner ug <UG> [ANO]` | PRONTO | backfill de UG |
| `siafe_stats` | jfn | http | `/api/siafe/stats` | PRONTO | 'quantas OBs temos', 'status/cobertura da coleta SIAFE', 'quanto ja coletamos', 'o SIAFE esta em dia' |
| `siafe_status` | jfn | http | `/api/siafe/status` | PRONTO | 'o SIAFE esta coletando agora?', 'tem sweep rodando?', 'a coleta esta ativa?' |
| `sweeps_status` | jfn | http | `/api/sweeps/status` | PRONTO | 'como esta o sweep', 'o sweep do SEI/dados esta funcionando', 'a coleta continua esta rodando', 'quantos processos SEI ja foram lidos' |
| `consultar_diario` | jfn | http | `/api/diario` | PRONTO | 'saiu no diario oficial de X?', publicacao/extrato de contrato municipal |
| `consultar_empresa` | jfn | http | `/api/empresa` | PRONTO | 'dados da empresa X', socios de um CNPJ |
| `consultar_idoneidade` | lex | http | `/api/idoneidade` | PRONTO | 'a empresa X esta sancionada?', PEP |
| `consultar_leaks` | jfn | http | `/api/leaks` | PRONTO | 'aparece nos Panama/Pandora Papers?' |
| `consultar_links` | jfn | http | `/api/links` | PRONTO | 'onde mais pesquisar sobre X', aprofundar DD |
| `consultar_ownership` | jfn | http | `/api/ownership` | PRONTO | vinculo societario cross-jurisdicao |
| `doador_contrato_qsa` | lex | http | `/api/doador_contrato` | PRONTO | 'algum socio do fornecedor X financiou campanha?', conflito doador-fornecedor pela via QSA |
| `dossie` | jfn | http | `/api/dossie` | PRONTO | 'monte um dossie sobre X' |
| `grafo_ftm` | jfn | http | `/api/grafo/ftm` | PRONTO | 'exporte a rede de X p/ FtM/Aleph' |
| `grafo_poder` | jfn | http | `/api/grafo` | PRONTO | 'quem esta ligado a X', 'a N saltos do deputado Y com contrato' |
| `investigar_web` | jfn | http | `/api/compliance/investigar` | PRONTO | 'pesquise na web sobre X', 'noticias recentes de X', 'atividade publica/aparicoes na midia de X', 'o que saiu sobre X', monitoramento diario de uma pessoa |
| `busca_juridica` | lex | cli | `compliance_agent.collectors.lexml_fetcher --termo "<TERMO>"` | PRONTO | 'qual a lei sobre...', jurisprudencia |
| `buscar_direcionamento` | lex | http | `/api/sei/direcionamento` | PRONTO | 'ache editais restritivos na UG X' |
| `consultar_pncp` | lex | http | `/api/pncp` | PRONTO | analisar licitacao SEM SEI; editais por UF/orgao/fornecedor; preventivo (abertos) |
| `instrumento_mandato` | lex | http | `/api/mandato/minuta` | PRONTO | 'faca um requerimento sobre esse contrato' |
| `ler_processo_sei` | lex | cli | `tools.sei_reader "<NUMERO>"` | PRONTO | ler/analisar um processo SEI especifico. FORMATO do numero: 'SEI-UUUUUU/NNNNNN/AAAA' (ex.: SEI-070002/008633/2022) ou 'E-NN/NNN/AAAA' (ex.: E-12/345/2026) — unidade/sequencial/ano. Aceita com ou sem o prefixo SEI-. |
| `parecer_juridico` | lex | cli | `compliance_agent.lex "<empresa|cnpj>"` | PRONTO | 'tem direcionamento?', parecer |
| `radar_status` | jfn | http | `/api/radar/status` | PRONTO | 'o que voce monitora', 'teve alerta hoje' |
| `vigiar` | jfn | http | `/api/radar/vigiar` | PRONTO | '/vigiar <cnpj|ug|nome>' |
| `agenda_jobs` | jfn | http | `/api/agenda` | PRONTO | 'como estao os jobs/sweeps/agenda', 'o que roda quando', 'algum job falhou/parado' |
| `memoria` | jfn | http | `/api/memoria` | PRONTO | 'o que voce aprendeu', consolidar memoria |
| `skill_detalhe` | yoda | cli | `telegram /skill <id>` | PRONTO | 'como funciona a skill X', detalhe de uma capacidade |
| `skills` | yoda | cli | `telegram /skills [filtro]` | PRONTO | 'o que voce sabe fazer', 'quais skills', 'capacidades' |
| `skills_reload` | yoda | cli | `telegram /skills_reload` | PRONTO | apos editar o YAML na VM |
| `skills_sync` | yoda | cli | `telegram /skills_sync` | PRONTO | apos git push do repo |
| `skills_validate` | yoda | cli | `telegram /skills_validate` | PRONTO | antes de sync/reload, sanidade do contrato |
| `status_jfn` | jfn | http | `/status` | PRONTO | diagnostico |
| `trace` | jfn | http | `/api/trace/{correlation_id}` | ONDA 0 | debug |

> Regra do roteador: o Yoda só chama `id` com status **PRONTO**. Fora do registro = erro explícito ('não tenho ferramenta para isso'), nunca invenção.
