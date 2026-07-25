# Handoff — estado em 25/07/2026 (sessão da noite)

**Para retomar:** *"continue pelo docs/superpowers/specs/2026-07-25-handoff-continuidade.md"*.
Branch: `feat/painel-v8-melhorias` — tudo commitado e **no remoto** (`37e763ac` → `19a62daf`).

---

## 1 · O QUE FICOU ABERTO (e o que depende de você)

### 1.1 Painel — a foto de referência (DEPENDE DE VOCÊ)

O painel foi reformulado (item 2.1) sem a foto que você mandou ao Yoda — ela nunca chegou
ao disco da VM. **Se ainda quiser aquela direção específica, anexe a foto no chat da
sessão** (aí é vista direto) ou salve em `~/JFN/docs/referencias/`. Sem ela, qualquer
tentativa de imitar a referência é chute.

### 1.2 Adobe Express — o teste de 5 minutos (DEPENDE DE VOCÊ)

Veredito apurado e documentado em **`docs/referencias/express/PASSO-A-PASSO.md`**: a API
exige entitlement de **organização** (Admin Console, product profiles com *Firefly
Creative Production for Enterprise*) — assinatura individual não habilita. A ponte que
funciona hoje, sem credencial e sem custo, está em `tools/express_ponte.py`.

**O que só você pode fazer:** entrar em `developer.adobe.com/console` → *Create new
project* → *Add API* → procurar **Adobe Express API**. Se aparecer e deixar criar
credencial `OAuth Server-to-Server`, a conta tem o entitlement e dá para automatizar
daqui. Se não aparecer, o veredito está confirmado e o caminho é o passo a passo.

### 1.3 Yoda — 413 com foto: **VERIFICADO** (falta só o teste ao vivo)

O patch (`6f222a1a2` no `hermes-agent`) sobreviveu ao auto-update das 04:00 e está em HEAD.
Testado nesta sessão com foto pesada sintética:

| | antes | depois |
|---|---|---|
| dimensão | 4000×3000 | 1568×1176 |
| arquivo | 8.568 KB | 1.229 KB (−85,7%) |
| **payload base64** (o que estourava o corpo do provedor) | **11,16 MB** | **1,60 MB** |

O original em tamanho pleno fica preservado ao lado (`img_*.orig.jpg`). Falta só você
mandar uma foto pesada no Telegram para confirmar o caminho vivo.

### 1.4 Continua na fila (do handoff anterior, sem mudança)

3. **VLM local para fotos de medição** — `foto_medicao.avaliar_fotos(descrever=…)` está
   pronto e injetável; falta subir **moondream2** ou **SmolVLM** em llama.cpp na VM-2.
4. **Consulta à SEFAZ por chave de NF-e** — `nfe_verifica.situacao(consultar=…)` pronto;
   caminho gratuito é o portal público com captcha pelo **ddddocr local** (já roda na VM-2).
5. **I.D.E.A.S** — R$ 3,56 bi pelo Fundo Estadual de Saúde (UG 296100), 124 processos SEI,
   743 OBs. Com o motor calibrado, vale o dossiê completo dedicado.
6. **Fracionamento pelo SIAFE** — 4 casos com prioridade ≥ 0,7 em 2024; o primeiro
   (4ID MÉDICOS, UG 294200) tem 12 pagamentos, 12 processos distintos, todos ≥ 80% do teto.

### 1.5 Achado NÃO tratado (decisão consciente)

`reporting.intel_base.moeda(None)` e `moeda('x')` devolvem **`0,00`** — o que **afirma que
o valor é zero**, contra a regra `INDISPONÍVEL ≠ 0`. **Não foi mexido de propósito:** a
função tem **178 chamadas** e mudar a semântica dela derrubaria os goldens em massa. Fica
registrado como dívida com raio de impacto medido. Nos 152 sítios corrigidos nesta sessão
o risco é nulo (todos já pressupunham valor numérico; hoje `f"{None:,.2f}"` levantaria
`TypeError`).

