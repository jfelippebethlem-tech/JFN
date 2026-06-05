# SEI — Mapa de Funções (o que dá pra fazer logado)

> Conta: **itkava (Karen Cardozo Valentim) — órgão ITERJ — unidade ITERJ/CHEGAB**
> Acesso conquistado em 04/06/2026 (login interno, sem captcha). Ritmo humano sempre.
> Tudo aqui é leitura/consulta para **auditoria e compliance** (uso legítimo do Mestre Jorge).

## Como o SEI funciona (visão simples)
O SEI é o sistema de **processos eletrônicos** do Governo do RJ. Cada **processo** (ex.: `SEI-070026/001185/2020`) é uma "pasta" que guarda vários **documentos** (despachos, ofícios, atas, deliberações, planos de ação, formulários...). Cada documento tem número, unidade, autor e data.

## Menu principal (funções e o "acao=" técnico)
| Função (menu) | acao= | Pra que serve |
|---|---|---|
| **Controle de Processos** | `procedimento_controlar` | Lista os processos da SUA unidade (recebidos/gerados) |
| **Pesquisa** ⭐ | `protocolo_pesquisar` | Busca processos/documentos por nº, texto, assunto, data, valor, assinante (SEM captcha quando logado) |
| **Painel de Controle** | `painel_controle_visualizar` | Visão geral/indicadores |
| **Acompanhamento Especial** | `acompanhamento_listar` | Processos que você marcou pra acompanhar |
| **Base de Conhecimento** | `base_conhecimento_pesquisar` | Manuais/orientações de procedimentos |
| **Blocos** (Assinatura/Internos/Reunião) | `bloco_*_listar` | Agrupar documentos p/ assinar ou revisar em lote |
| **Contatos** | `contato_listar` | Pessoas/órgãos (interessados, remetentes) |
| **Controle de Prazos** | `controle_prazo_listar` | Prazos dos processos |
| **Estatísticas** (Unidade/Desempenho) | `gerar_estatisticas_*` | Relatórios quantitativos |
| **Favoritos** | `protocolo_modelo_listar` | Modelos/atalhos |
| **Grupos** (Contatos/E-mail/Envio) | `grupo_*_listar` | Listas de envio |
| **Iniciar Processo** | `procedimento_escolher_tipo` | Abrir um processo novo (NÃO vamos usar — só leitura) |
| **Marcadores** | `marcador_listar` | Etiquetas coloridas nos processos |
| **Pontos de Controle** | `controle_unidade_gerar` | Etapas/checkpoints |
| **Processos Sobrestados** | `procedimento_sobrestado_listar` | Processos parados/suspensos |
| **Reabertura/Retorno Programado** | `reabertura_programada_listar` / `retorno_programado_listar` | Agendamentos |
| **Textos Padrão** | `texto_padrao_interno_listar` | Modelos de texto |
| **Abrir/Trabalhar um processo** | `procedimento_trabalhar` | Entra DENTRO de um processo e vê a árvore de documentos |

## A função-chave pra nós: **Pesquisa** (`protocolo_pesquisar`)
Campos disponíveis no formulário (todos opcionais, combináveis):
- `txtProtocoloPesquisa` → **número do processo/documento** (ex.: `070026/001185/2020`)
- `q` → **pesquisa livre** (texto dentro dos documentos)
- `selOrgaoPesquisa[]` → filtrar por órgão | `txtUnidade` → por unidade
- `txtAssunto`, `txtDescricaoPesquisa`, `txtObservacaoPesquisa`
- `txtAssinante` → quem assinou | `txtContato` → interessado/remetente/destinatário
- `selTipoProcedimentoPesquisa` → tipo do processo
- `txtNumeroDocumentoPesquisa` → nº de um documento específico
- `txtDataInicio`/`txtDataFim` + `selData` → período
- `txtDinValorInicio`/`txtDinValorFim` → **faixa de valor R$** (ótimo pra auditoria!)
- Abas de resultado: **Processos | Documentos | Gerados | Externos | Com Tramitação na Unidade**

### Exemplo real testado (04/06/2026)
Busca por `070026/001185/2020` → **10 documentos** (Exibindo 1-10 de 10):
- Tipo: *Administrativo: Elaboração de Ofício de Mero Expediente*
- Tema: **FECAM / AMBIENTE JOVEM / Apoio Técnico** — valores citados: **R$ 35.113.262,38** e **R$ 3.753.283,54**
- Documentos: Ata, Despachos de Encaminhamento, Publicação, Deliberação, Plano de Ação, Formulário
- Unidades envolvidas: SEAS/COOFECAM, SEAS/SUPFIP, SEAS/SUBEXE, SEAS/SUPESUS
- Período: abr–jul/2023

## O que JÁ conseguimos fazer (validado)
1. ✅ Logar (sessão reaproveitável, salva em `data/sei_cache/sessao_cookies.json`)
2. ✅ Pesquisar processo por número (sem captcha)
3. ✅ Ler a lista de documentos + metadados (unidade, autor, data, valores)
4. ✅ Mapear o menu/funções do sistema

## O que dá pra fazer a seguir (próximos passos)
- **Abrir um processo** (`procedimento_trabalhar`) e ler a árvore completa de documentos.
- **Pesquisa por VALOR** (faixa R$) e por **tipo** → achar contratos/empenhos suspeitos.
- **Cruzar com SIAFE 2**: pegar nº de empenho/contrato no SIAFE e localizar o processo SEI correspondente (e vice-versa) → relatório de red flags.
- **Baixar PDFs** dos documentos para análise (com cuidado de ritmo).

## Regras (sempre)
- Ritmo humano: 1 busca por vez, pausa 4–9s, reaproveitar sessão, parar se aparecer bloqueio.
- Só LEITURA/consulta. Nunca iniciar/alterar/assinar processos sem o Mestre Jorge mandar.
- Credenciais só no `.env`. Resultados em cache, nunca no git/chat.
