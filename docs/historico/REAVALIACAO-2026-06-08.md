# REAVALIAÇÃO JFN 2.0 — spec × implementação × instrumentalização OSINT (2026-06-08)

> Pedido do dono: "reveja o documento todo e tudo o que fizemos até aqui para entender e instrumentalizar
> essas ferramentas novas e onde se aplicam; reavalie tudo o que foi feito antes."
> Fontes desta reavaliação: os 3 documentos-mestre (`docs/refs/JFN-DOCUMENTO-MESTRE-CONSOLIDADO-v2.pdf`,
> `JFN-SPEC-SKILLTREE-YODA.pdf`, `JFN-ADICIONAL-DUE-DILIGENCE-OSINT.pdf`) lidos na íntegra + validador de
> capabilities + **89 testes jfn2** + checagem de imports de todos os módulos de onda + rotas reais do `server.py`.

## 1. Veredito geral
Implementação **fiel ao spec no nível de contrato**: `capabilities.yaml` com **38/39 PRONTO** (validador OK; rotas
existem no `server.py`), **89 testes** verdes, **todos os módulos das 13 ondas importam sem erro**. O que falta é
**(a)** itens conscientemente diferidos (com motivo), **(b)** enriquecedores **key-gated** (esperando chave grátis),
e **(c)** 3 refinamentos de honestidade/completude listados em §4.

## 2. Onda a onda (critério de aceite do spec → estado verificado)

| Onda | Aceite (spec) | Estado | Evidência / ressalva |
|---|---|---|---|
| 0 Fundação | restart não derruba coleta; X-Correlation-Id; SEI via proxy | ✅/⚠️ | `obs_trace` + `/api/trace`; SEI lido via **itkava** (12k chars, validado), não via proxy residencial — caminho alternativo que funciona |
| 1 Orquestração | 4 cenários de roteamento; `grep web_search`=vazio | ✅ | `capabilities.yaml` fonte única; skilltree viva; política de modelo única |
| 2 PNCP+Conflito | `/api/conflito` rede c/ score; `/api/pncp` analisa edital | ✅ | `lex_conflito` validado live (MGS); **agora c/ UG pagadora + SEI** (cadeia fechada) |
| 3 Motor de risco | Benford; cartel; sobrepreço c/ referencial | ✅ | 15 testes; `analysis/benford.py`, `cartel.py`, `sobrepreco.py` |
| 4 Grafo+Dossiê | "≤2 saltos do deputado X com contrato"; dossiê PDF 360 | ✅ | `/api/grafo`, `/api/grafo/ftm`, `/api/dossie` |
| 5 SEI escala | processos suspeitos ranqueados c/ trechos | ✅/⚠️ | `/api/sei/direcionamento`; embeddings semânticos = FTS5 (sentence-transformers não instalado, lazy) |
| 6 Radar 24/7 | alerta no Telegram ao surgir alvo | ✅ | `radar.py` + units systemd; `/api/radar/status` |
| 7 Relatório | PDF profissional, ≥3 SVG, rating, score | ✅ | motor HTML→PDF (Playwright); **agora c/ tabela mês a mês (5-B) + zebra** |
| 8 Massare notícia/macro | Focus + agenda + manchetes c/ tom | ✅/⚠️ | `/api/massare/{focus,fundamentos,calendario,noticias}`; **crypto_ws daemon DIFERIDO** |
| 9 Massare teses | teses c/ acerto OOS; DSR; regime | ✅/⚠️ | `/api/massare/teses,carteira`; backtest `vectorbt` **não instalado** (validação López de Prado parcial) |
| 10 Lex+Mandato | parecer cita precedente; gera minuta | ✅ | `mandato.py` (5 testes; docx requerimento/representação/notícia/post) |
| 11 Higiene | split de módulos; lock SIAFE; `/api/memoria` | ✅/⚠️ | `/api/memoria`, locks SIAFE; **split dos módulos grandes ainda pendente** (dívida) |
| 12 OSINT/DD | OpenSanctions+OpenCorporates+FtM, c/ proveniência | ⚠️ | `opensanctions.py` ✅ (key-gated), **`aleph.py` ✅ novo (key-gated)**, FtM `/api/grafo/ftm` ✅, **`opencorporates.py` FALTA** |
| 13 Skilltree | ver/atualizar skilltree pelo Telegram | ✅ | `/skills`, `/skill`, reload/sync/validate admin |