---

## 2 · O QUE FOI FEITO NESTA SESSÃO

### 2.1 Painel v12 "HOLOMESA" — 3D de verdade no núcleo (`a426ea00`)

O núcleo deixou de ser um círculo visto de frente e virou **mesa de holograma**: o
território do RJ é o **chão** (perspectiva com divisão por z), os domínios **flutuam** em
três altitudes, cada um preso ao piso por feixe vertical e pegada de luz, e no centro está
o projetor. Profundidade vem dos quatro sinais que faltavam — divisão por z, oclusão por
ordem de pintura, paralaxe do cursor, contato com um plano.

**Custo medido no próprio navegador: 0,9 ms/quadro** (p90 1,1 · teto 3) num orçamento de
16,6 ms. O piso é assado em bitmap ortogonal e deformado em faixas afins, com cache
invalidado só quando a câmera se move.

> **Armadilha de medição, para não cair de novo:** o FPS da VM é **4 mesmo com TODOS os
> canvas parados** — SwiftShader por software, 2 vCPU. FPS aqui **não** mede a experiência
> do usuário; o que mede é o ms/quadro do desenho.

**Segunda rodada do pipeline (papel 8 → papel 2).** A auditoria sobre o próprio resultado
apontou que faltavam duas coisas para deixar de parecer desenho e passar a parecer objeto:

- **o território não tinha espessura** — era um contorno deitado no tampo, e contorno
  deitado o olho lê como decalque. Virou **laje**: parede lateral até `ESP=0.045`, tampo de
  vidro fumê (que de quebra esconde a parede de trás, como deve) e a malha assada projetada
  na altura da laje. São 294 pontos de contorno, convertidos para mundo pelo inverso exato
  do mapeamento da placa. Tudo o que pousa passou a pousar **na laje**: pé do feixe, onda de
  evento, base do projetor, anéis do reator;
- **a mesa não tinha borda** — o piso só esmaecia, e sem limite físico o olho aceita como
  fundo. Ganhou **aro** com halo.

Custo depois da extrusão, em 63 quadros: **mediana 1,1 ms · p90 2,3 ms · teto 6 ms** (o p90
dobrou; segue 7× abaixo do orçamento).

> **A lição que mais vale desta rodada** — e que o commit `e3a0937c` perdeu, porque as
> crases da mensagem foram comidas pelo shell: `repinta()` chamava `draw()` **antes** da
> declaração de `_nuVisivel`, e um `let` em **zona morta temporal** derrubava a mesa inteira
> com `ReferenceError` — mas **só** em `prefers-reduced-motion`, o único caminho em que
> `repinta()` desenha. Era o defeito da mesa em branco **voltando por outra porta**.
> Moral: **reduced-motion é um caminho de código distinto e tem de ser testado a cada
> rodada** — a tela normal não o exercita.

Defeitos achados por auditoria visual e corrigidos:

| Defeito | Causa-raiz |
|---|---|
| lâmina de luz atravessando o herói | `background-clip:padding-box,border-box` com **uma** camada de imagem: a 2ª fatia não tem o que recortar e o cônico inundou o card. Correção em 3 camadas |
| mesa **em branco** em `prefers-reduced-motion` | desenho único + `canvas.width=…` no `size()` limpa o bitmap; o 1º resize apagava tudo para sempre |
| ticker **vazio** em reduced-motion | `padding-left:100%` só faz sentido com a animação que traz o texto |
| rótulos empilhados, um clipado, um cobrindo o projetor | viraram **trilho de chamada** lateral com linha-guia |
| número longo cortado na borda do chip | largura fixa; virou `min/max-width` |
| mesa esmagada em tela estreita | **regime compacto**: grade sob a cena abaixo de 720px |
| pílula de sweep cobrindo a legenda | foi para o topo |

### 2.2 R$ no padrão brasileiro — 152 lugares + trava (`70e67766`)

