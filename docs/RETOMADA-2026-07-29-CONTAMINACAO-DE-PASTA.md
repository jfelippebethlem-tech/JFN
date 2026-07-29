# Documentos de OUTRO processo dentro da pasta — achado, causa e conserto

> Escrito em 2026-07-29. **Resolvido na mesma sessão**, mas fica registrado porque a extensão
> ainda não foi corrigida no acervo já arquivado e porque as réguas que FALHARAM ensinam mais
> que o achado.

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

## 4. Extensão medida — e o denominador que quase me enganou

    manifests de íntegra ......................... 352
      avaliáveis (formato novo COM `contexto`) ... 103
        contaminados .............................   7   (7% dos avaliáveis)
        documentos alheios .......................  219
      NÃO avaliáveis ............................. 249   (201 sem `contexto`, 48 formato antigo)

Dividir 7 por 352 daria "2%", que é INDISPONÍVEL entrando na conta como se fosse limpo. Pior
caso: `260007/019598/2024`, com **1 documento próprio e 37 alheios**.

**PENDENTE para a próxima sessão:** o conserto vale para arquivamentos NOVOS. As 7 pastas já
contaminadas seguem como estão — rearquivar a partir da íntegra as resolve, e os 249 não
avaliáveis precisam de outra régua (ou de recaptura, que regrava o manifest no formato novo).

## 5. As três réguas que FALHARAM (não repetir)

| régua | por que falhou |
|---|---|
| contar documentos que citam outro número de processo | citação cruzada é legítima ("conforme processo X") — deu 5 de 120 sem distinguir referência de contaminação |
| comparar o ÓRGÃO no cabeçalho do SEI | o cabeçalho do SIAFE é `Governo do Estado do Rio de Janeiro / Nota de Empenho` — a regex leu o TIPO como órgão e acusou **67 de 120 falsos** |
| `grep -B 3` para ligar achado a certame (mesma sessão) | associava o achado ao bloco ANTERIOR do log; corrigido por parse sequencial |

O padrão das três: eu inventava um sinal indireto em vez de perguntar ao dado que já existia. A
régua que funcionou não deduziu nada — leu o campo em que o próprio SEI escreve o dono do
documento.
