# Módulo PCRJ — Análise da Prefeitura do Rio de Janeiro

Cruzamento de vínculos entre a **Câmara Municipal do Rio**, a **Prefeitura do Rio** e as
**candidaturas eleitorais (TSE)**, para identificar indícios de duplo vínculo / acúmulo de
cargos e nomeados que foram candidatos — sempre como **indício, nunca acusação** (sem CPF nas
fontes públicas, o casamento é por nome).

## Como rodar

```bash
# tudo (câmara → sweep prefeitura ~1h → tse → relatório)
python -m compliance_agent.pcrj.pipeline

# sem o sweep lento da Prefeitura (usa o que já está no banco)
python -m compliance_agent.pcrj.pipeline --etapas camara,tse,relatorio

# só o relatório
python -m compliance_agent.pcrj.pipeline --etapas relatorio
```

Saídas: `data/pcrj.db` (banco dedicado) + `reports/pcrj_camara_cruzamento_<data>.{pdf,xlsx,html}`.

## Componentes

| Arquivo | Papel |
|---|---|
| `pipeline.py` | orquestrador (1 comando, etapas selecionáveis) |
| `camara_servidores.py` | coleta a relação completa de servidores da Câmara (dados abertos por ano de ingresso); deriva o gabinete da lotação |
| `camara_gabinetes.py` | mapa Gabinete Parlamentar Nº → vereador (planilha de núcleos) |
| `pcrj_remuneracao.py` | consulta a remuneração da Prefeitura por POST puro (JSF, sem browser) |
| `cruzamento.py` | match direcional Câmara→Prefeitura por nome, com níveis de confiança |
| `tse_candidatos.py` | cruza os nomeados com candidaturas do TSE (**somente estado do RJ, 92 municípios**) |
| `relatorio.py` | produto Kroll geral (pdf/xlsx/html) |
| `relatorio_gabinete.py` | PDF **pesquisável por gabinete/vereador**: `gerar_completo()` (todos + estrutura administrativa) ou `gerar(<nº>)` (um gabinete) |
| `pericia.py` | perícia de vínculos: direção temporal, datas entrada/saída, concomitância, domicílio outra cidade, comissionados-candidatos |
| `comissionados_candidatos.py` | cruzamento INVERSO: candidatos do TSE (RJ) que são comissionados (ESPECIAL/DAS/DAI) na Prefeitura 2021+ |
| `alternancia.py` | 5 gabinetes com alternância titular/suplente (posse 02/01/2025) + 🚩 flag de continuidade |
| `movimentacoes.py` | trajetórias Câmara⇄Prefeitura⇄candidatura nos dois sentidos, com datas (gabinete→pref, pref→gabinete, candidato antes/depois, multi-gabinete) |
| `dossie_completo.py` | **documento ÚNICO** (Partes A-E) com todos os cruzamentos |
| `os_panorama.py` | panorama AGREGADO das Organizações Sociais (RDP da CODESP — despesa/headcount por OS; **sem nomes**, não cruza nominal). Banco separado `data/pcrj_os.db` |
| `tools/pcrj_finalizar.py` | finalizador autônomo (sem LLM): espera o sweep all-RJ, gera o dossiê e envia pelo Yoda |
| `db.py` / `nomes.py` | banco `pcrj.db` + normalização de nomes |

## Fontes de dados (públicas)

- **Câmara** — `aplicsc.camara.rj.gov.br/.../Cons_Relacao_Servidores_API_csv/?ANOINGRESSO=<ano>`
  (traz Nome·Vínculo·Cargo·**Lotação/gabinete**; sem CPF) + planilha de núcleos dos gabinetes.
- **Prefeitura** — `contrachequeapi.rio.gov.br` (JSF; consulta por nome; sem CSV em massa; sem CPF).
- **TSE** — `cdn.tse.jus.br/.../consulta_cand/consulta_cand_<ano>.zip`, arquivo `*_RJ.csv`.

## Regras de honestidade (invariantes)

1. **Sem CPF em nenhuma base** → casamento por nome é **INDÍCIO**, jamais prova (homônimo possível).
2. **Cessão ≠ acúmulo**: "à disposição da CMRJ" / vínculo "Requisitado" = mesmo posto (vínculo
   único), descontado dos candidatos a acúmulo real.
3. **Homônimo provável**: nome que casa candidatos em ≥3 municípios distintos é sinalizado.
4. **INDISPONÍVEL ≠ 0**: erro de consulta nunca é tratado como "nada encontrado".
5. **Escopo TSE**: somente o estado do RJ e seus 92 municípios (nunca outros estados).

## Níveis de confiança do cruzamento

- `indicio_nome_unico` — 1 matrícula na Prefeitura com o nome (duplo vínculo provável).
- `homonimo_ambiguo` — 2+ matrículas com o mesmo nome (não isolável sem CPF).
- `nao_encontrado` / `indisponivel`.

## Base legal

Acumulação remunerada de cargos é vedada salvo exceções (CF art. 37, XVI/XVII). O sinal mais
forte é vínculo **efetivo/carreira** no Executivo (Guarda Municipal, professor) concomitante a
posto comissionado na Câmara — a apurar por CPF no RH, jamais afirmado aqui.