`f"{v:,.2f}"` produz `57,208.00`, que no Brasil se lê como **cinquenta e sete reais**.
Havia **164 linhas** montando `R$` assim. 152 trocas em 57 arquivos para o formatador
canônico da casa (`reporting.intel_base.moeda`), reusando o formatador **local** onde já
havia um. `tests/test_moeda_padrao_brasileiro.py` varre o código e **falha se voltar**.

> O `_brl` de `editais/teste_finalistico.py` é um **parser** (`str→float`): usá-lo seria
> bug, e o script de transformação o rejeita explicitamente.

**Suíte: 2.524 passando, as MESMAS 50 falhas de ambiente da VM-2** (nenhuma nova, nenhuma
sumiu), comparadas **nome a nome** — não por contagem.

### 2.3 Contraste abaixo do mínimo da casa (`37e763ac`)

Medido, não estimado: `--dim` (L=0.57) rendia **4,22–4,47:1** nos textos de 9,5–12px onde
ele vive — abaixo do 4,5:1 que a `PRODUCT.md` declara obrigatório. **L=0.60** é o menor
passo que resolve (**4,78:1**) sem encostar em `--mut` e apagar um degrau de hierarquia.
Depois: **0 violações e 0 elementos não medidos nas 9 abas**.

`tools/auditar_contraste.py` guarda o auditor. Três coisas que ele aprendeu a fazer certo,
cada uma nascida de um laudo falso que ele mesmo deu:
- resolve a cor pintando 1px num canvas (ler `oklch(0.96 0.012 230)` com regex de dígitos e
  tratá-los como RGB **inventa número**);
- compõe o fundo camada a camada até um opaco (texto rosa sobre véu de rosa a 7% dava 1,00:1);
- lê só a **primeira** camada de `background-image` e declara "não sei medir" quando não sabe.

### 2.4 O card GRAVE recuperou o que o v11 tomara dele

Duas perdas silenciosas desde o v11: o cônico **inundava** a superfície com azul/laranja
(cor que não é dele, competindo com o rosa que É o sinal), e `animation:holoSpin` da mesma
regra **sobrescreveu o `graveGlow`** — o card grave não pulsava gravidade havia uma versão
inteira. Ambos de volta.

### 2.5 Ponte do Adobe Express (`19a62daf`)

`tools/express_ponte.py`: `--spec` exporta a identidade do painel (paleta **OKLCH→HEX**,
fontes, medidas, teto de peso) e `--importar` traz de volta o que sair do Express,
validado e versionado. Conversão de cor conferida contra os cinco pontos de referência do
sRGB. Testada ponta a ponta, inclusive **recusando** arquivo com extensão mentindo.

---

## 3 · COMANDOS ÚTEIS

```bash
# suíte completa (na VM-2, deixando a VM-1 livre) — compare nome a nome com as 50 de base
./tools/testar_na_vm2.sh

# auditoria de contraste no navegador que já roda na VM (CDP 9222)
.venv/bin/python tools/auditar_contraste.py

# ponte do Express
.venv/bin/python -m tools.express_ponte --spec
.venv/bin/python -m tools.express_ponte --importar

# painel
systemctl --user restart jfn && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/painel
```

**Como auditar o painel sem chutar** (foi o que funcionou): screenshot + erros de console
pelo Chrome que já roda na VM (CDP 9222), com
`websocket.create_connection(..., suppress_origin=True)` — sem isso o Chrome recusa com 403.
Recorte de um elemento: pegue o `getBoundingClientRect()` e passe em `clip` com `scale:2`.
**Variantes que revelam defeito que a tela normal esconde:** `Emulation.setEmulatedMedia`
com `prefers-reduced-motion:reduce`, e `setDeviceMetricsOverride` a 390px.

**Regras da casa que valeram em cada passo:** OB é pagamento (empenho não); INDISPONÍVEL ≠
irregular; indício ≠ acusação; nunca dessaturar o que já brilha; e **a VM tem 2 vCPU** — um
pesado por vez.
