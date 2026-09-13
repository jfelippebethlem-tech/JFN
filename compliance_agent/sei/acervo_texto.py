# -*- coding: utf-8 -*-
"""Porta única para o TEXTO que o acervo guarda — separando o que o SEI serviu do que nós escrevemos.

Todo `data/sei_arquivo/<processo>/texto/NNN_*.txt` começa com uma ETIQUETA nossa:

    [Parecer 462 (74886257)] (fase: controle · tipo: parecer_juridico)

    Governo do Estado do Rio de Janeiro …

Ela existe por um bom motivo — o `.txt` fica autodescritivo e a `conferencia_captura` a usa para
saber QUAL documento é aquele quando o manifesto foi reconstruído do nome do arquivo. O custo só
apareceu ao ler os disparos dos detectores (2026-08-03):

  • **O documento passava a provar a si mesmo.** A palavra `parecer_juridico` fica DENTRO do
    texto, então o regex que pergunta "isto é manifestação jurídica?" recebe de volta a etiqueta
    que se queria conferir. Foi assim que o "Parecer de Análise para Emissão DL" — corpo inteiro
    *"Procedida a Revisão do processo"*, assinado por um Coordenador de Qualidade — passou por
    parecer. O mesmo documento já custara 71 falsos positivos ao `G3`.
  • **A etiqueta come a janela.** Mediana de 71 caracteres, p90 de 119 e **máximo medido de 478**:
    quem lê `texto[:200]` perde 36,5% da janela para o próprio rótulo, e um caso extremo apaga
    uma janela de 400 inteira.
  • **O rótulo vaza para a IA.** `doc_juizo` manda o documento para a LLM julgar e mandava junto
    a NOSSA classificação — a IA via o palpite da casa antes de opinar.

**A regra:** só o que a FONTE serviu prova algo sobre a fonte. Quem quer o rótulo pede
`etiqueta()`; todo o resto recebe `sem_etiqueta()`, que é o padrão de `ler()`.

Cuidado que custou uma medição: **nem todo `[` no começo é etiqueta.** Documentos reais começam
com colchete (`[RECEBEMOS DE PROMEFARMA MEDIC. …` de uma nota fiscal) e títulos reais têm colchete
DENTRO (`[Anexo 7 - Pesquisa_de_Satisfação-[SES_RJ] (80815818)]`). Por isso a âncora é o
PARÊNTESE que só nós escrevemos — `(fase: …)` ou `(tipo: …)` — e o casamento do título é guloso
até o último `]` da linha.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

# A etiqueta canônica: `[<título>] (fase: X · tipo: Y)` (de `sei_arquivar`) ou `[<título>]
# (tipo: Y)` (de `sei_arquivar_do_cache`). O `.*` é guloso e NÃO cruza linha: pega o último `]`
# da primeira linha, o que resolve título com colchete aninhado.
_RE_ETIQUETA = re.compile(r"\A\[.*\]\s*\((?:fase|tipo):[^)\n]*\)[ \t]*\r?\n?")
# Segunda etiqueta, sem parêntese, que o escritor de PDF da íntegra deixa
# (`sei/pdf_texto.escrever_texto` grava `[titulo]\n\n{texto}`) e que sobrevive à re-extração:
# 856 documentos em 58 processos do acervo. Só se remove quando bate com o título conhecido —
# sem essa prova, um `[RECEBEMOS DE …]` de nota fiscal seria confundido com rótulo.
_RE_ETIQUETA_NUA = re.compile(r"\A\[(.*)\][ \t]*\r?\n")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").casefold())
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip()


def etiqueta(texto: str) -> str:
    """A linha de rótulo que o ARQUIVO escreveu, ou "" se o texto não a tem.

    É o que a `conferencia_captura` precisa: quando o manifesto foi reconstruído a partir do nome
    do arquivo, o título perde o número do documento e só a etiqueta ainda o carrega.
    """
    m = _RE_ETIQUETA.match(texto or "")
    return m.group(0).strip() if m else ""


def sem_etiqueta(texto: str, titulo: str = "") -> str:
    """O texto que o SEI serviu — sem nenhum rótulo nosso pela frente.

    `titulo` é opcional e serve para a segunda etiqueta (a nua, sem parêntese): só se remove um
    `[X]` solitário quando `X` é reconhecidamente o título do documento.
    """
    t = _RE_ETIQUETA.sub("", texto or "", count=1).lstrip("\n")
    if titulo:
        m = _RE_ETIQUETA_NUA.match(t)
        if m and _norm(m.group(1)) and _norm(m.group(1)) in _norm(titulo):
            t = t[m.end():].lstrip("\n")
    return t


# Piso de teor herdado de `sei_integra_fila._arquivado_ok`: abaixo disto o arquivo não carrega
# documento, carrega resíduo. A casa já usava 40 no manifesto; aqui o mesmo número vale no disco.
MIN_CHARS_CONTEUDO = 40
# Maior etiqueta medida no acervo tem 478 caracteres. Arquivo acima deste tamanho tem conteúdo
# por construção e não precisa ser aberto — poupa I/O em varredura de 45 mil arquivos.
_TAMANHO_SEGURO = 600


def tem_conteudo(caminho: Path | str, minimo: int = MIN_CHARS_CONTEUDO) -> bool:
    """O arquivo tem TEXTO DO DOCUMENTO, ou só a etiqueta que nós escrevemos?

    Medido em 2026-08-03: **10.332 dos 45.161 arquivos do acervo (22,9%) contêm apenas a
    etiqueta** — zero conteúdo — em 257 processos. Existir `.txt` nunca provou captura; é a mesma
    lição dos ~11.9k documentos que o escritor mudo deixou em branco (2026-07-23).
    """
    p = Path(caminho)
    try:
        if p.stat().st_size > _TAMANHO_SEGURO:
            return True
        return len(sem_etiqueta(p.read_text(encoding="utf-8", errors="ignore")).strip()) >= minimo
    except OSError:
        return False


def arquivos_declarados(pasta: Path | str) -> list[Path]:
    """Os `.txt` que o MANIFESTO aponta — e só eles.

    Varrer `texto/*.txt` lê também o que sobrou de capturas anteriores: medido em 2026-08-03,
    **6.286 arquivos órfãos em 121 processos**, de um esquema de nome antigo (070002/000991/2022
    tem 486 documentos no manifesto e 1.072 arquivos na pasta). Quem varre o diretório mistura
    duas capturas do mesmo processo e conta cada documento duas vezes. O manifesto é o índice.
    """
    import json

    p = Path(pasta)
    mf = p / "manifest.json"
    if not mf.exists():
        return sorted((p / "texto").glob("*.txt")) if (p / "texto").is_dir() else []
    try:
        man = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return sorted((p / "texto").glob("*.txt")) if (p / "texto").is_dir() else []
    declarados = man.get("docs") or []
    if not declarados:
        # Índice QUEBRADO, não índice vazio: existe processo com `docs: []` no manifesto e
        # `texto/*.txt` intacto no disco — é a mesma avaria que `tools/sei_reparar_manifestos`
        # conserta (num caso, 210 documentos). Devolver [] aqui apagaria documentos reais da
        # leitura em silêncio; sem índice utilizável, o diretório é a melhor evidência que há.
        return sorted((p / "texto").glob("*.txt")) if (p / "texto").is_dir() else []
    fora = []
    for d in declarados:
        rel = (d or {}).get("texto") if isinstance(d, dict) else None
        if rel and (p / rel).exists():
            fora.append(p / rel)
    return fora


def orfaos(pasta: Path | str) -> list[Path]:
    """`.txt` na pasta que NENHUM documento do manifesto reivindica — sobra de captura anterior."""
    p = Path(pasta)
    td = p / "texto"
    if not td.is_dir() or not (p / "manifest.json").exists():
        return []
    declarados = {f.resolve() for f in arquivos_declarados(p)}
    return sorted(f for f in td.glob("*.txt") if f.resolve() not in declarados)


def docs_com_conteudo(pasta: Path | str) -> int:
    """Quantos documentos DECLARADOS têm texto de verdade em disco (não só etiqueta, não órfão)."""
    return sum(1 for f in arquivos_declarados(pasta) if tem_conteudo(f))


def etiqueta_de(pasta: Path | str, doc: dict) -> str:
    """A etiqueta do documento no acervo, lendo só a 1ª linha do arquivo (sem carregar o resto)."""
    rel = (doc or {}).get("texto")
    if not rel:
        return ""
    try:
        with (Path(pasta) / rel).open(encoding="utf-8", errors="ignore") as f:
            return etiqueta(f.readline())
    except OSError:
        return ""


def ler(pasta: Path | str, doc: dict, teto: int | None = None) -> str:
    """Texto do documento no acervo, JÁ sem a etiqueta. Padrão correto: ninguém precisa lembrar.

    Devolve "" quando o documento não tem texto em disco — INDISPONÍVEL ≠ vazio é decisão de quem
    chama, e aqui a ausência não vira conteúdo.
    """
    rel = (doc or {}).get("texto")
    if not rel:
        return ""
    p = Path(pasta) / rel
    try:
        bruto = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    limpo = sem_etiqueta(bruto, str(doc.get("titulo") or doc.get("ref") or ""))
    return limpo if teto is None else limpo[:teto]
