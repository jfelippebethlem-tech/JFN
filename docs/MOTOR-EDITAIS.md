# Motor de Avaliação de Editais e Licitações — E7 + coletor_ata + Jurisprudência

> Auditoria determinística (com LLM só como âncora) de cláusulas de edital e das fases de habilitação/julgamento.
> Aprimorado e validado em dado real SEI em 2026-07-08 (branch `seguranca/ssrf-captcha`, commits `bf17ba3`→`129dfa4`).

---

## 1. O que faz

Analisa **cada cláusula** de um edital para ilegalidade ou restritividade (direcionamento), cruza essas cláusulas
com as **decisões da ata de julgamento** (habilitação/inabilitação/classificação/desclassificação) e **fundamenta
cada achado em súmula/acórdão** de Tribunal de Contas (TCU/TCE-RJ). Saída: `ResultadoDetector` por detector
(score com âncoras, evidência com hash, explicação inocente, verificador adversarial).

## 2. Arquitetura (regra de ouro: limiar no código, nunca no prompt)

| Camada | Onde | Papel |
|---|---|---|
| Extração — edital | `detectores/coletor_edital.py` | regex determinístico → `clausulas_edital` (catálogo de 12 tipos) + `exigencias_habilitacao` (E1) |
| Extração — ata | `detectores/coletor_ata.py` | decisões/propostas/`resultado` da ata (reusa `j7.classificar_classe_falha`); segmenta por CNPJ |
| Detectores | `detectores/e7_clausula_restritiva.py` (E7) + E1–E6, J2–J7 | teste finalístico por cláusula + efeito combinado + cruzamento com resultado |
| Jurisprudência | `knowledge/jurisprudencia.py` | `INDICE_CLAUSULA`, `fundamentar_clausula(tipo)`, `SUMULAS` (verbatim conferido) |
| Fundamento | `detectores/base.py` | âncoras, rubrica fechada c/ citação obrigatória, verificador adversarial, convergência multiplicativa |

**E7** (`desenho_certame`, peso 0,6) — testes finalísticos com limiar no código: capital/PL > 10% (Súm. 275),
garantia > 1%, marca sem "ou equivalente" (Súm. 270), visita sem declaração substitutiva (art. 63), vínculo
prévio (Súm. TCE-RJ 10), sede local, atestado > 50% (Súm. 263), etc. **Efeito combinado:** ≥ 3 categorias
distintas → forte (Ac. TCU 1.065/2024). **Cruza com a ata:** inabilitação em cascata + poucos licitantes → eleva
e *explica o resultado*.

## 3. Como rodar

```bash
# um processo (lê do SEI via itkava, ou do cache 24h):
PYTHONPATH=. .venv/bin/python -m compliance_agent.detectores.coletor_edital "SEI-UUUUUU/NNNNNN/AAAA" --llm

# em código:
from compliance_agent.detectores.coletor_edital import analisar_processo_sei_sync
out = analisar_processo_sei_sync("SEI-510001/000571/2024")   # {ctx_resumo, resultados[], confirmados, ...}
```

O motor roda `rodar_edital` (E1–E7) + `rodar_planejamento` (P1/P2/P5) e, se a ata trouxe `decisoes`/`propostas`,
`rodar_julgamento` (J2–J7). Sem edital/ata legível → `nao_avaliavel` (campo ausente ≠ 0).

## 4. Sweep dos editais (onde eles vivem)

Editais vivem no **processo-pai de contratação**, não no docket de pagamento. Para alimentá-los:
- **Foco por UG:** adicionar a UG ao `data/ugs_foco.txt` (ex.: `660100` = Sec. das Cidades / MUV-Grupo Vieira);
  o `sweep_sei.sh` (cron) lê os processos da UG por valor e segue os relacionados.
- **Campanha acelerada:** `tools/sweep_tudo_editais.sh [MAXITER]` — bounded, resumível, parável, VM-guardada,
  **sessão itkava única** (espera o cron liberar). Prioriza `sei_sweep --seguir-pais` (processo-pai = edital) +
  geral. Parar: `touch data/.stop_sweep_tudo`. Pausar tudo: `touch data/.pause_sweeps`. Logs:
  `data/sweep_tudo_editais.log` (progresso) e `data/sweep_tudo_achados.log` (motor nos editais cacheados).
- Escala: ~40k processos → campanha incremental (o cron cobre a cauda ao longo dos dias).

## 5. Jurisprudência (verbatim de fonte primária + honestidade)

