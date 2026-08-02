# Artefatos INERTES do painel — histórico, não código vivo

Estes arquivos **não têm efeito nenhum** no painel. Estão aqui para consulta histórica e porque a
casa manda mencionar código morto pré-existente em vez de apagá-lo.

## `v15_layer.css` … `v22.css`
Camadas de estilo que foram, uma a uma, **mescladas para dentro** do painel. Verificado por
casamento de seletor (`#kyber` do v17 aparece 25× no painel; os `@font-face` do v20/v22, 9×).
**Editar qualquer um deles não muda um pixel** — desde o v49 o CSS vivo é `static/css/painel.css`.

## `painel.antes-v15layer.html` · `painel.antes-v16.html` · `painel.antes-v23.html` · `painel.antes-v27.html`
Fotografias do monolito antes de cada salto de versão. O painel atual é o v49 e já não é monolito:
`static/jfn-painel.html` (~3 KB de casca) + `static/css/painel.css` + `static/js/painel.js`.

## O que FOI removido, e a prova
`static/jfn-painel.html.bak-v15` era **byte a byte idêntico** a `painel.antes-v15layer.html`:

    sha256 = e6ac0b34856ef6ea4afcc20485cf528c26bc4e065ebfd46cec3767ea6286a09a  (os dois)

Duplicata exata provada, cópia sobrevivente nomeada — a única condição sob a qual algo é removido
nesta faxina. Todo o resto foi comprimido ou movido, nunca descartado.
