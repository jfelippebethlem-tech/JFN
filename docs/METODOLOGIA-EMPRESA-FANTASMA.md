# Metodologia — empresa fantasma/fachada + foto sem Google API

> Como o JFN decide se um favorecido é empresa de fachada, e como conferir a
> fachada real sem depender (nem pagar) a API do Google Maps.

## 1. Triagem por sinais cruzados (determinística, sem IA)

`compliance_agent/empresa_fantasma.py` · Yoda: `/fantasma <CNPJ>`

Nenhum sinal isolado condena (indício ≠ acusação). O score cruza:

| Sinal | Peso | Fonte no banco |
|---|---|---|
| situação BAIXADA/INAPTA/SUSPENSA | 32 | `empresas.situacao` (RFB via BrasilAPI) |
| sancionada CEIS/CNEP | 24 | `sancoes_federais` |
| capital ínfimo vs recebido (≥500×) | 22* | `empresas.capital_social` × Σ OB |
| endereço-ninho (≥10 empresas no mesmo end.) | 20 | `endereco_fornecedor.endereco_norm` |
| aberta ≤1 ano antes do 1º grande pagamento | 18 | `empresas.data_abertura` × 1ª OB |
| CNAE incompatível com o objeto pago | 16 | `empresas.atividade_princ` × observação OB |
| sócio único com capital simbólico | 12 | `empresa_socios` |
| endereço residencial (casa/apto/lote) | 10 | `endereco_fornecedor.endereco` |

`*` capital cai para peso 6 em OS/OSCIP/associação (capital ínfimo é legítimo —
evita a lista virar só entidade sem fins lucrativos).

Faixas: ≥60 alto · ≥30 médio · <30 baixo. **É triagem** — manda verificar.

## 2. Verificação in loco — foto da fachada SEM Google API ($0)

`tools/fachada_capturar.py` · `--cnpj` | `--endereco` | `--latlon`

1. Geocodifica no **OSM/Nominatim** (grátis, sem chave).
2. Tira **screenshot do Street View embed clássico** (`output=svembed`, dentro
   de um iframe) num headless via `vm_guard`. É a MESMA imagem do Google, mas
   capturada da tela — **não** usa a Static API paga (desligada por billing).
3. Tenta 4 ângulos; marca `cobertura: false` honestamente se não há imagem.

Saída: `data/fachadas/<slug>.jpg` + `.json`. Provado ao vivo (imagem real, 63KB).

> Uma empresa de alto valor com score de fachada alto **e** cuja foto mostra
> terreno baldio / casa residencial / imóvel incompatível com o objeto é o
> caso mais forte para representação ao TCE.

## 3. Fluxo completo (o que rodar, em ordem — barato→caro)
```bash
/fantasma 19088605000104                              # 1. triagem (grátis, banco)
tools/fachada_capturar.py --cnpj 19088605000104       # 2. foto real da fachada ($0)
/pericia 19088605000104                               # 3. perícia das OBs (Núcleo)
tools/sei_consultar.py "PROC" --fase execucao         # 4. medição/atesto no SEI
```
Ver também `docs/PLAYBOOK-SEI.md` e `docs/METODOLOGIA` do Núcleo.
