# Adobe Express × JFN — o que dá, o que não dá, e o passo a passo

*Apurado em 25/07/2026 na documentação oficial da Adobe.*

> ## ⚠️ ATUALIZAÇÃO (25/07/2026, mesma noite) — existe caminho por MCP
>
> O dono conectou o **"Adobe for creativity"**, servidor MCP remoto **oficial** da Adobe
> (`https://adobe-creativity.adobe.io/mcp`, transporte HTTP streamable, OAuth no primeiro
> uso). Verificado por `claude mcp list`: **✔ Connected**. Ele liga Photoshop, Lightroom,
> Illustrator, Firefly, Premiere, **Express**, InDesign e Stock.
>
> Isso **supera o veredito da seção 1** para quem usa um cliente MCP: não é preciso
> entitlement de organização no Admin Console para operar por aqui — a autorização é a do
> próprio usuário, por OAuth. A seção 1 continua valendo para a **Express API REST**
> (aquela sim é empresarial), que é coisa diferente.
>
> **Como usar:** as ferramentas de um MCP entram no conjunto do assistente no **início da
> sessão**. Se o servidor foi conectado com a sessão já aberta, rode `/clear` ou abra uma
> nova — aí elas aparecem. Conferir com `claude mcp list`.
>
> A ponte local (`tools/express_ponte.py`) **continua valendo e não depende de nada**:
> `--spec` (identidade do painel em HEX), `--gerar` (arte na marca, grátis) e `--importar`
> (validação + versionamento). Use o MCP quando quiser o Express/Firefly de verdade;
> use a ponte quando quiser arte de fundo em 2 s sem gastar crédito.

---

## 1 · O veredito, sem rodeio

A **Adobe Express API** existe e faz o que se esperaria (gerar variações e exportações de
um documento por chamada REST), mas a documentação de credenciais é explícita sobre quem
pode criá-las:

