# ADR-011 — Dados no git: o que está versionado em `data/` e o que sai

| Campo | Valor |
|---|---|
| **Estado** | Aceito como inventário (O1.4, 24/11/2026). **A remoção é a O9.4 e só acontece com ok do dono** |
| **Plano** | `~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md` §2 (Segurança), §3.11, decisão 5 do dono |
| **Linha de base** | `seguranca.arquivos_versionados_data` = **169** (MEDIDO em `git ls-tree -r HEAD data/`) |
| **Relacionados** | ADR-001 (autoridade de dados), ADR-008 (segurança de produção) |

## 1. Contexto

O repositório é **público** e tem 169 arquivos em `data/`. O `.gitignore` cobre `data/*.db`, os logs e os
caches, mas não a pasta inteira: filas, estados, scripts operacionais, íntegras de processo e laudos foram
versionados ao longo dos meses.

O histórico do `main` tem CPF completo (o §2 cita 869). Essa medida **não foi refeita** pela linha de base da
O1.3: está INDISPONÍVEL, porque a varredura do `git log -p` inteiro é pesada para a VM-1 e foi movida para a
VM-2.

Este ADR lista os arquivos **só pelo nome**, sem abrir nem citar o conteúdo, para não repetir o vazamento no
próprio ADR.

## 2. Decisão

1. **Classes:**
   - **público-ok**: catálogo público, nota de método, derivado regenerável, publicação oficial ou exemplo;
   - **operacional**: fila, estado, log, PID/lock, bancada, script com caminhos e horários. Não é segredo, mas
     expõe topologia e muda a toda execução;
   - **sensível**: íntegra ou laudo de processo, gabarito tirado de processo, alvo, cruzamento de pessoas,
     processo restrito, memória sobre entidade.
2. **A classificação é pelo nome e pela pasta**, que é conservadora: na dúvida, vale a classe mais restrita.
   A O9.4 confirma cada `sensível` com o scanner de PII antes de agir.
3. **Ações previstas (O9.4; nada é removido agora):**
   - público-ok: manter versionado (O9.4 decide se vai para `docs/` ou `tests/fixtures/`);
   - operacional: deixar de versionar: `git rm --cached` + `.gitignore` (O9.4); o estado migra conforme a ADR-001;
   - sensível: deixar de versionar e avaliar a purga do histórico (O9.4, **só com ok do dono**).
4. **Daqui em diante:** arquivo novo em `data/` não entra no git, salvo `.gitkeep`. A catraca e o scanner de CPF
   do pre-commit barram (ADR-008).

## 3. Resumo

| Classe | Arquivos |
|---|---:|
| público-ok | 89 |
| operacional | 50 |
| sensível | 30 |
| **Total** | **169** |

## 4. Inventário (169 arquivos, por nome)

