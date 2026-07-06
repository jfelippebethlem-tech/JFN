# reports/ — Produtos gerados pelo ecossistema JFN

> **Regra de organização:** a raiz guarda apenas a **versão mais recente** de cada produto.
> Versões anteriores vão para `arquivo/AAAA-MM/` (mesmo nome de arquivo).
> Arquivos datados seguem o padrão `<produto>_<AAAA-MM-DD>.<ext>`.

## Produtos e geradores

| Prefixo do arquivo | Produto | Gerador |
|---|---|---|
| `parecer_lex_<fornecedor>_` | Parecer jurídico-pericial Lex (fornecedor) | `compliance_agent/lex.py` |
| `parecer_lex_orgao_<ug>_` | Parecer Lex por órgão/UG | `compliance_agent/lex.py` |
| `inteligencia_<fornecedor>_` | Relatório de inteligência/due diligence (padrão Kroll) | `compliance_agent/reporting/inteligencia.py` |
| `inteligencia_orgao_<ug>_` | Inteligência por órgão/UG | `compliance_agent/reporting/inteligencia_orgao.py` |
| `pericia_camara_` / `pericia_prefeitura_` | Perícia da folha Câmara/Prefeitura PCRJ | `compliance_agent/pcrj/pericia_pcrj.py` |
| `pericia_beneficios_nomeados_` | Benefício social × servidor nomeado | `compliance_agent/pcrj/pericia_beneficios.py` |
| `pericia_socios_fornecedores_beneficio_` | Benefício social × sócio de fornecedor | `compliance_agent/pcrj/pericia_socios_beneficio.py` |
| `pcrj_camara_cruzamento_` | Cruzamento Câmara×Prefeitura | `compliance_agent/pcrj/` |
| `pcrj_dossie_completo_` / `pcrj_gabinetes_*` / `pcrj_alvos_*` / etc. | Dossiês e panoramas PCRJ | `compliance_agent/pcrj/` (módulo homônimo) |
| `compliance_<data>.pdf` | Relatório diário de compliance (enviado no Telegram) | `compliance_agent/reports/` via scheduler |
| `_*.json` | Artefatos intermediários de reconciliação (não são entregáveis) | perícia bombeiros |

## Subpastas

- `arquivo/AAAA-MM/` — versões superadas (mantidas para trilha de auditoria).
- `charts/` — PNGs de gráficos usados pelos PDFs.

## Convenções

- Entregável final = **PDF** (padrão visual Kroll); `.md`/`.html`/`.xlsx` são fontes/anexos do mesmo produto.
- Nunca editar um relatório gerado à mão — corrigir o gerador e regerar.
