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

## Limite conhecido (honesto)
Empregados de **Organização Social (OS)** não são cruzáveis por nome: as prestações de contas
públicas são 100% agregadas (LGPD/CLT) — nenhuma publica nome de empregado.
