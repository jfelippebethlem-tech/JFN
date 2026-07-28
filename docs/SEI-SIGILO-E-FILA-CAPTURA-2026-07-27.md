# Processos SEI sob Restrição de Acesso e Fila de Captura
## Inventário para requisição formal

| | |
|---|---|
| **Emissão** | 27 de julho de 2026 |
| **Base** | 5.663 caches de varredura já gravados (`data/sei_cache/`), sem novo acesso ao portal |
| **Tabelas** | `sei_sigilo` (5.663 linhas) · `sei_fila_captura` (3.216 linhas) |
| **Uso** | Requerimento de informação / requisição do gabinete (CF art. 50 §2º; CERJ arts. 122-123) |

---

## 1. Por que a restrição de acesso é, ela mesma, um achado

Processo administrativo de contratação é **público**: art. 5º, XXXIII, da Constituição;
art. 7º, §3º, da Lei 12.527/2011; art. 13 da Lei 14.133/2021. A restrição de acesso a processo
de despesa exige fundamento legal expresso e é excepcional. Um processo de contratação sob
cadeado é, no mínimo, matéria de diligência — e o pedido formal não depende do portal.

## 2. O marcador de cadeado foi TESTADO antes de virar lista

A detecção existia em `sei/navegador.py` e `collectors/sei_cdp.py` desde antes, e nunca havia
sido persistida (`processos_sei.nivel_acesso` está vazio). Ao recuperá-la, a primeira hipótese
foi de que o sinal fosse artefato: o seletor inclui `[class*="restrit" i]`, que casa qualquer
elemento com "restrit" na classe, e `n_docs_restritos` vem 0 em 100% dos casos.

**Dois testes de correlação refutaram a hipótese de artefato:**

| Teste | Resultado | Leitura |
|---|---|---|
| Cadeado entre caches **sem** documentos | 76 / 339 = **22,42%** | — |
| Cadeado entre caches **com** documentos | 1 / 5.324 = **0,02%** | mil vezes de diferença; artefato de CSS apareceria igual nos dois grupos |
| Distribuição por órgão | 20 UGs, taxas de 1,3% a 28,6% | não é template de um órgão (seria ~100% dentro dele) |

> A assinatura canônica de sigilo é **árvore reportou carregamento + zero documentos visíveis +
> cadeado presente**. Os 263 caches com zero documentos e **sem** cadeado formam o grupo de
> falha técnica / processo vazio e ficam **fora** desta lista.

## 3. Números

| Medida | Valor |
|---|---:|
| Caches inventariados | 5.663 |
| **Processos com marcador de restrição** | **77** |
| Caches com o campo `arvore_carregou` em branco (ver §3.1) | 2.579 |
| Processos conhecidos pelo pipeline e sem texto capturado | 3.216 |

> **Não é possível quantificar a exposição financeira desta fila:** `sei_arvore.total_pago`
> está preenchido em apenas 6 dos 3.216 processos (R$ 5.356.912,08). O valor real é
> INDISPONÍVEL, não zero.

### 3.1 Correção — os "2.579 com árvore não carregada" não eram falha

**CORRIGIDO em 28/07:** este número era um ALARME FALSO meu. `arvore_carregou` só é preenchido pelo caminho de leitura normal; o caminho `cracked` lê direto e deixa o campo no default `False`. Dos caches com o campo False, **200 de 200 amostrados eram `via='cracked'` e TINHAM documentos** — leitura bem-sucedida. A investigação seguinte produziu um segundo alarme falso pela mesma causa ("falha de captcha em massa": `captcha_resolvido` também nasce `False`). É o erro que a casa combate — INDISPONÍVEL ≠ 0 — cometido do nosso lado. O inventário agora distingue *não carregou* de *não aferível*.

O que **permanece verdadeiro** e não muda: os 77 processos com marcador de restrição (a correlação de 22,42% × 0,02% foi medida sobre o cadeado, não sobre este campo) e a fila de 3.216 processos conhecidos e sem texto capturado.

## 4. Lista completa — processos sob restrição de acesso

Ordem por órgão e número. `texto local` indica se conseguimos capturar algum conteúdo.