`fundamentar_clausula(tipo)` → `{sumulas, acordaos:[Acordao], dispositivos_legais, teste_finalistico,
verificar_antes_de_citar}`. Súmulas TCU (177/247/263/269/270/272/275/281/289) e TCE-RJ (nº 01 visita, nº 10
vínculo) com **texto conferido em fonte primária** (`pesquisa.apps.tcu.gov.br`, `tce.rj.gov.br`). Itens ainda de
fonte secundária carregam `verificar_antes_de_citar=True` — o relatório exibe o aviso; **nunca** citar número
não-confirmado como definitivo.

## 6. Lições de precisão (pagas com falso positivo em 634 processos/editais reais)

1. **Cláusula só de doc de EDITAL/planejamento, nunca de NF/OB/despacho.** No SEI o título do doc é o NÚMERO
   ("121656966"), não o nome → `sei.fases.classificar` dá 'indefinida'; `_fontes_de_edital` detecta por
   **CONTEÚDO** (marcador: "DA HABILITAÇÃO", "termo de referência", "PREGÃO/CONCORRÊNCIA Nº"…).
2. **Direcionamento = IMPERATIVO/exclusividade, não menção.** `marca_dirigida` só dispara com "deverá ser da
   marca X"/"somente marca Y"/vedação de similar — não com "veículo marca FORD" (objeto), "Marca dos Volumes"
   (coluna de NF), "modelo 504 marca BAUSCH" (equipamento p/ manutenção), "modelo 185" (medida de pneu).
3. **Word-boundary + excludentes:** `solv[êe]ncia` casava "in**solvência** civil"; "atestad" casava "nota fiscal
   **atestada** por 2 fiscais". Vetos de certidão/formulário/insolvência.
4. **O motor acerta ao abster-se:** "vínculo empregatício" = código `IRRF - REND DO TRABALHO SEM VÍNCULO` (retenção);
   "50% dos quantitativos" = teto de adesão em ARP — **não** são cláusula restritiva.

**Resultado:** E7 com **0 falso positivo** em 634 processos/editais reais. Verdadeiro-positivo provado no
end-to-end sintético (E1/E7/J7 disparam em edital+ata dirigidos, `tests/test_coletor_edital.py`).

## 6.1 Reader do SEI — 0 docs (debug 2026-07-08)

Sweep voltava ~93% "0 docs". Investigação isolada (screenshot) revelou **dois problemas distintos**, sem
relação com acesso/WAF (itkava é interno; login = só `fill(usuário)+fill(senha)`):

1. **Radio 'Documentos' em vez de 'Processos'** (CORRIGIDO, `3fedc83`): o `_ler_cracked` selecionava o radio
   por `parentElement.innerText` do fieldset 'Pesquisar', que contém as DUAS palavras → nunca marcava
   'Processos' → busca por nº de processo rodava em modo Documentos → caía na caixa da unidade. Fix: seleciona
   pelo `r.labels` (label próprio) + clique no `<label>` exato 'Processos'. Verificado por screenshot.
2. **Busca por Nº SEI retorna 0 resultados** p/ alguns processos (mesmo com Processos marcado): a apurar — pode
   ser número stale na `ordens_bancarias`, processo mesclado/movido, ou formato do protocolo. Investigar **sem
   estrangular o login**: re-login rápido em massa throttla o SSO (erro "login itkava não autenticou"); o sweep
   canônico loga **1×** e itera `ler_processo` (por isso não sofre) — replicar esse padrão no debug (login único
   + loop), nunca `ler()` por processo em rajada.

> Regra operacional: para pausar TODOS os sweeps ao depurar o browser, setar `data/.pause_sweeps`,
> `data/.pause_sei_sweep` **e** `data/.pause_bombeiros` (o bombeiros tem flag própria) + `.pause_sede_sweep`,
> `.pause_fachada_streetview_sweep`. O `browser_lock` serializa (nunca 2 browsers) — 0-docs não é contenção.

## 7. Invariantes de honestidade

indício ≠ acusação · `INDISPONÍVEL`/`nao_avaliavel` ≠ 0 · nunca inventar número · presunção de regularidade ·
score é indício **interno** · itkava é usuário **interno** (lê todas as unidades por número, **sem WAF/captcha**;
0 docs = método, não acesso — ver `~/vault/aprendizados` e a memória `sei-acesso-liberado-nunca-culpar`).

## 8. Arquivos

**Núcleo:** `detectores/e7_clausula_restritiva.py`, `detectores/coletor_ata.py`, `detectores/coletor_edital.py`,
`knowledge/jurisprudencia.py`. **Sweep:** `tools/sweep_tudo_editais.sh`, `data/ugs_foco.txt`, `tools/sei_sweep.py`.
**Testes:** `tests/test_detector_e7.py`, `tests/test_coletor_ata.py`, `tests/test_jurisprudencia.py`,
`tests/test_coletor_edital.py`.