> *"Product profiles must include **Adobe Express**, **Adobe Firefly Services** and
> non-Premium Fonts access. A **Default Free Membership** and **Firefly Creative
> Production for Enterprise** configurations will suffice."*
> — [Create Credentials — Express API](https://developer.adobe.com/firefly-services/docs/express-api/getting-started/create-credentials/)

Três coisas nessa frase decidem o caso:

| Sinal | O que significa |
|---|---|
| *"for admins creating a client ID for their **teams**"* | o fluxo é de **Admin Console**, não de conta individual |
| **product profiles** | perfis são atribuídos por um **administrador de organização** |
| **Firefly Creative Production for Enterprise** | entitlement **empresarial**, e a doc da API vive sob `/firefly-services/` |

**Conclusão honesta:** uma assinatura **individual** do Adobe Express **não** habilita a
API. O caminho por API é empresarial e pago — e coisa paga está vetada aqui desde 24/07.

**O que também não serve:**
- **Add-on SDK** — roda *dentro* do Express, no navegador. Não chama de servidor.
- **Embed SDK** — embute o editor numa página, mas ainda exige API key do Developer
  Console (mesma porta).
- **Firefly Services** — plataforma empresarial, paga.

> Ainda assim, o teste de 5 minutos do item 3 vale: é ele que transforma "a doc diz que é
> empresarial" em "a **sua** conta tem ou não tem". Documentação erra; console não.

---

## 2 · O que foi construído no lugar (e já funciona)

`tools/express_ponte.py` — uma ponte de mão dupla, **zero credencial, zero custo**:

| Comando | O que faz |
|---|---|
| `--spec` | exporta a identidade do painel para um documento que se usa no Express: paleta **convertida de OKLCH para HEX**, fontes, medidas exatas das artes e o teto de peso |
| `--importar` | pega o que você exportou do Express, valida (imagem real? SVG real?), copia para `static/assets/express/`, versiona num manifesto e imprime o trecho pronto de HTML/CSS |

O elo que faltava era a cor: a paleta da casa é toda **OKLCH** e o Express só aceita
**HEX**. A conversão é feita na fonte, a partir do próprio `jfn-painel.html`, para não
existirem duas verdades de cor. Ela foi conferida contra os cinco pontos de referência do
sRGB (branco, preto, vermelho, verde e azul puros) — bate exato.

---

## 3 · Passo a passo — o que você faz

### Passo 0 · O teste que decide o caminho (5 minutos, faça primeiro)

1. entre em **`developer.adobe.com/console`** com a conta da sua assinatura;
2. **Create new project** → **Add API**;
3. procure **Adobe Express API** na lista.

- **Aparece e deixa criar credencial `OAuth Server-to-Server`** → sua conta tem o
  entitlement. Me avise: dá para automatizar daqui, e eu ligo a ponte na API.
- **Não aparece, ou pede perfil de produto que você não tem** → confirmado o veredito do
  item 1. Siga do Passo 1 em diante; é o caminho que funciona hoje.

### Passo 1 · Pegar a identidade do painel

```bash
cd ~/JFN && .venv/bin/python -m tools.express_ponte --spec
```

Gera `docs/referencias/express/ESPECIFICACAO.md`, com a paleta já em HEX:

| Token | HEX | Papel |
|---|---|---|
| `--ion` | `#59A3FF` | azul — console: estrutura, interação |
| `--flame` | `#FF8804` | laranja — energia: ação, dinheiro |
| `--flame-hi` | `#FFBF5C` | laranja claro — número de dinheiro |
| `--rose` | `#FF5472` | rosa — severidade crítica |
| `--green` | `#61DA92` | verde — conforme |
| `--bg` | `#010410` | fundo da página |

### Passo 2 · Ensinar a marca ao Express (uma vez só)

No Adobe Express: **Marca → Cores da marca → Adicionar** e cole os HEX acima.
Em **Fontes da marca**, escolha **IBM Plex Sans** e **IBM Plex Mono** (as duas são
gratuitas e estão na biblioteca dele).

Daí em diante tudo que você criar já nasce na paleta certa.

### Passo 3 · Criar a arte

Use as medidas da tabela do `ESPECIFICACAO.md` (elas vêm dos arquivos que o painel já
consome, não de chute). Regras que valem no Express:

- **fundo / nebulosa** → JPEG, qualidade 80;
- **ícone, selo, marca, diagrama** → **SVG** (escala sem peso e aceita cor por CSS);
- **não** exporte texto como imagem — o painel precisa dele legível e buscável;
- **teto de 900 KB por arte**. A VM tem 2 vCPU: arte pesada atrasa a primeira dobra.

### Passo 4 · Devolver para o painel

1. salve o arquivo exportado em `~/JFN/docs/referencias/express/entrada/`;
2. rode:

```bash
cd ~/JFN && .venv/bin/python -m tools.express_ponte --importar
```

O comando valida, copia para `static/assets/express/`, registra no manifesto e imprime o
trecho pronto — por exemplo:

```
selo-controle.svg  vetor  14 KB
    HTML:  <img src="/static/assets/express/selo-controle.svg" alt="" width="…" height="…">
```

3. me diga qual arte entrou e onde ela deve aparecer — eu integro no painel.

### Passo 5 · Quando a paleta mudar

Rode `--spec` de novo e atualize as cores da marca no Express. O documento se refaz a
partir do `jfn-painel.html`; **não edite o `ESPECIFICACAO.md` à mão**.

---

## 4 · Se você quiser mesmo a via API

Só há um caminho legítimo, e ele custa: contratar **Firefly Services / Creative Production
for Enterprise**, virar administrador de uma organização no Admin Console e atribuir os
product profiles. Aí a ponte passa a falar com a API em vez de com a pasta de entrada — a
mudança do nosso lado é pequena, porque a especificação de design e o manifesto já existem.
Enquanto isso não acontecer, **não vale ficar tentando**: o erro que se recebe é de escopo
inválido, e ele não é contornável por chave pessoal.