| # | Arquivo | Classe | Motivo (pelo nome) |
|---:|---|---|---|
| 1 | `data/.bombeiros_alerta_cursor.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 2 | `data/.desktop_hb_state` | operacional | estado, fila, log, bancada ou artefato de execução |
| 3 | `data/.gitkeep` | público-ok | convenção de pasta vazia |
| 4 | `data/.llm_month_cap.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 5 | `data/.lock_fachada_sv` | operacional | estado, fila, log, bancada ou artefato de execução |
| 6 | `data/.pcrj_sweep_pid` | operacional | estado, fila, log, bancada ou artefato de execução |
| 7 | `data/ajovem_cruzamento.json` | sensível | alvos, cruzamento de pessoas, processo restrito ou gabarito tirado de processo |
| 8 | `data/bancada_ocr_20261123/bench_sota.py` | operacional | estado, fila, log, bancada ou artefato de execução |
| 9 | `data/bancada_ocr_20261123/estrutura_deepdoc.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 10 | `data/bancada_ocr_20261123/medir.py` | operacional | estado, fila, log, bancada ou artefato de execução |
| 11 | `data/bancada_ocr_20261123/resultado_bancada_ovis_parcial.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 12 | `data/bancada_ocr_20261123/resultado_bancada_sota.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 13 | `data/bancada_ocr_20261123/tempos_deepdoc.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 14 | `data/bancada_ocr_20261123/tempos_ovis.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 15 | `data/bancada_ocr_20261123/tempos_paddlevl.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 16 | `data/bancada_ocr_20261123/tempos_ppocrv6.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 17 | `data/benchmark_ias_gold.json` | sensível | alvos, cruzamento de pessoas, processo restrito ou gabarito tirado de processo |
| 18 | `data/benchmark_relatorio.md` | operacional | estado, fila, log, bancada ou artefato de execução |
| 19 | `data/bombeiros_integra_cobertura.csv` | operacional | estado, fila, log, bancada ou artefato de execução |
| 20 | `data/bombeiros_sei_fila.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 21 | `data/bombeiros_supervisor.pid` | operacional | estado, fila, log, bancada ou artefato de execução |
| 22 | `data/cerebro_bateria/antes-fase2-2026-11-19.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 23 | `data/cerebro_bateria/antes-fase4-2026-11-19.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 24 | `data/cerebro_bateria/base-2026-11-19.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 25 | `data/cerebro_bateria/depois-fase2-2026-11-19.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 26 | `data/cerebro_bateria/depois-fase4-2026-11-19.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 27 | `data/cerebro_bateria/fase1-2026-11-19.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 28 | `data/coleta_esporte_2018.sh` | operacional | topologia operacional (comandos, caminhos, horários) |
| 29 | `data/coleta_suderj_2018.sh` | operacional | topologia operacional (comandos, caminhos, horários) |
| 30 | `data/consulta_media_finalizar.sh` | operacional | topologia operacional (comandos, caminhos, horários) |
| 31 | `data/corpus_762_pericia.txt` | sensível | texto ou laudo de processo |
| 32 | `data/crontab_backup_pre_cap21k_2026-08-02.txt` | operacional | topologia operacional (comandos, caminhos, horários) |
| 33 | `data/crontab_backup_pre_sentinela_2026-08-02.txt` | operacional | topologia operacional (comandos, caminhos, horários) |
| 34 | `data/diagnostics/.gitkeep` | público-ok | convenção de pasta vazia |
| 35 | `data/digest_estado.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 36 | `data/doerj_learning.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 37 | `data/empresas_target.json` | sensível | alvos, cruzamento de pessoas, processo restrito ou gabarito tirado de processo |
| 38 | `data/experimento_ia_fraca_330005_000030_2026.md` | sensível | texto ou laudo de processo |
| 39 | `data/experimento_ia_fraca_330020_000762_2021.md` | sensível | texto ou laudo de processo |
| 40 | `data/fila_fiscal_360.md` | sensível | alvos, cruzamento de pessoas, processo restrito ou gabarito tirado de processo |
| 41 | `data/finalizar_mestre.sh` | operacional | topologia operacional (comandos, caminhos, horários) |
| 42 | `data/flags_graves.json` | sensível | alvos, cruzamento de pessoas, processo restrito ou gabarito tirado de processo |
| 43 | `data/gabaritos_sei.json` | sensível | alvos, cruzamento de pessoas, processo restrito ou gabarito tirado de processo |
| 44 | `data/hermeneutica_baseline.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 45 | `data/hermeneutica_ultima.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 46 | `data/hermes_memoria_md/contexto_admin__00_limite-dispensa-obras.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 47 | `data/hermes_memoria_md/contexto_admin__01_limite-dispensa-compras.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 48 | `data/hermes_memoria_md/contexto_admin__02_limite-convite-antigo.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 49 | `data/hermes_memoria_md/contexto_admin__03_vedacao-sancionada.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 50 | `data/hermes_memoria_md/contexto_admin__04_processo-sei-obrigatorio.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 51 | `data/hermes_memoria_md/contexto_admin__05_ug-principais-rj.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 52 | `data/hermes_memoria_md/contexto_admin__06_rajada-fim-mes.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 53 | `data/hermes_memoria_md/contexto_admin__07_valor-redondo.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 54 | `data/hermes_memoria_md/contexto_admin__08_nepotismo.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 55 | `data/hermes_memoria_md/contexto_admin__09_improbidade-dolo-especifico.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 56 | `data/hermes_memoria_md/contexto_admin__10_improbidade-dano-efetivo.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 57 | `data/hermes_memoria_md/contexto_admin__11_anatomia-achado.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 58 | `data/hermes_memoria_md/contexto_admin__12_nota-tecnica-cge.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 59 | `data/hermes_memoria_md/contexto_admin__13_tcerj-dados-abertos.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 60 | `data/hermes_memoria_md/contexto_admin__14_crimes-contratacao.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 61 | `data/hermes_memoria_md/empirico__15_base-volume.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 62 | `data/hermes_memoria_md/empirico__16_cobertura-ob-sei.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 63 | `data/hermes_memoria_md/empirico__17_anomalia-threshold.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 64 | `data/hermes_memoria_md/empirico__18_concentracao-ug-top1.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 65 | `data/hermes_memoria_md/empirico__19_fornecedores-ubiquos.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 66 | `data/hermes_memoria_md/entidade__20_FOO-LTDA.md` | sensível | memória sobre entidade ou missão em curso |
| 67 | `data/hermes_memoria_md/metodo__21_primario-sobre-derivado.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 68 | `data/hermes_memoria_md/metodo__22_bruto-vs-liquido.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 69 | `data/hermes_memoria_md/metodo__23_reajuste-componente-nao-flat.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 70 | `data/hermes_memoria_md/metodo__24_empenho-liquidacao-ob.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 71 | `data/hermes_memoria_md/metodo__25_duplicidade-por-competencia.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 72 | `data/hermes_memoria_md/metodo__26_sei-busca-por-interessado.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 73 | `data/hermes_memoria_md/metodo__27_verificar-contagem-antes-de-relatar.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 74 | `data/hermes_memoria_md/metodo__28_pericia-pagamento-execu-o-financeira-ob.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 75 | `data/hermes_memoria_md/metodo__29_pericia-parecer-jur-dico-habilita-o-regularidade.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 76 | `data/hermes_memoria_md/metodo__30_pericia-pesquisa-de-pre-os-planilha-de-custos.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 77 | `data/hermes_memoria_md/metodo__31_pericia-modalidade-fundamento-legal.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 78 | `data/hermes_memoria_md/metodo__32_pericia-termo-de-refer-ncia-etp-dfd.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 79 | `data/hermes_memoria_md/metodo__33_pericia-presuncao-regularidade.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 80 | `data/hermes_memoria_md/metodo__34_pericia-confirma-ob.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 81 | `data/hermes_memoria_md/metodo__35_pericia-entrega-execu-o-do-objeto-fiscaliza-o.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 82 | `data/hermes_memoria_md/metodo__36_pericia-pagamento-ob.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 83 | `data/hermes_memoria_md/metodo__37_pericia-confirmar-ob.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 84 | `data/hermes_memoria_md/metodo__38_pericia-confirmar-pagamento-ob.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 85 | `data/hermes_memoria_md/metodo__39_pericia-fundamento-legal.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 86 | `data/hermes_memoria_md/metodo__40_pericia-verificar-ob-pagamento.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 87 | `data/hermes_memoria_md/metodo__41_pericia-conformidade-legal.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 88 | `data/hermes_memoria_md/metodo__42_pericia-parecer-juridico.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 89 | `data/hermes_memoria_md/metodo__43_pericia-achado-presente-sobre-ausente.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 90 | `data/hermes_memoria_md/metodo__44_pericia-duplicidade-atas-nes-mesmo-objeto.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 91 | `data/hermes_memoria_md/metodo__45_pericia-importacao-direta-estrangeira-sem-exclusiv.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 92 | `data/hermes_memoria_md/metodo__46_pericia-email-pessoal-em-ato-oficial.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 93 | `data/hermes_memoria_md/metodo__47_pericia-aditivo-reajuste-vig-ncia.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 94 | `data/hermes_memoria_md/metodo__48_pericia-regularidade-juridica.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 95 | `data/hermes_memoria_md/metodo__49_relacionados-verificar-favorecido.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 96 | `data/hermes_memoria_md/metodo__50_laudo-precisa-conclusao-e-memoria.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 97 | `data/hermes_memoria_md/metodo__51_pericia-verificar-ob.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 98 | `data/hermes_memoria_md/metodo__52_pericia-confirma-pagamento-ob.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 99 | `data/hermes_memoria_md/metodo__53_pericia-valida-fundamento-legal.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 100 | `data/hermes_memoria_md/metodo__54_pericia-legalidade-regularidade.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 101 | `data/hermes_memoria_md/metodo__55_pericia-planejamento-custos.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 102 | `data/hermes_memoria_md/metodo__56_pericia-execucao-fiscalizacao.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 103 | `data/hermes_memoria_md/metodo__57_pericia-conformidade-documental.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 104 | `data/hermes_memoria_md/metodo__58_pericia-confirmar-ob-pagamento.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 105 | `data/hermes_memoria_md/metodo__59_pericia-avaliar-pesquisa-precos.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 106 | `data/hermes_memoria_md/metodo__60_pericia-comprovacao-pagamento.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 107 | `data/hermes_memoria_md/metodo__61_pericia-planejamento-execucao.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 108 | `data/hermes_memoria_md/metodo__62_pericia-analise-precos.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 109 | `data/hermes_memoria_md/metodo__63_pericia-modalidade-legal.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 110 | `data/hermes_memoria_md/metodo__64_pericia-arvore-rasa-nao-periciavel.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 111 | `data/hermes_memoria_md/metodo__65_pericia-pagamento-efetivo.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 112 | `data/hermes_memoria_md/metodo__66_pericia-confirma-ob-pagamento.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 113 | `data/hermes_memoria_md/metodo__67_pericia-analisar-precos-custos.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 114 | `data/hermes_memoria_md/metodo__68_pericia-avaliar-regularidade-juridica.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 115 | `data/hermes_memoria_md/metodo__69_pericia-regularidade-parecer.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 116 | `data/hermes_memoria_md/metodo__70_pericia-fundamento-modalidade.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 117 | `data/hermes_memoria_md/missao__71_atual.md` | sensível | memória sobre entidade ou missão em curso |
| 118 | `data/hermes_memoria_md/padrao_fraude__72_frac-x.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 119 | `data/hermes_memoria_md/pesquisa__73_pesquisa-superfaturamento-14133.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 120 | `data/hermes_memoria_md/pesquisa__74_pesquisa-cartel-dempster.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 121 | `data/hermes_memoria_md/pesquisa__75_pesquisa-cartel-metrica-codevasf.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 122 | `data/hermes_memoria_md/pesquisa__76_pesquisa-fracionamento-tcu.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 123 | `data/hermes_memoria_md/pesquisa__77_pesquisa-benford.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 124 | `data/hermes_memoria_md/pesquisa__78_pesquisa-robo-alice.md` | público-ok | nota de método/contexto normativo (conhecimento, sem dado pessoal pelo nome) |
| 125 | `data/ioerj/edicoes/contratos_extraidos.json` | público-ok | Diário Oficial (fonte pública) |
| 126 | `data/ioerj/edicoes/parte_executivo_2026-06-02.txt` | público-ok | Diário Oficial (fonte pública) |
| 127 | `data/ioerj/manual_2026-06-02/edicao.html` | público-ok | Diário Oficial (fonte pública) |
| 128 | `data/ioerj/manual_2026-06-02/edicao.txt` | público-ok | Diário Oficial (fonte pública) |
| 129 | `data/ioerj/status.txt` | operacional | estado de coleta |
| 130 | `data/jfn_tools.json` | público-ok | catálogo/derivado público ou exemplo |
| 131 | `data/lai_requerente.exemplo.json` | público-ok | catálogo/derivado público ou exemplo |
| 132 | `data/leitura_claude/030001_000071_2025.json` | sensível | leitura/laudo de processo |
| 133 | `data/leitura_claude/030001_015319_2025.json` | sensível | leitura/laudo de processo |
| 134 | `data/leitura_claude/030001_025906_2025.json` | sensível | leitura/laudo de processo |
| 135 | `data/leitura_claude/030001_069533_2024.json` | sensível | leitura/laudo de processo |
| 136 | `data/leitura_claude/030001_103373_2024.json` | sensível | leitura/laudo de processo |
| 137 | `data/leitura_claude/070002_005897_2024.json` | sensível | leitura/laudo de processo |
| 138 | `data/leitura_claude/070002_006258_2024.json` | sensível | leitura/laudo de processo |
| 139 | `data/leitura_claude/070002_006459_2024.json` | sensível | leitura/laudo de processo |
| 140 | `data/leitura_claude/070002_015404_2022.json` | sensível | leitura/laudo de processo |
| 141 | `data/memoria_hermes_dump.json` | sensível | alvos, cruzamento de pessoas, processo restrito ou gabarito tirado de processo |
| 142 | `data/nucleo_ciclo_run1.err` | operacional | estado, fila, log, bancada ou artefato de execução |
| 143 | `data/pcrj_comiss_mensal.done` | operacional | estado, fila, log, bancada ou artefato de execução |
| 144 | `data/pericia_762_comparativo.md` | sensível | texto ou laudo de processo |
| 145 | `data/pericia_762_hermes.txt` | sensível | texto ou laudo de processo |
| 146 | `data/pipelines_slo_estado.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 147 | `data/proc_integra/Das-Dragmaq-desassoreamento-R41mi.pdf` | sensível | íntegra de processo (PDF) |
| 148 | `data/proc_integra/Hydra-urbanizacao-R52mi.pdf` | sensível | íntegra de processo (PDF) |
| 149 | `data/proc_integra/Lytoranea-macrodrenagem-Maxambomba-R96mi.pdf` | sensível | íntegra de processo (PDF) |
| 150 | `data/proc_integra/Lytoranea-macrodrenagem-R70mi.pdf` | sensível | íntegra de processo (PDF) |
| 151 | `data/proc_integra/Metropolitana-macrodrenagem.pdf` | sensível | íntegra de processo (PDF) |
| 152 | `data/proc_integra/Trial-SEAS-R6mi.pdf` | sensível | íntegra de processo (PDF) |
| 153 | `data/pull_integra_completa.sh` | operacional | topologia operacional (comandos, caminhos, horários) |
| 154 | `data/pull_processos_seas_inea.sh` | operacional | topologia operacional (comandos, caminhos, horários) |
| 155 | `data/recaptura_cap21k.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 156 | `data/recaptura_cap21k_fatias.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 157 | `data/recaptura_integral_progresso.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 158 | `data/resumo_sessao.txt` | operacional | estado, fila, log, bancada ou artefato de execução |
| 159 | `data/scorecard_hist.jsonl` | operacional | estado, fila, log, bancada ou artefato de execução |
| 160 | `data/sei_fila_dinheiro.json` | operacional | estado, fila, log, bancada ou artefato de execução |
| 161 | `data/sei_orgaos.json` | público-ok | catálogo/derivado público ou exemplo |
| 162 | `data/sei_prestacao_contas.sh` | operacional | topologia operacional (comandos, caminhos, horários) |
| 163 | `data/sei_restritos.json` | sensível | alvos, cruzamento de pessoas, processo restrito ou gabarito tirado de processo |
| 164 | `data/sweep_seas_inea_pampolha.sh` | operacional | topologia operacional (comandos, caminhos, horários) |
| 165 | `data/tac_ranking_ugs.json` | público-ok | catálogo/derivado público ou exemplo |
| 166 | `data/ug_canonico.json` | público-ok | catálogo/derivado público ou exemplo |
| 167 | `data/ug_index_siafe.json` | público-ok | catálogo/derivado público ou exemplo |
| 168 | `data/ugs_foco.txt` | operacional | estado, fila, log, bancada ou artefato de execução |
| 169 | `data/yoda_capabilities_prompt.txt` | operacional | estado, fila, log, bancada ou artefato de execução |

## 5. Consequências

- O repo público deixa de expor estado operacional e conteúdo de processo novo.
- O histórico continua com o que já foi publicado até a purga. A purga reescreve o histórico e exige
  `force push`, por isso **só com ok explícito do dono** (O9.4).
- Os estados que hoje vivem nesses arquivos migram para o PG antes de sair do git (ADR-001 §4). Nenhum leitor
  pode ficar sem fonte.

## 6. Não adotar

- **Apagar agora com `git rm`:** contraria a decisão 5 do dono (limpeza só na O9.4) e a parada de obras.
- **Purgar o histórico sem o ok do dono:** reescrita irreversível de um repo público.
- **Tornar o repo privado como solução:** é decisão do dono e não remove o que já foi clonado; pode somar-se,
  mas não substitui.

## 7. Gatilho de reavaliação

- Um arquivo novo aparece em `git ls-tree HEAD data/` além do `.gitkeep`.
- O scanner de PII acha CPF completo num arquivo classificado como público-ok ou operacional.
- O dono decide sobre a visibilidade do repo.
