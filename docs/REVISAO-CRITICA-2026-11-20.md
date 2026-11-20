# JFN — Revisão crítica de arquitetura, execução e ferramentas

| | |
|---|---|
| **Documento** | Revisão crítica final do trabalho de 19–20/11/2026 e do sistema como está |
| **Data** | 20/11/2026 |
| **Autor** | Fable (revisão independente, a pedido do dono) |
| **Base** | `38972e5a` (passada final do untangle) · branch `worktree-agent-ad4328b67ba91b117` |
| **Escopo** | Estado do RJ e Prefeitura do Rio · sem coleta em SEI/SIAFE, sem LLM pago, `data/` só em leitura |
| **Entrega em código** | 3 commits locais, sem push: `10af1553`, `0e519fca`, `21f2cecc` |

> **Critério de tudo que segue.** O JFN existe para achar indício de irregularidade em gasto público **com prova
> primária, sem margem de erro, rápido e barato**. Cada item abaixo é julgado por isso: aumenta a prova, reduz o
> erro, encurta o tempo ou corta custo — ou é ornamento.

---

## 1. Sumário executivo

**O sistema detecta muito melhor do que age.** Tem 21 sensores, 70 regras de qualidade, 64 famílias de falha
catalogadas e uma fila de automelhoria — e, nessa fila, 25 itens abertos, dos quais só 3 tinham remédio automático;
um deles está aberto há 169 rodadas. O que a casa sabe sobre os próprios defeitos cresce mais depressa do que a
capacidade de fechá-los. As quatro melhorias desta revisão atacam exatamente isso: cada uma transforma um
diagnóstico já escrito em memória ou log num mecanismo que **barra, descarta ou remedia sozinho**.

| # | Melhoria | Antes | Depois | Commit |
|---|---|---|---|---|
| 1 | Ficha do acervo: conferência literal do **texto corrido** | 126 fatos sem fonte (valor, CNPJ, data, nº SIAFE) gravados em 46 de 300 fichas (15,3%); 394 datas verdadeiras descartadas por grafia | 0 gravados pela mesma régua; 90 frases (0,78%) e 21 itens descartados e contados; 120 contas do modelo refeitas pelo código; +394 datas, +68 documentos, +34 valores recuperados | `10af1553` |
| 2 | it-campo ocioso vira laço (alimentar × escalar × silêncio) | "GPU em 0% (OCR parado?)", sem remédio, 4 rodadas REINCIDIU | mesmo sinal sai com o comando que regenera a fila; fila vazia deixa de ser item; fila cheia com GPU parada escala | `0e519fca` |
| 3 | Integração de agentes: remoção perdida e worktree esquecido | 14 remoções perdidas achadas à mão dias depois; 45 worktrees (14 GB) → disco a 100% → `claude -p` fora do ar | `tools/integracao_conferir` acha as 14 no histórico real (0 na ponta); sensor com remédio seguro para worktree | `0e519fca` |
| 4 | Catraca: módulo sem chamador de produção | 43 módulos de `compliance_agent/` sem chamador, invisíveis | baseline nomeada que só encolhe; módulo novo órfão **não passa** no portão | `21f2cecc` |

**Escala de severidade usada neste documento** (1 a 5): 5 = pode levar afirmação errada a um entregável;
4 = esconde irregularidade real ou gasta cota do juiz em ruído; 3 = desperdício de máquina/cota; 2 = dívida que
encarece a manutenção; 1 = cosmético.

---

## 2. Diagnóstico — onde arquitetura, execução e ferramentas não servem aos objetivos

### 2.1 Os cinco achados que mais pesam

