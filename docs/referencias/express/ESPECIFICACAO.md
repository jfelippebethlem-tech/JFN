# Especificação de design — JFN (para usar no Adobe Express)

> Gerado de `static/jfn-painel.html` em 25/07/2026 01:14. **Não editar à mão** — rode
> `python -m tools.express_ponte --spec` de novo quando a paleta mudar.

## 1 · Paleta (HEX, convertida do OKLCH do painel)

No Express: **Cores da marca → Adicionar cor → colar o HEX**.

| Token | HEX | Papel |
|---|---|---|
| `--ion` | `#59A3FF` | azul — o console: estrutura, interação, frio |
| `--ion-hi` | `#90D7FF` | azul claro — realce de console |
| `--flame` | `#FF8804` | laranja — ENERGIA: ação, dinheiro, carga |
| `--flame-hi` | `#FFBF5C` | laranja claro — número de dinheiro |
| `--rose` | `#FF5472` | rosa — severidade crítica (nunca decorativo) |
| `--green` | `#61DA92` | verde — conforme/ok |
| `--bg` | `#010410` | fundo da página |
| `--card` | `#081222` | superfície de card |
| `--tx` | `#EAF3F8` | texto principal |
| `--mut` | `#90A5B2` | texto secundário |

**Regra de cor da casa:** azul = console/estrutura · laranja = energia/dinheiro ·
rosa e verde só carregam severidade. Cor saturada sem significado é proibida.

## 2 · Tipografia

- **IBM Plex Sans** — texto (auto-hospedada em `/static/assets/fonts/`)
- **IBM Plex Mono** — número, telemetria, CNPJ

As duas são gratuitas e estão na biblioteca do Express. Não substituir por outra
sem-serifa geométrica: o par do painel é serifa-menos-mono, não duas sem-serifa.

## 3 · Medidas das artes que o painel consome

| Arquivo | Dimensão |
|---|---|
| `nebula-estado.jpg` | 1536×384 |
| `nebula-prefeitura.jpg` | 1536×384 |
| `nebula-transversal.jpg` | 1536×384 |
| `portal-nebula.jpg` | 1175×501 |

**Teto de peso por arte: 900 KB.** A VM tem 2 vCPU; arte pesada
atrasa a primeira dobra. Exportar JPEG qualidade 80 para fundo, SVG para vetor.

## 4 · O que exportar do Express

- **fundo/nebulosa** → JPEG, na dimensão da tabela acima;
- **ícone, selo, marca, diagrama** → **SVG** (escala sem peso e aceita cor por CSS);
- **não** exportar texto como imagem: o painel precisa do texto legível e buscável.

## 5 · Como devolver ao painel

1. salve o arquivo exportado em `docs/referencias/express/entrada/`;
2. rode `python -m tools.express_ponte --importar`;
3. cole no painel o trecho que o comando imprimir.