| # | Processo SEI | Docs visíveis | Docs restritos | Texto local |
|--:|---|--:|--:|---|
| 1 | `SEI-030001/061883/2024` | 0 | 0 | **não** |
| 2 | `SEI-070002/014667/2026` | 0 | 0 | **não** |
| 3 | `SEI-080001/000435/2024` | 0 | 0 | **não** |
| 4 | `SEI-080001/001852/2022` | 0 | 0 | **não** |
| 5 | `SEI-080001/003115/2022` | 0 | 0 | **não** |
| 6 | `SEI-080001/007279/2026` | 0 | 0 | **não** |
| 7 | `SEI-080001/019841/2025` | 0 | 0 | **não** |
| 8 | `SEI-080001/020174/2023` | 0 | 0 | **não** |
| 9 | `SEI-080001/022887/2021` | 0 | 0 | **não** |
| 10 | `SEI-080001/024104/2020` | 0 | 0 | **não** |
| 11 | `SEI-080001/024360/2024` | 0 | 0 | **não** |
| 12 | `SEI-080001/024975/2022` | 0 | 0 | **não** |
| 13 | `SEI-080001/026133/2022` | 0 | 0 | **não** |
| 14 | `SEI-080002/002830/2024` | 0 | 0 | **não** |
| 15 | `SEI-080002/005629/2026` | 0 | 0 | **não** |
| 16 | `SEI-080002/011406/2024` | 0 | 0 | **não** |
| 17 | `SEI-080002/011908/2026` | 0 | 0 | **não** |
| 18 | `SEI-080002/011929/2024` | 0 | 0 | **não** |
| 19 | `SEI-080002/012090/2026` | 0 | 0 | **não** |
| 20 | `SEI-080002/012145/2026` | 0 | 0 | **não** |
| 21 | `SEI-080002/012315/2026` | 0 | 0 | **não** |
| 22 | `SEI-080002/013304/2024` | 0 | 0 | **não** |
| 23 | `SEI-080002/013670/2026` | 0 | 0 | **não** |
| 24 | `SEI-080002/014931/2024` | 0 | 0 | **não** |
| 25 | `SEI-080002/015673/2024` | 0 | 0 | **não** |
| 26 | `SEI-080002/016641/2024` | 0 | 0 | **não** |
| 27 | `SEI-080002/017289/2024` | 0 | 0 | **não** |
| 28 | `SEI-080002/018782/2024` | 0 | 0 | **não** |
| 29 | `SEI-080002/019766/2025` | 0 | 0 | **não** |
| 30 | `SEI-080002/028466/2025` | 0 | 0 | **não** |
| 31 | `SEI-080002/028757/2025` | 0 | 0 | **não** |
| 32 | `SEI-080005/000468/2021` | 0 | 0 | **não** |
| 33 | `SEI-120001/001338/2026` | 0 | 0 | **não** |
| 34 | `SEI-150001/006387/2026` | 0 | 0 | **não** |
| 35 | `SEI-260006/039851/2024` | 0 | 0 | **não** |
| 36 | `SEI-260007/19242/2024` | 0 | 0 | **não** |
| 37 | `SEI-270001/000467/2025` | 0 | 0 | **não** |
| 38 | `SEI-270006/001945/2025` | 0 | 0 | **não** |
| 39 | `SEI-270006/005483/2025` | 0 | 0 | **não** |
| 40 | `SEI-270006/005928/2024` | 0 | 0 | **não** |
| 41 | `SEI-270006/006427/2028` | 0 | 0 | **não** |
| 42 | `SEI-270006/009627/2025` | 0 | 0 | **não** |
| 43 | `SEI-270006/015302/2025` | 0 | 0 | **não** |
| 44 | `SEI-270006/017500/2025` | 0 | 0 | **não** |
| 45 | `SEI-270006/017507/2025` | 0 | 0 | **não** |
| 46 | `SEI-270006/020569/2024` | 0 | 0 | **não** |
| 47 | `SEI-270006/029577/2024` | 0 | 0 | **não** |
| 48 | `SEI-270006/032688/2024` | 0 | 0 | **não** |
| 49 | `SEI-270006/036795/2025` | 0 | 0 | **não** |
| 50 | `SEI-270006/042111/2025` | 0 | 0 | **não** |
| 51 | `SEI-270007/013813/2025` | 0 | 0 | **não** |
| 52 | `SEI-270007/021032/2024` | 0 | 0 | **não** |
| 53 | `SEI-270007/021963/2024` | 0 | 0 | **não** |
| 54 | `SEI-270007/023965/2025` | 0 | 0 | **não** |
| 55 | `SEI-270007/028177/2024` | 0 | 0 | **não** |
| 56 | `SEI-270007/037398/2025` | 0 | 0 | **não** |
| 57 | `SEI-270007/045606/2025` | 0 | 0 | **não** |
| 58 | `SEI-270007/051909/2025` | 0 | 0 | **não** |
| 59 | `SEI-270013/000042/2024` | 0 | 0 | **não** |
| 60 | `SEI-270042/000443/2021` | 0 | 0 | **não** |
| 61 | `SEI-270078/000457/2023` | 0 | 0 | **não** |
| 62 | `SEI-270099/000062/2022` | 0 | 0 | **não** |
| 63 | `SEI-270128/000002/2022` | 0 | 0 | **não** |
| 64 | `SEI-330005/000161/2026` | 15 | 0 | **não** |
| 65 | `SEI-330005/000261/2025` | 0 | 0 | **não** |
| 66 | `SEI-330005/000442/2026` | 0 | 0 | **não** |
| 67 | `SEI-330005/000443/2026` | 0 | 0 | **não** |
| 68 | `SEI-330005/000506/2026` | 0 | 0 | **não** |
| 69 | `SEI-330005/000585/2026` | 0 | 0 | **não** |
| 70 | `SEI-330005/000820/2024` | 0 | 0 | **não** |
| 71 | `SEI-330020/000019/2023` | 0 | 0 | **não** |
| 72 | `SEI-330020/000288/2021` | 0 | 0 | **não** |
| 73 | `SEI-330020/000568/2023` | 0 | 0 | **não** |
| 74 | `SEI-330020/001178/2023` | 0 | 0 | **não** |
| 75 | `SEI-330020/001179/2022` | 0 | 0 | **não** |
| 76 | `SEI-330020/001313/2021` | 0 | 0 | **não** |
| 77 | `SEI-510001/001291/2025` | 0 | 0 | **não** |

## 5. Encaminhamento sugerido

1. Requisitar os processos da lista acima, pedindo **o fundamento legal da restrição** em cada
   caso (a exceção precisa ser motivada — Lei 12.527/2011, art. 7º, §3º).
2. Para os 3.216 conhecidos e não capturados, pedir a íntegra por lote, por órgão.
3. Corrigir a causa dos 2.579 caches com árvore não carregada — é falha nossa de captura, não
   restrição do órgão, e hoje se confunde com "processo com poucos documentos".
