# Documentos de OUTRO processo dentro da pasta — achado, causa e conserto

> Escrito em 2026-07-29 e **fechado no mesmo dia**: o conserto vale para arquivamentos novos
> (§3) E o acervo já contaminado foi limpo (§6). Fica registrado porque as réguas que FALHARAM
> (§5) ensinam mais que o achado, e porque a medição da extensão teve de ser refeita (§4).

## 1. O achado

`data/sei_arquivo/080001_000744_2024/` — R$ 51,6 milhões, repasse do Fundo Estadual de Saúde
(UG 296100) para nove Fundos Municipais (Itaperuna, Iguaba Grande, Volta Redonda, Duque de
Caxias, Petrópolis, Teresópolis, Três Rios, Macaé, Cabo Frio).

Apareceu ao LER o dossiê que a releitura acabara de produzir: assinaturas de **merendeira,
Subtenente PM, Cabo PM, Vice-Diretora do ILE/UERJ e Procurador da UERJ**, e um despacho da
Secretaria de **Educação** sobre controle de frequência de um colégio estadual.

## 2. A causa, rastreada

    cache CDP (a leitura da árvore) ..... 10 documentos — TODOS do processo
    pasta arquivada ..................... 35 documentos
    manifest da íntegra ................. 37, e o campo `contexto` diz de quem é cada um

**A captura estava certa. O ARQUIVAMENTO juntou peças de 22 outros processos numa pasta só** —
e o dado para separar já estava no manifest, sem uso: `"Recursos Humanos: Controle de Frequência
Nº SEI-030001/006436/2026"`.

O dano: o dossiê atribui fatos e RESPONSÁVEIS a um processo que não é o deles, e
`agente_processo` — que responde "quem responde por este processo" — herda o erro.

## 3. O conserto (já em produção)

`compliance_agent/sei/documentos_alheios.py` (`numero_do_contexto`, `separar_alheios`), ligado
em `tools/sei_arquivar.py`: peça de outro processo não vira texto nem entra no manifest, e o
log diz **de qual** processo ela era, para o conserto ser possível.

**Regra que não pode ser invertida:** documento SEM número no contexto **fica**. Ausência de
dado não prova que a peça é alheia; descartá-la trocaria contaminação por perda silenciosa.

## 4. Extensão medida — e o denominador que quase me enganou (duas vezes)

    manifests de íntegra ......................... 352
      avaliáveis (formato novo COM `contexto`) ...  70
        contaminados .............................   7   (10% dos avaliáveis)
      NÃO avaliáveis ............................. 282   (201 sem `contexto`, 81 sem lista útil)

Dividir 7 por 352 daria "2%", que é INDISPONÍVEL entrando na conta como se fosse limpo.

**A primeira medição também errou o denominador, para o outro lado.** Ela publicou 103
avaliáveis; a recontagem, feita ao aplicar o conserto, achou **70** — e a taxa de contaminação
não é 7%, é **10%**. A diferença vem do critério de "avaliável": um manifest com o campo
`contexto` presente mas VAZIO em todos os documentos não é avaliável, e entrava na conta como se
fosse. É o mesmo erro do parágrafo acima em escala menor, e passou porque só o denominador foi
conferido, nunca o critério que o produz.

Pior caso: `260007/019598/2024`, com **1 documento próprio e 35 alheios** na pasta arquivada.

## 5. As três réguas que FALHARAM (não repetir)

| régua | por que falhou |
|---|---|
| contar documentos que citam outro número de processo | citação cruzada é legítima ("conforme processo X") — deu 5 de 120 sem distinguir referência de contaminação |
| comparar o ÓRGÃO no cabeçalho do SEI | o cabeçalho do SIAFE é `Governo do Estado do Rio de Janeiro / Nota de Empenho` — a regex leu o TIPO como órgão e acusou **67 de 120 falsos** |
| `grep -B 3` para ligar achado a certame (mesma sessão) | associava o achado ao bloco ANTERIOR do log; corrigido por parse sequencial |

O padrão das três: eu inventava um sinal indireto em vez de perguntar ao dado que já existia. A
régua que funcionou não deduziu nada — leu o campo em que o próprio SEI escreve o dono do
documento.


## 6. O acervo já contaminado — resolvido em 2026-07-29

`tools/sei_descontaminar.py` fechou a pendência. **210 documentos alheios saíram de 7 pastas:**

| processo | ficam | removidos |
|---|---:|---:|
| `080001_015873_2024` | 46 | 56 |
| `080001_021045_2023` | 12 | 51 |
| `260007_019598_2024` |  1 | 35 |
| `080001_000744_2024` | 13 | 22 |
| `260006_053620_2025` | 13 | 22 |
| `260006_057654_2025` |  1 | 12 |
| `260007_015650_2025` |  1 | 12 |

**A chave de junção não é o título.** O manifest arquivado normaliza o texto ("programa o de
desembolso") enquanto a íntegra guarda "Programação de Desembolso" — casar por texto erraria. O
que liga com segurança é o **prefixo numérico do arquivo de texto** (`000_….txt` ↔ índice 0 da
íntegra), e isso foi verificado em **35 de 35** documentos antes de qualquer escrita. Documento
sem esse prefixo não é decidido: fica.

**Nada foi apagado.** As peças vão para `_alheios/` dentro da própria pasta, com `_indice.json`
dizendo de qual processo cada uma veio — é o que permite devolvê-las ao lugar certo. O manifest
anterior fica em `manifest.json.antes-descontaminar`, e o novo declara o que foi removido e como
reverter. Rodar duas vezes não sobrescreve o backup original.

A régua do §3 continua valendo aqui e é a mais importante: **documento sem número no `contexto`
FICA**. Nas sete pastas foram 17 documentos nessa situação, todos preservados.

**O que segue pendente, e agora com o número certo:** os 282 manifests não avaliáveis. Não são
"limpos" — são não observados, e só a recaptura (que regrava o manifest no formato com
`contexto`) muda isso. Enquanto não vier, nenhuma afirmação sobre a integridade dessas pastas se
sustenta.