| # | Achado | Sev. | Evidência medida |
|---|---|:-:|---|
| D1 | **Detectar sem agir.** A automelhoria é um painel de pendências, não um laço. | 4 | `data/automelhoria_fila.json` em 20/11 20h: 25 abertos (7 REINCIDIU), 3 com remédio automático; `dados:siafe_lacunas_tfe` aberto há 169 rodadas; 5 detectores com 37–68% de falso positivo listados como "ação humana". O dono silenciou os avisos de sistema em 17/11 — o canal que restava. |
| D2 | **Modelo barato escrevendo texto que ninguém conferia.** A conferência literal cobria as listas e parava no texto corrido. | 5 | Em 300 fichas já pagas (sorteio fixo), a régua v1 gravava **126 fatos sem fonte** — valor em R$, CNPJ, data ou nº de documento do SIAFE que não está em peça alguma do processo — em **46 fichas (15,3%)**. Extrapolado às 6.081 respostas guardadas: ordem de 2.500 afirmações sem lastro no banco, em texto que o painel exibe como "análise" e "perícia". Corrigido para fichas novas (§3.1). |
| D3 | **A VM-1 faz o trabalho que devia orquestrar.** | 3 | 20/11 20h30: carga 12–18 em 2 vCPU, com `sei_depurar_pdfs`, `galaxia gerar`, `processo_360 --lote 120`, `pericia_integral`, o portão de pre-push, três runners de bancada, o servidor e 30 processos de Chromium **ao mesmo tempo** — enquanto o it-campo (24 núcleos, RTX 5070) estava em 16% de CPU e 0% de GPU com a fila de OCR vazia. A regra "1 pesado por vez" é violada pelos próprios crons (115 linhas ativas no crontab + 78 derivados na propagação). |
| D4 | **O espelho TFE ainda fala como se fosse pagamento.** | 5 | A passada final migrou 6 pontos para a régua `_ob_paga` (SIAFE) e inventariou ~40 somas de `ordens_bancarias.valor` ainda apresentadas como pago em `/relatorio`, `/orgao`, dossiê, grafo e perfil. 87 arquivos de código ainda leem a tabela do espelho. Onde foi medido, a diferença é material: rede de sócios R$ 155.353.956.166,75 → R$ 136.907.074.138,16 (−11,9%). Viola a regra absoluta nº 2 da casa nos dois produtos mais vistos. |
| D5 | **Código que existe e não roda.** A família nº 1 do catálogo continua a maior. | 2–4 | 43 módulos de `compliance_agent/` sem chamador de produção no repositório (medido nesta revisão): 3 agendados só no crontab, 25 CLIs sem agendamento e **15 bibliotecas que só os testes exercitam, com 211 funções de teste verdes** — entre elas entregas inteiras do plano de hermenêutica (`dosimetria`, `matriz_achados`, `qualificacao_juridica`, `quesitos_diligencia`) e um sinal de rede de sócios que nunca disparou por consultar coluna inexistente (passada final §7.1). Teste verde aqui é custo sem efeito. |

### 2.2 O que a casa continua errando, e por quê (estrutura, não episódio)

O catálogo tem 64 famílias, mas elas se reduzem a **quatro mecanismos**. Enquanto o mecanismo não for barrado por
código, a família reincide com outro nome.

| Mecanismo | Famílias do catálogo que são o mesmo erro | Por que reincide | O que barra de verdade |
|---|---|---|---|
| **A. Sucesso declarado pela ação, não pelo efeito** | 1, 5, 7, 14, 30, 33, 54, 55, 57, 63 (construído e nunca rodado; falha calada; catraca que mente; drenador morto 16 dias; motor "rodando" 84× com erro e rc=0) | O critério de "pronto" é *o código existe e o teste passa*. Ninguém é obrigado a mostrar a linha gravada, a fila drenada, o número que mudou. Cron não tem contrato de efeito. | Todo produtor declara o **efeito mensurável** (linhas, arquivo, idade) e um sensor cobra. A propagação já tem `efeito:`; os 115 crons não. A catraca nova (melhoria 4) fecha a porta de entrada. |
| **B. Ausência lida como fato** | 2, 20, 36, 47, 51, 52 (corte por posição, coleta que morre no meio, balde de ignorância) | `INDISPONÍVEL ≠ 0` é regra escrita, mas o tipo de dado não a carrega: a função devolve `[]`, `0` ou `""` tanto para "não há" quanto para "não li". | Estado explícito no retorno (`VERIFICADO/PENDENTE/INDISPONÍVEL`) — já existe em `llm/verificacao` e na certeza; falta nos coletores e nos detectores antigos. |
| **C. Cópia divergente da régua** | 4, 26, 41 e as três cópias de teto de dispensa, as ~40 somas do espelho TFE, as duas máscaras de CPF, as três definições de "ente público" | Régua nasce privada (`_ob_paga` tem 53 importadores de um nome com `_`), então copiar é mais fácil que importar. | Promover a régua a API pública com nome, e catraca que proíbe o literal fora dela (já feito para tetos; falta para OB paga). |
| **D. O texto engana o extrator** | 12, 15, 18, 19, 23, 61 (metadado dentro do dado, menção × fonte, norma × fato, janela híbrida) | Regex e modelo barato leem *palavras*; a pergunta do fiscal é sobre *atos*. | Conferência literal por código depois de toda extração (melhoria 1) e juízo só na camada do Opus — nunca relaxar isso por volume. |

