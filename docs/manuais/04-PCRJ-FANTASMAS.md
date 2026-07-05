# Manual — PCRJ / Detector de Funcionário Fantasma

## O que é
Módulo `compliance_agent/pcrj/` (banco `data/pcrj.db`) que cruza as folhas públicas da **Câmara** e
da **Prefeitura** do Rio e sinaliza **funcionário fantasma** = quem recebe salário sem trabalhar.

## O que é fantasma aqui (indícios OSINT legais)
A prova definitiva é o **ponto/frequência** (interno, só por requisição da CPI). O sistema entrega
INDÍCIOS que dizem *"peça o ponto deste"*:
- **s_acumulo** (mais forte) — mesma pessoa em 2 folhas ao mesmo tempo (Câmara∩Prefeitura), casada
  por nome único → não dá para cumprir jornada nos dois.
- **s_beneficio** — recebe Bolsa Família/BPC no Rio (1 pessoa única) → renda assistencial
  incompatível com estar na folha.
- **s_distante** — domicílio eleitoral em cidade distante do Rio.
- **s_candidato** — candidato em outra cidade enquanto vinculado.

## Honestidade (obrigatória)
- Sem CPF nas bases públicas → casamento por **nome** é indício, nunca prova. Homônimo (nome em ≥3
  cidades) **não** vira faixa "forte".
- "À disposição da CMRJ" / "Requisitado" = **cessão** (vínculo único), NÃO acúmulo — descontado.
- Nunca base vazada. Indício ≠ acusação.

## Como rodar e entregar
```bash
cd ~/JFN
PYTHONPATH=. .venv/bin/python -m compliance_agent.pcrj.fantasma_servidor      # (re)detecta → pcrj.db
PYTHONPATH=. .venv/bin/python -m compliance_agent.pcrj.dossie_prioritarios    # PDF Kroll dos fortes
```
Saída atual (2026-07-05, determinística): **565 avaliados → 69 forte / 386 verificar / 110 fraco**.
Dossiê: `reports/pcrj_alvos_prioritarios_<data>.pdf` (enviado ao Yoda).

## Dados
- `pcrj_camara_servidores` (2.252) — CSV por ano de ingresso (traz gabinete, SEM CPF)
- `pcrj_prefeitura_consulta` (3.994) — POST puro no contrachequeapi (sem CSV em massa)
- `pcrj_vinculo_cruzado` (644) — o cruzamento por nome
- `pcrj_fantasma_servidor` (565) — o resultado priorizado
- `tse_candidatura` — candidaturas (situacao = APTO/INAPTO; **não** tem resultado de eleição)

## De qual cidade a pessoa é (origem geográfica) — 2026-07-05
- **Filiação partidária (Wayback TSE 2018)**: `filiados_brasilio.py --wayback` → tabela `pcrj_filiado` (nome+município+partido+título). 764 pessoas casadas, 286 com domicílio fora do Rio. Cobre quem NUNCA foi candidato. Sinal só pontua se cidade distante (fora da região metropolitana).
Sinais de origem, do mais forte ao mais fraco (todos indício, nunca prova):
- **Domicílio eleitoral** = `NM_UE` (município onde foi candidato; por lei mora lá). Já usado em `s_distante`.
- **Título de eleitor** → UF de alistamento (dígitos 9-10). `origem.py::uf_do_titulo`. Disponível em
  anos que não redigem o título (2016/2020; 2024 redige).
- **Naturalidade** = `SG_UF_NASCIMENTO` (~99% preench.) e `NM_MUNICIPIO_NASCIMENTO` (só 2016).
- **Eleito em outra cidade** = `DS_SIT_TOT_TURNO` (resultado) → sinal forte de mandato fora do Rio.
- **CPF** (9º dígito = região fiscal; 7 = RJ/ES): `origem.py::regiao_do_cpf`, pronto p/ quando houver CPF.

O coletor TSE (`tse_candidatos.py`) mapeia colunas **por cabeçalho** (o layout do TSE muda por ano).

## Filiação partidária (cobertura de cidade para não-candidatos)
É pública, mas o TSE cortou o bulk nominal em 2021 (CDN só tem agregado, sem nomes). Nominal atual
(até 2026) só via BigQuery do Base dos Dados (exige billing Google — vetado). Caminho adotado:
**Brasil.IO** (nominal, grátis, sem Google). Ingestão via `filiados_brasilio.py` (em construção).

## Prefeitura mês a mês (2021+)
`comissionados_candidatos.coletar_mensal` varre a folha competência a competência 2021→hoje,
resumível (checkpoint `data/pcrj_comiss_mensal.done`), throttle workers=2/pausa=0.4. Captura todo
nomeado-candidato presente em qualquer mês (as datas de admissão/exoneração dão a lotação completa).

## Limite conhecido (honesto)
Empregados de **Organização Social (OS)** não são cruzáveis por nome: as prestações de contas
públicas são 100% agregadas (LGPD/CLT) — nenhuma publica nome de empregado.