## 3. Instrumentalização das ferramentas novas (onde cada uma se aplica)
Mapa contra a estrutura de relatório de DD (doc OSINT §A.3). **Princípio do dono: API primeiro; free/free-tier
só; self-host apenas leve e sem alternativa de API; Aleph = via API (a versão a evitar é a self-host pesada).**

| Ferramenta | Acesso | Onde se aplica (seção da DD) | Estado |
|---|---|---|---|
| **OpenSanctions** | API, free não-comercial | §7 Listas restritivas + §8 Conflito (PEP de sócios) + score | ✅ ligado (relatório §4 + dossiê); falta **OPENSANCTIONS_API_KEY** |
| **OCCRP Aleph** | API, free (conta OCCRP) | §4 Beneficiários finais + §8 Vínculos/follow-the-money + vazamentos (registra link no dossiê) | ✅ ligado (relatório §4 + dossiê); falta **ALEPH_API_KEY** |
| **OpenCorporates** | API, free permitted-user | §3 Perfil + §4 rede societária **cross-jurisdição** (complementa BrasilAPI) | ❌ **a implementar** (`enrich/opencorporates.py`); falta **OPENCORPORATES_API_KEY** |
| **ExifTool** | local (sem API possível) | §9 Mídia adversa / forense de documentos e imagens do SEI/PNCP (metadados: data, GPS, autor) | ✅ instalado; falta **wrapper** `enrich/exif.py` p/ rodar nos anexos |

**Conclusão da instrumentalização:** 2 de 4 já plugadas no relatório e no dossiê (OpenSanctions, Aleph), prontas
para "acender" assim que houver chave. Faltam **OpenCorporates (coletor)** e **ExifTool (wrapper de forense
documental)** — ambos pequenos, ficam para a próxima onda.

## 4. Gaps honestos (backlog priorizado)
1. **Consolidar matriz+filiais por raiz** no `/relatorio` (uma PJ só — STJ REsp 1.286.122; aprovado pelo dono).
2. **Parecer Lex usar o SEI real + honestidade** — não afirmar "leu na íntegra" se voltar vazio.
3. **`/lista` fast-path** no gateway (hoje lento pelo loop do LLM; `/api/lista` = 29ms).
4. **OpenCorporates** (`enrich/opencorporates.py`) + **ExifTool wrapper** (`enrich/exif.py`).
5. **Paridade `render_md` ↔ HTML** (a seção 5-B mês a mês só existe no motor HTML/PDF).
6. **Dívida da Onda 11:** split dos módulos grandes (`hermes_goal`, `inteligencia`, `siafe_ob_orcamentaria`…).
7. **Diferidos com motivo:** `crypto_ws` daemon (Onda 8); `vectorbt`/validação López de Prado plena (Onda 9);
   `sentence-transformers` p/ busca semântica do SEI (Onda 5 usa FTS5 hoje). CNPJ alfanumérico (Receita 2026)
   exigirá ajuste no `so_digitos()`.

## 5. Credenciais/registros grátis a obter (todas free / free-tier)
| Variável (.env) | Onde obter (grátis) | Destrava |
|---|---|---|
| `OPENSANCTIONS_API_KEY` | opensanctions.org (uso não comercial) | sanções + PEP no relatório/dossiê |
| `ALEPH_API_KEY` | aleph.occrp.org → Settings → API key | follow-the-money cross-jurisdição + vazamentos |
| `OPENCORPORATES_API_KEY` | opencorporates.com (conta "Permitted User") | rede societária internacional (após implementar coletor) |
| `FINNHUB_API_KEY` | finnhub.io (free tier) | agenda macro/notícia de mercado (Massare Onda 8 — complementa GDELT) |
| `brapi` token | brapi.dev (free tier) | fundamentos B3 mais estáveis (hoje funciona sem, com limite) |

> Tudo o que está **key-gated reporta INDISPONÍVEL honestamente** até a chave existir — nada é fabricado.