Há ainda um quinto, de **processo de trabalho**, que apareceu três vezes só em 20/11: integrar o trabalho de
agentes paralelos por patch, à mão. Rendeu remoção perdida (14 arquivos), disco cheio (45 worktrees) e um `amend`
que travou o `pull --ff-only` do it-campo por um dia. A melhoria 3 mecaniza a conferência; a regra "nunca amend
depois que outra máquina pode ter puxado" continua dependendo de memória.

### 2.3 Desperdício de custo, cota e máquina

| Item | Medida | Leitura |
|---|---|---|
| Cota do Opus em alerta de detector ruim | 5 detectores acima de 30% de falso positivo em 30 dias: fracionamento 68% (107 vereditos), doerj_anomalia 58% (50), emendas_d3 56% (621), direcionamento 54% (242), pcrj_d9 37% (506) | ~770 julgamentos do juiz gastos em ruído num mês (soma dos falsos positivos dos cinco). Parte já foi atacada em 19–20/11 (régua de credor institucional, D3 posterior à emenda). O sensor mede; quem corrige ainda é uma pessoa. |
| GPU e 24 núcleos parados | it-campo 20/11 19h44: CPU 16%, GPU 0%, fila de OCR 0 | Problema de **suprimento**, não de capacidade: a captura SEI é limitada por IP (12–18 navegadores derrubam a conexão) e é ela que alimenta tudo. Ociosidade com fila vazia não é defeito — é o teto real do sistema. |
| VM-1 saturada | carga 12–18 em 2 vCPU | Tudo o que é computação sobre dado já coletado (galáxia, Processo 360 em lote, depuração de PDF, perícia integral) devia rodar na réplica do it-campo, como os padrões já rodam (24 detectores em 1.662 s lá). |
| Suíte de testes | 9.958 testes, 908 arquivos; ~30 arquivos leem a máquina real | 211 funções testam módulo sem chamador. Suíte que só roda na VM-2 e em lotes é sintoma: o que protege o push são ~13 catracas, não os 9.958. |
| Worktrees de agente | ~340 MB cada; 45 = 14 GB | Sem limpeza automática, cada rodada de agentes em paralelo custa disco numa máquina a 94–95%. |
| Bancada de modelos grátis | T1 no Sonnet: 100 itens, US$ 2,86; nemotron super/lightning inventaram valor e dispositivo | O critério do dono (≥ Sonnet **e** zero erro) elimina quase todo modelo grátis em extração com número. O ganho real de custo está em **não chamar modelo** onde regex + conferência literal resolvem, não em trocar de modelo. |

### 2.4 Riscos de acurácia ainda abertos

| Risco | Sev. | Estado | O que falta |
|---|:-:|---|---|
| Ficha do acervo (Haiku) — texto corrido | 5 | **Fechado para fichas novas** (melhoria 1). As ~6.081 já gravadas seguem na v1. | Rodar `--regravar` nos 130 lotes guardados (sem custo de API). Decisão do dono (§5, item 1). |
| Ficha do acervo — a inferência | 4 | A citação confere; a **conclusão** tirada dela não é conferível por código. `nivel_risco` já não é gravado; `analise` e `pericia_*` continuam sendo opinião de modelo barato. | Tratar `analise`/`pericia_*` como rascunho: nunca exibir sem o selo "triagem, não conferida pelo Opus"; nunca alimentar detector. |
| OCR | 4 | Regra nova (20/11): OCR novo nunca substitui texto existente; 8.289 documentos restaurados. Tesseract de produção acerta 78,0% dos valores em R$ no gabarito. | 219.125 documentos (60% do acervo) foram lidos pelo Tesseract e só ~6 mil ainda têm PDF. Valor em R$ vindo de documento `ocr=True` precisa sair marcado como tal em perícia e ficha — hoje não sai. |
| Espelho TFE em `/relatorio` e `/orgao` | 5 | Aberto (D4). | Rodada comparada dos três produtos e troca de fonte. Decisão do dono (§5, item 2). |
| PDF consolidado do SEI | 4 | 2 de 738 documentos omitidos sem aviso no teste real; a conferência por marcador foi integrada. | Manter a conferência doc a doc **obrigatória** como portão de "íntegra completa" — nunca confiar no "Gerar PDF: Todos". |
| Detectores com falso positivo alto | 4 | Sensor liga; 5 abertos. | §4, prioridade 3. |
| Conferência por dígitos | 3 | `numero_no_trecho` compara só a sequência de dígitos: "R$ 123.456,78" confere com o CNPJ "12.345.678/…" (achado nesta revisão ao escrever teste). | Conferir valor monetário contra números **monetários** da fonte (o `_Fonte.centavos` da melhoria 1 já faz isso; `numero_no_trecho` segue aceitando por dígitos, para não derrubar recall sem medir). |
| CPF na janela D1–D3 + DV vindo da fonte (`fiscal_doc`) | 4 | Aberto (passada final §3). | Decisão do dono (§5, item 4). |

### 2.5 Estado da arte — o que a literatura e as referências dizem sobre o que a casa faz

- **Extração com conferência determinística é o desenho certo, e a casa já o tem.** Bibliotecas de saída
  estruturada garantem o *formato*, não que o valor esteja no documento; a verificação por alinhamento de trecho
  (string) depois da extração é a linha recomendada, e casar valor "em outra grafia" (datas, moeda) é parte
  obrigatória dela — exatamente o defeito de recall medido aqui (394 datas verdadeiras descartadas em 300 fichas).
  Fontes: [llmground](https://pypi.org/project/llmground/), [SAFEPASSAGE, arXiv 2510.00276](https://arxiv.org/pdf/2510.00276v1),
  [LlamaIndex — citation-grounded extraction](https://www.llamaindex.ai/glossary/citation-grounded-extraction).
- **Juiz LLM não substitui conferência por código em nível de trecho.** Um benchmark de 2026 reporta detector
  pequeno ajustado com 0,689 de F1 por trecho contra no máximo 0,22 dos melhores juízes LLM sem ajuste; trabalho de
  extração jurídica nota que conferir campo de texto livre com outro LLM "pode ele mesmo alucinar". Confirma a
  regra da casa: código confere o literal, Opus só julga. Fontes:
  [arXiv 2607.00895](https://arxiv.org/abs/2607.00895), [arXiv 2607.03325](https://arxiv.org/pdf/2607.03325),
  [FullCite, arXiv 2606.07130](https://arxiv.org/pdf/2606.07130). *Ressalva: são preprints, lidos por resumo.*
- **Red flag é medida de risco, não de irregularidade.** O guia de 2024 da Open Contracting Partnership (73
  indicadores) afirma que os indicadores "sozinhos não estabelecem impropriedade"; a literatura de validação trata
  red flag como *proxy* a ser validado contra resultado. Nem OCP nem OCDE publicam protocolo de taxa de falso
  positivo — o sensor `detectores` da casa (veredito do juiz × tipo de alerta) está **à frente** da prática
  publicada; o que falta é fechar o laço dele. Fontes:
  [OCP — Red flags in public procurement (2024)](https://open-contracting.org/wp-content/uploads/2024/12/OCP2024-RedFlagProcurement-1.pdf),
  [OCP — red flags](https://open-contracting.org/redflags), [arXiv 2309.01462](https://pdf.arxiv.org/pdf/2309.01462),
  [OCDE — indicadores de risco](https://t4.oecd.org/governance/procurement/toolbox/search/indicators-procurement-risk.pdf).

---

## 3. O que foi feito — com número antes × depois no mesmo dado

### 3.1 Ficha do acervo: o texto corrido também é conferido contra o processo (`10af1553`)

**Problema.** `tools/sei_ficha_acervo.conferir` descartava o que não conferia nas listas (valores, CNPJs, datas,
partes, documentos, red flags) e gravava **como o Haiku escreveu** os campos de texto: `objeto`, `resumo`,
`analise`, `pericia_contabil`, `pericia_juridica`, o `ponto` de cada documento, o texto da red flag depois da
citação e a anotação entre parênteses de cada item. Os "239 itens graves em 100 fichas" da bancada são os das
listas — esses a produção já descartava. O que escapava era o texto.

**O que mudou.**
1. Frase que afirma valor em R$, CNPJ, data completa ou nº de documento do SIAFE (`2025NL00384`) **ausente do
   processo** é descartada — nunca corrigida — e contada em `verificacao.conferido.narrativa` (frases, fatos sem
   fonte, exemplos). Red flag e item de lista com fato sem fonte fora da citação caem inteiros.
2. **Conta do modelo é refeita pelo código**: soma de duas ou três parcelas e diferença de duas, onde as parcelas
   são valores que a própria ficha cita e que estão no texto. Um centavo fora, a frase cai.
3. Arredondamento ("R$ 9,06 milhões") só vale se algum valor do texto arredonda para ele na casa escrita.
4. **Recall**: data e valor em outra grafia deixam de ser dados como ausentes ("3 de fevereiro de 2025",
   `03.02.2025`, `2025-02-03`; `12369.6`, `1357985.5399999998`).
5. **A fonte da conferência passa a ser o processo inteiro no acervo**, não só a janela de 60 mil caracteres de
   hoje. Achado à mão: de 12 fatos "ausentes" abertos um a um, 4 estavam no processo, fora da janela — o acervo
   muda entre o envio do lote e a conferência (recaptura, OCR restaurado em 8.289 documentos, `--regravar` dias
   depois) e a ordem por valor fiscalizatório muda junto.
6. `VERSAO` passa a `acervo-v2` (`fonte_modelo` distingue a régua de cada ficha).

**Prova (300 respostas já pagas, sorteio fixo de `data/claude_api_lotes`, 6.081 no universo; só leitura).**

| Medida | v1 (`38972e5a`) | v2 (`10af1553`) | Δ |
|---|---:|---:|---:|
| Fatos sem fonte **gravados** no texto corrido e nas anotações | 126 | 0 | −126 |
| Fichas com pelo menos um fato sem fonte gravado | 46 de 300 (15,3%) | 0 | −46 |
| Frases descartadas (de 11.506) | — | 90 (0,78%) | |
| Itens de lista / red flags descartados pela anotação | — | 21 | |
| Contas do modelo refeitas e confirmadas pelo código | — | 120 | |
| Datas aceitas (de 2.053 dadas) | 1.634 (79,6%) | 2.028 (98,8%) | +394 |
| Valores aceitos (de 1.305) | 1.244 (95,3%) | 1.278 (97,9%) | +34 |
| Documentos com trecho literal (de 3.300) | 3.009 (91,2%) | 3.077 (93,2%) | +68 |
| Red flags com citação literal (de 2.478) | 2.256 (91,0%) | 2.277 (91,9%) | +21 |
| CNPJs aceitos (de 576) | 557 | 561 | +4 |
| Partes aceitas (de 1.244) | 947 | 962 | +15 |

Leitura: a v2 é **mais dura onde havia erro** (126 afirmações sem lastro deixam de ser gravadas, ao custo de 0,78%
das frases) e **mais justa onde havia perda** (394 datas e 68 documentos verdadeiros que a v1 jogava fora por
grafia ou por estarem fora da janela do dia). "0" na primeira linha é pela mesma régua que descarta — é o que a
régua garante, não uma medida independente; a medida independente é a conferência à mão abaixo.

**Erro real que a régua pegou** (aberto à mão): processo `270064_000270_2023` — o texto diz
"R$ 236.207,17"; a ficha escrevia "R$ 236.207,16" no resumo e na perícia contábil. Um centavo, três vezes.

**Limite declarado.** A régua confere *fatos escritos com número*. Afirmação sem número ("não há pesquisa de
preços") segue sem conferência por código — é o risco "inferência" da §2.4.

**Testes.** `tests/test_sei_ficha_acervo.py`: 11 passam (6 novos: frase descartada e contada; outra grafia;
conta refeita e conta errada por um centavo; arredondamento; anotação e red flag; fonte integral).

### 3.2 it-campo ocioso: de aviso a laço (`0e519fca`)

**Problema.** `avaliar_maquinas` abria "it-campo: GPU em 0% (OCR parado?)" com ação humana. O item estava
REINCIDIU havia 4 rodadas; ninguém age em aviso de sistema silenciado. E "ociosa" com fila vazia não é defeito.

**O que mudou.** A decisão usa a fila de OCR dos dois lados — a do trabalhador (`ocr_gpu.restantes`) e a que a VM-1
publica (`data/sei_ocr_gpu_fila.txt`, linhas e idade):

| GPU < 50% e… | Diagnóstico | Saída |
|---|---|---|
| trabalhador sem fila; fila da VM-1 com mais de 3 h ou ausente | falta suprimento | **remédio automático**: `python -m tools.sei_ocr_gpu_fila` (regera a fila, com o arquivo frio) |
| trabalhador sem fila; fila da VM-1 nova e vazia | não há trabalho | **nada** — deixa de virar item |
| trabalhador com fila | trabalhador quebrado | escala ao dono (`gpu_parada_com_fila`), sem remédio |
| fila nova publicada e o trabalhador segue vazio | não está puxando | escala ao dono (`gpu_fila_nao_puxada`) |

CPU ociosa só vira item se houver trabalho (ou se não der para saber). Dois remédios sem cura continuam escalando
pelo mecanismo que já existia.

**Prova no estado real** (`data/itcampo_estado.json` de 20/11 19h44 + fila real: 88 linhas, 4,4 h):

| | Assinatura | Título | Remédio |
|---|---|---|---|
| Antes | `maquinas:itcampo:gpu_ociosa` | it-campo: GPU em 0% (OCR parado?) | — (ação humana) |
| Depois | `maquinas:itcampo:gpu_ociosa` | GPU em 0% e fila de OCR vazia no trabalhador; a fila publicada pela VM-1 é de 4.4 h atrás | `PYTHONPATH=. .venv/bin/python -m tools.sei_ocr_gpu_fila >> data/sei_ocr_gpu_fila.log 2>&1` |

O remédio **não foi executado** nesta revisão (não tocar o it-campo); roda na próxima rodada da automelhoria
depois da integração (cron `40 */3`).

**Testes.** `tests/test_automelhoria_geral.py`: 2 novos (as cinco linhas da tabela + contagem/idade da fila).

### 3.3 Integração de agentes: remoção perdida e worktree esquecido (`0e519fca`)

**Ferramenta nova** `tools/integracao_conferir.py`:
- `remocoes <branch> [--em HEAD]` — caminhos que o agente apagou ou renomeou e que ainda existem. Sai com código 1.
- `stage` — remoção parada no índice.
- `worktrees [--aplicar] [--horas N]` — lista; com `--aplicar` remove **só** worktree limpo, parado há N horas e
  sem processo com diretório de trabalho dentro. A branch fica (os commits do agente não se perdem).

**Sensor novo** `integracao` na automelhoria: worktrees removíveis com disco ≥ 85% ou ≥ 10 worktrees → remédio
automático (`worktrees --aplicar --horas 12`); remoção em stage → ação do dono.

**Prova no histórico real** (42 branches de agente):

| Conferido contra | Remoções de agente que não chegaram |
|---|---:|
| `af86ddd7` (antes da passada final) | **14** nas branches dos dois agentes de 20/11 (11 em `…01fc6c`: 8 units de `deploy/` + 3 de `tools/`; 3 em `…78f711`: `tools/sei_*`) — a mesma lista que a passada final achou à mão, incluindo `tools/enviar_forense_telegram.py` |
| `38972e5a` (ponta) | **0** |

Worktrees em 20/11 20h20: 1 (o desta revisão, sujo e em uso — corretamente mantido). Disco: 95%.

**Testes.** `tests/test_integracao_conferir.py`: 4 (remoção e renomeação apontadas e resolvidas; worktree limpo
sai e sujo fica, branch preservada; processo vivo dentro impede; sensor remedia worktree e escala remoção).

### 3.4 Catraca: módulo sem chamador de produção não entra (`21f2cecc`)

**Problema.** `test_ferramenta_tem_quem_a_rode` só cobre as ferramentas que alguém pôs na tabela; a família
reincidiu três vezes depois dela. O módulo que nasce órfão não está em tabela nenhuma.

**O que mudou.** `tests/test_catraca_modulo_sem_chamador.py`: todo módulo de `compliance_agent/` precisa de um
importador fora de `tests/` **ou** de uma citação por nome em shell, yaml, unit ou código (é como entram o `-m`
do cron, a propagação e o `importlib`). Pacotes carregados por descoberta (`padroes`, `migrations`) estão
nomeados com o carregador. O que já era órfão fica em `tests/baseline_modulos_sem_chamador.txt`, **anotado e só
podendo encolher** (um segundo teste cobra a retirada de quem ganhou chamador).

**Medida em `38972e5a`: 43 módulos sem chamador no repositório.**

| Classe | Módulos | Leitura |
|---|---:|---|
| `[cron]` — agendado só no crontab da VM-1 | 3 | chamador existe, mas fora do repositório: some se a VM for refeita |
| `[cli]` — tem `__main__`, nenhum agendamento achado | 25 | uso manual ou morto; cada um é uma pergunta ao dono |
| `[biblioteca]` — só os testes exercitam | 15 | 211 funções de teste verdes sobre código que não roda |

> **Errata.** A mensagem do commit `21f2cecc` diz "26 com `__main__`" e "16 bibliotecas"; a conta certa é a desta
> tabela (25 e 15 — a contagem tinha somado a linha de legenda do arquivo). O arquivo de baseline está correto.

**Controle positivo.** Módulo novo com teste e sem chamador → a catraca falha com a instrução do que fazer.
**Custo:** 0,9 s de CPU. Entrou em `CATRACAS` do portão de pre-push e do sensor de catracas.

### 3.5 Verificação

| Conjunto | Resultado |
|---|---|
| `test_sei_ficha_acervo`, `test_automelhoria_geral`, `test_integracao_conferir`, `test_catraca_modulo_sem_chamador`, `test_regra_registro`, `test_regra_sensores`, `test_ferramenta_tem_quem_a_rode`, `test_import_nao_executa_trabalho` | **112 passam** (VM-1, `nice -n 15`) |
| Catracas transversais: `test_catraca_excepts`, `test_divida_except_pass`, `test_regra_catracas`, `test_regra_inventario`, `test_catraca_nao_pode_ser_tolerada` | **49 passam** |
| `ruff check` nos arquivos tocados | limpo |
| Suíte inteira | **não rodada** — VM-1 em carga 12–18; rodar por `tools/testar_na_vm2.sh` antes de integrar |

GitNexus: `impact` não acha `conferir` nem `avaliar_maquinas` (índice desatualizado em relação à branch);
chamadores conferidos por busca de texto — `tools/fila_analise_sei.sh` (ficha) e `sensor_maquinas` (único).
Nenhum código lê `verificacao.conferido`, então a chave nova `narrativa` não quebra leitor.

---

## 4. Plano priorizado

Ordem por impacto no objetivo ÷ esforço. "S" = cabe numa sessão; "M" = um dia; "G" = sábado (cota semanal).

| # | Ação | Objetivo servido | Esforço | Critério de pronto (efeito, não ação) |
|:-:|---|---|:-:|---|
| 1 | Regravar as fichas já colhidas na régua v2 | acurácia | S | `SELECT COUNT(*) … fonte_modelo LIKE '%#acervo-v1'` = 0; soma de `narrativa.fatos_sem_fonte` registrada |
| 2 | Trocar a fonte de pagamento de `/relatorio` e `/orgao` para SIAFE (`_ob_paga`), com rodada comparada | acurácia (regra nº 2) | G | nenhum `SUM(ordens_bancarias.valor)` rotulado "pago" fora da régua; catraca proibindo o literal |
| 3 | Fechar o laço dos detectores: FP ≥ 50% com n ≥ 50 → detector sai da triagem do Opus sozinho (alerta fica gravado, marcado "em revisão") até alguém corrigir | custo de cota + ruído | M | vereditos do juiz por mês em detector suspenso = 0; item some do sensor quando a taxa cai |
| 4 | Tirar computação da VM-1: `galaxia gerar`, `processo_360 --lote`, `sei_depurar_pdfs`, `pericia_integral` (parte determinística) para a réplica do it-campo, como os padrões | rapidez + estabilidade | G | carga de 15 min da VM-1 < 2,5/núcleo por 24 h; item `vm1:sobrecarga` curado |
| 5 | Contrato de efeito para cron: cada linha do crontab vira derivado da propagação ou entrada de `config/pipelines.yaml` com `efeito:` | mecanismo A (§2.2) | G | 0 linha de crontab sem dono declarado; os 3 `[cron]` saem da baseline |
| 6 | Decidir os 15 módulos `[biblioteca]`: ligar (com medição no dado real) ou apagar | custo de manutenção | M | baseline ≤ 28 |
| 7 | Marcar valor vindo de documento `ocr=True` em ficha e perícia | acurácia | S | ficha traz `origem_ocr` por valor; perícia não gradua 🔴 sobre valor só de OCR |
| 8 | Promover `_ob_paga` a API pública e proibir o literal de status fora dela | mecanismo C | M | 53 importadores no nome novo; catraca verde |
| 9 | Disjuntor por sessão SEI (N falhas iguais → limpar e relogar / parar e avisar) | rapidez da captura (o gargalo real) | S | nenhuma sessão com > 20 falhas idênticas seguidas no log |
| 10 | `numero_no_trecho` monetário (não por dígitos soltos), medido antes × depois | acurácia | S | zero valor aceito por coincidir com CNPJ/telefone na amostra de 300 |

---

## 5. Decisões que são do dono

| # | Decisão | Por que não decidi | Recomendação |
|:-:|---|---|---|
| 1 | Rodar `python -m tools.sei_ficha_acervo --regravar <lote>` nos 130 lotes guardados | Escreve em `data/compliance.db` (fora do mandato desta revisão) e muda o texto de ~6 mil fichas | **Sim**, fora do horário do painel; sem custo de API. Medir antes × depois por `verificacao`. |
| 2 | Espelho TFE → SIAFE em `/relatorio`, `/orgao`, dossiê e `detector_tac` | Muda número publicado em produto; pede rodada comparada dos três | **Sim, no sábado.** É a maior exposição a erro que resta. |
| 3 | Suspender sozinho da triagem do Opus o detector com FP ≥ 50% | É regra de produto: um detector deixaria de gerar julgamento sem ordem humana | **Sim**, com o alerta preservado e reentrada automática quando a taxa cair. |
| 4 | `fiscal_doc` do ContasRio (janela D1–D3 + DV) | LGPD: com a máscara da casa na outra tela o CPF fecha | Exibir só o nome. |
| 5 | Os 15 módulos `[biblioteca]` e os 25 `[cli]` sem agendamento | Ligar acende sinal nunca medido; apagar remove entrega pedida | Lista em `tests/baseline_modulos_sem_chamador.txt`. Começar por `dosimetria` (cita artigo inexistente) e pelo sinal de rede de sócios (1.360 fornecedores acenderiam). |
| 6 | Limpeza automática de worktree pela automelhoria | Remove diretório sem perguntar (só limpo, parado 12 h, sem processo; branch fica) | **Sim.** O dano de não ter foi o juiz fora do ar. |
| 7 | Avisos de sistema silenciados desde 17/11 | Sem canal, "escalar ao dono" não chega | Manter o silêncio e ler a fila pelo `/melhorias` uma vez por dia — ou reabrir só para `escalado`. |
| 8 | `analise` e `pericia_*` do Haiku no painel | Texto de modelo barato exibido como análise | Selo fixo "triagem automática — não conferida" ou não exibir. |

---

## 6. O que esta revisão **não** fez

- Não rodou a suíte inteira (VM-1 saturada); não integrou na branch principal; não fez push.
- Não executou nenhum remédio (fila de OCR, remoção de worktree) nem regravou ficha: tudo só leitura sobre `data/`.
- Não mediu a régua v2 no universo de 6.081 fichas — a amostra é de 300, sorteio fixo (`random.Random(20261120)`).
- Não revalidou à mão os 126 fatos sem fonte um a um: 12 foram abertos: 5 eram ausência real ou erro do
  modelo, 4 estavam no processo fora da janela do dia e 3 eram grafia — duas passaram a conferir (`12369.6`,
  `1357985.5399999998`); a terceira (`1687 510,72`, espaço como separador de milhar) segue descartada de
  propósito, porque aceitar espaço juntaria números vizinhos.
- Pesquisa de estado da arte por resumo de busca, sem leitura integral dos artigos.

Scripts de medição (fora do repositório, regeneráveis):
`/tmp/claude-1001/-home-ubuntu/0743404b-e253-4f4d-aaab-ea0e48e8303b/scratchpad/revisao/` —
`antes_depois.py`, `medir_ficha.py`, `diag.py`, `mao.py`, `prova_remocoes.py`, `itc_real.py`, `classificar.py`.
