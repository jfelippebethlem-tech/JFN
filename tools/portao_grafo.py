# -*- coding: utf-8 -*-
"""Seleção de testes do portão pelo GRAFO DE IMPORT (O2.5 da Esteira Única).

POR QUE EXISTE. O portão antigo (`casados()` em tools/pre_push_gate.sh) escolhia testes por NOME: `test_<arquivo>*.py`
e os 6 primeiros arquivos que o `grep` devolvesse com o nome do módulo. Em 24/11 isso deixou passar duas falhas que só a
suíte completa pegou:
  · 1008786e mexeu em `reporting/inteligencia_orgao.py`; `tests/test_orgao_endereco_google.py` importa o módulo, mas o
    `grep | head -6` cortou a lista antes de chegar nele (3 testes vermelhos);
  · 00b63d5b pôs `TETO_NAO_CONFIRMADO` em `llm/memoria.py`; `test_limites_aditivo_fonte_unica` VARRE `compliance_agent/**`
    e acusou — nenhum import liga os dois, então só uma regra de "teste transversal" alcança esse caso.

O QUE ESCOLHE (a seleção é a UNIÃO):
  1. testes que dependem, TRANSITIVAMENTE, de um arquivo que o push muda. Dependência = import (absoluto, relativo,
     `from pacote import submódulo`, import dentro de função, nome solto achado por `sys.path`), mais menção literal:
     string pontilhada que é um módulo da casa (`monkeypatch.setattr("tools.x.f")`, `-m tools.x`) e string que é um
     caminho/nome de arquivo versionado (`"config/fluxo.yaml"`, `"pre_push_gate.sh"`). Importar `a.b.c` executa
     `a/__init__` e `a/b/__init__`, então depende deles também. Todo teste depende do `conftest.py` dos diretórios acima.
     Arquivos de texto de `config/` e `capabilities.yaml` entram como nós (módulo citado neles vira aresta).
  2. as catracas: `tests/test_regra_*.py`, `test_catraca_*.py`, `test_divida_*.py` e a lista CATRACAS do portão antigo
     (`tools/pre_push_gate.sh`, que segue sendo a fonte — `test_regra_registro` confere que toda catraca está lá);
  3. os testes TRANSVERSAIS: os que varrem o repositório (`glob`/`rglob`/`os.walk`/`git ls-files`/`git grep` fora do
     `tmp_path`). Não há import que os ligue ao que mudou — o caso do art. 125 acima.
  4. a suíte INTEIRA quando muda o que configura toda a coleta (pyproject, requirements, conftest raiz, pytest.ini).

O grafo é montado da ÁRVORE DO COMMIT que vai subir (`git ls-tree`/`git cat-file`), nunca da árvore de trabalho — a
árvore tem WIP de outras frentes. Cache por blob em ~/.cache/jfn-portao/grafo.json: só o blob novo é lido de novo.

    python -m tools.portao_grafo selecionar <base> <sha>      # lista os testes (um por linha)
    python -m tools.portao_grafo explicar <base> <sha>        # contagem por motivo
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

VERSAO_CACHE = 3
# Quantas arestas TARDIAS (import dentro de função etc.) um caminho teste→arquivo mudado pode ter. Medido no replay de
# 24/11 (ver o relatório da O2.5): 1 pega as duas falhas do dia sem puxar a suíte inteira por causa das cadeias tardias.
MAX_TARDIAS = int(os.environ.get("JFN_PORTAO_TARDIAS", "1"))
CACHE = Path(os.environ.get("JFN_PORTAO_CACHE", Path.home() / ".cache" / "jfn-portao" / "grafo.json"))

# Muda a coleta inteira → suíte inteira. (tests/conftest.py já cai na suíte inteira pelo grafo: todo teste depende dele.)
GATILHOS_SUITE = {"pyproject.toml", "requirements.txt", "requirements-dev.txt", "pytest.ini", "setup.cfg", "conftest.py",
                  "tests/conftest.py"}
CATRACA_RE = re.compile(r"^tests/(test_regra_|test_catraca_|test_divida_)[^/]*\.py$")
TESTE_RE = re.compile(r"^tests/(.*/)?test_[^/]*\.py$")
# texto não-Python que vira nó do grafo (citam módulos/arquivos e são lidos por código)
TEXTO_NO_RE = re.compile(r"^(config/.*\.(ya?ml|json|toml)|capabilities\.yaml)$")
_STR_OK = re.compile(r"^[\w./-]{3,200}$")
_DOTTED = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")
_TOKEN_TEXTO = re.compile(r"[A-Za-z_][\w./-]{2,200}")
_RECEPTOR_TMP = {"tmp_path", "tmpdir", "tmp", "tmp_path_factory"}
# nome de arquivo genérico demais para valer como menção (há dezenas de "manifest.json" de dado fora do repo)
_NOME_GENERICO = {"__init__.py", "conftest.py", "manifest.json", "index.html", "index.js", "README.md", "config.json",
                  "package.json", "data.json", "estado.json", "dados.json", "saida.json"}
# "compliance.db", "relatorio.pdf": parece módulo pontilhado (`compliance` existe), é nome de arquivo
_EXT_ARQ = {"db", "py", "json", "yaml", "yml", "csv", "md", "txt", "html", "js", "css", "log", "sh", "pdf", "toml",
            "xlsx", "zst", "gz", "png", "jpg", "sql", "tgz", "zip", "lock", "pid", "xml", "parquet", "duckdb", "env"}


def _git(repo: Path, *args: str, entrada: bytes | None = None) -> bytes:
    r = subprocess.run(["git", "-C", str(repo), *args], input=entrada, capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} falhou: {r.stderr.decode(errors='replace')[:300]}")
    return r.stdout


def arvore(repo: Path, sha: str) -> dict[str, tuple[str, int]]:
    """caminho → (blob, tamanho) dos arquivos versionados no commit."""
    out = _git(repo, "ls-tree", "-r", "-l", "-z", sha).decode("utf-8", errors="replace")
    res: dict[str, tuple[str, int]] = {}
    for reg in out.split("\0"):
        if not reg:
            continue
        meta, caminho = reg.split("\t", 1)
        partes = meta.split()
        if len(partes) < 4 or partes[1] != "blob":
            continue
        res[caminho] = (partes[2], int(partes[3]) if partes[3].isdigit() else 0)
    return res


def mudados(repo: Path, base: str, sha: str) -> list[str]:
    """Caminhos tocados entre base e sha; renomeação vira remoção + adição (os dois lados contam)."""
    out = _git(repo, "diff", "--name-only", "--no-renames", "-z", base, sha).decode("utf-8", errors="replace")
    return sorted(p for p in out.split("\0") if p)


def _ler_blobs(repo: Path, blobs: list[str]) -> dict[str, bytes]:
    if not blobs:
        return {}
    out = _git(repo, "cat-file", "--batch", entrada=("\n".join(blobs) + "\n").encode())
    res: dict[str, bytes] = {}
    i = 0
    for b in blobs:
        fim_cab = out.index(b"\n", i)
        cab = out[i:fim_cab].split()
        if len(cab) < 3 or cab[1] == b"missing":
            raise RuntimeError(f"blob ausente no repositório: {b}")
        n = int(cab[2])
        res[b] = out[fim_cab + 1:fim_cab + 1 + n]
        i = fim_cab + 1 + n + 1
    return res


def _varre_repo(no: ast.AST) -> bool:
    """Chamada que lista arquivos do repositório (não do tmp_path do teste)."""
    if not isinstance(no, ast.Call):
        return False
    f = no.func
    if isinstance(f, ast.Attribute) and f.attr in {"glob", "rglob", "iglob", "walk", "iterdir", "scandir"}:
        alvo = f.value
        if isinstance(alvo, ast.Name) and alvo.id in _RECEPTOR_TMP:
            return False
        if f.attr in {"iterdir", "scandir"}:
            return False   # listar UMA pasta é comum demais para marcar transversal; varredura é glob/walk
        return True
    if isinstance(f, ast.Name) and f.id in {"glob", "iglob"}:
        return True
    consts = [a.value for a in ast.walk(no) if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    return any(c in {"ls-files", "grep"} for c in consts) and "git" in consts


def _eh_fixture(fn: ast.AST) -> bool:
    for d in getattr(fn, "decorator_list", []):
        alvo = d.func if isinstance(d, ast.Call) else d
        if (isinstance(alvo, ast.Attribute) and alvo.attr == "fixture") or (isinstance(alvo, ast.Name) and alvo.id == "fixture"):
            return True
    return False


def _imports_de(no: ast.AST) -> list[list]:
    if isinstance(no, ast.Import):
        return [[0, a.name, []] for a in no.names]
    if isinstance(no, ast.ImportFrom):
        return [[no.level or 0, no.module or "", [a.name for a in no.names if a.name != "*"]]]
    return []


def extrair_py(fonte: bytes) -> dict:
    """Imports crus `[nível, módulo, nomes, tardio]` (tardio = dentro de função: só roda se a função rodar), strings
    candidatas, marca de varredura e — para o conftest — os imports de cada fixture à parte (`fix`), mais os nomes de
    argumento do arquivo (`args`: que fixtures um teste pede). Sem resolver nada: o cache é por blob."""
    try:
        arv = ast.parse(fonte)
    except (SyntaxError, ValueError):
        # arquivo que não compila: sem arestas, mas marcado — o pytest dele vai falhar e é isso que se quer ver
        return {"imp": [], "str": [], "varre": False, "invalido": True, "fix": {}, "args": []}
    fix: dict[str, list] = {}
    imps: list[list] = []
    strs: set[str] = set()
    args: set[str] = set()
    varre = False
    pilha: list[tuple[ast.AST, bool, str | None]] = [(arv, False, None)]
    while pilha:
        no, em_funcao, fixture = pilha.pop()
        for imp in _imports_de(no):
            if fixture is not None:
                fix.setdefault(fixture, []).append(imp)
            else:
                imps.append([*imp, em_funcao])
        if isinstance(no, ast.Constant) and isinstance(no.value, str):
            s = no.value.strip()
            if _STR_OK.match(s):
                strs.add(s)
        elif isinstance(no, ast.arg):
            args.add(no.arg)
        if not varre and _varre_repo(no):
            varre = True
        e_funcao = isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        if fixture is None and isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) and _eh_fixture(no):
            fixture = no.name
            fix.setdefault(fixture, [])
        for filho in ast.iter_child_nodes(no):
            pilha.append((filho, em_funcao or e_funcao, fixture))
    return {"imp": imps, "str": sorted(strs), "varre": varre, "fix": fix, "args": sorted(args)}


def extrair_texto(fonte: bytes) -> dict:
    toks = {t.strip("./-") for t in _TOKEN_TEXTO.findall(fonte.decode("utf-8", errors="replace"))}
    return {"imp": [], "str": sorted(t for t in toks if ("." in t or "/" in t) and _STR_OK.match(t)), "varre": False}


def _carregar_cache() -> dict:
    try:
        dados = json.loads(CACHE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        print(f"[portão] cache do grafo ilegível ({e}) — refazendo do zero", file=sys.stderr)
        return {}
    return dados.get("blobs", {}) if dados.get("versao") == VERSAO_CACHE else {}


def _gravar_cache(blobs: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(f".tmp{os.getpid()}")
    tmp.write_text(json.dumps({"versao": VERSAO_CACHE, "blobs": blobs}), encoding="utf-8")
    tmp.replace(CACHE)


def _modulo(caminho: str) -> str | None:
    if not caminho.endswith(".py"):
        return None
    m = caminho[:-3].replace("/", ".")
    return m[: -len(".__init__")] if m.endswith(".__init__") else m


@dataclass
class Grafo:
    """deps[a][d] = custo da aresta a→d: 0 = roda no import de `a`; 1 = TARDIA (import dentro de função, módulo citado
    por string fora de teste, módulo citado num yaml de despacho) — só roda se o caminho de código chegar lá."""
    arquivos: dict[str, tuple[str, int]]
    deps: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(dict))
    mencoes: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))    # diretas (lê o texto do .py)
    varredura: set[str] = field(default_factory=set)

    def ligar(self, a: str, alvos, custo: int) -> None:
        d = self.deps[a]
        for x in alvos:
            if x != a and custo < d.get(x, 9):
                d[x] = custo

    def reversa(self) -> dict[str, dict[str, int]]:
        rev: dict[str, dict[str, int]] = defaultdict(dict)
        for a, ds in self.deps.items():
            for d, c in ds.items():
                rev[d][a] = c
        return rev


def montar(repo: Path, sha: str, extras: list[str] = ()) -> Grafo:
    """Grafo do commit `sha`. `extras` = caminhos removidos no push: entram como nós sem conteúdo, para que o teste
    que AINDA importa um módulo apagado seja escolhido (e falhe, como deve)."""
    arq = arvore(repo, sha)
    g = Grafo(arquivos=arq)
    nos = dict(arq)
    for e in extras:
        nos.setdefault(e, ("", 0))
    mod_idx = {m: p for p in nos if (m := _modulo(p))}
    tops = {m.split(".")[0] for m in mod_idx}
    base_idx: dict[str, list[str]] = defaultdict(list)      # último componente → módulos (import solto por sys.path)
    for m in mod_idx:
        base_idx[m.rsplit(".", 1)[-1]].append(m)
    nome_idx: dict[str, list[str]] = defaultdict(list)      # nome de arquivo → caminhos
    for p in nos:
        nome_idx[p.rsplit("/", 1)[-1]].append(p)

    cache = _carregar_cache()
    alvo = {p: b for p, (b, _) in arq.items() if p.endswith(".py") or TEXTO_NO_RE.match(p)}
    faltam = sorted({b for b in alvo.values() if b not in cache})
    for i in range(0, len(faltam), 400):
        lote = faltam[i:i + 400]
        conteudo = _ler_blobs(repo, lote)
        caminho_de = {b: p for p, b in alvo.items() if b in conteudo}
        for b in lote:
            p = caminho_de[b]
            cache[b] = extrair_py(conteudo[b]) if p.endswith(".py") else extrair_texto(conteudo[b])
    if faltam:
        _gravar_cache({b: cache[b] for b in set(alvo.values())})   # poda: só o que este commit usa

    def com_prefixos(m: str) -> list[str]:
        partes = m.split(".")
        return [p for i in range(1, len(partes) + 1) if (p := mod_idx.get(".".join(partes[:i])))]

    def resolver_mod(m: str) -> list[str]:
        if m in mod_idx:
            return com_prefixos(m)
        if m.split(".")[0] in tops:      # `from a.b import f`: a.b existe, f não é módulo — o prefixo mais longo
            partes = m.split(".")
            for i in range(len(partes) - 1, 0, -1):
                if ".".join(partes[:i]) in mod_idx:
                    return com_prefixos(".".join(partes[:i]))
            return []
        # import solto (sys.path.insert da pasta tools/, por exemplo): todo módulo com esse último componente
        return [p for cand in base_idx.get(m.split(".")[0], []) for p in com_prefixos(cand)]

    def absoluto(pacote: list[str], nivel: int, mod: str) -> str:
        if not nivel:
            return mod
        raiz = pacote[: len(pacote) - (nivel - 1)] if nivel - 1 <= len(pacote) else []
        return ".".join([*raiz, mod] if mod else raiz)   # `from ..x import y`: sobe nivel-1 pacotes

    def alvos_import(pacote: list[str], nivel: int, mod: str, nomes: list[str]) -> list[str]:
        base = absoluto(pacote, nivel, mod)
        res = resolver_mod(base) if base else []
        for nome in nomes:               # `from pacote import submodulo`
            sub = f"{base}.{nome}".strip(".")
            if sub in mod_idx:
                res.extend(com_prefixos(sub))
        return res

    for p, b in alvo.items():
        info = cache[b]
        if info.get("varre"):
            g.varredura.add(p)
        e_teste = bool(TESTE_RE.match(p))
        pacote = (_modulo(p) or "").split(".")
        if not p.endswith("__init__.py"):
            pacote = pacote[:-1]
        for nivel, mod, nomes, tardio in info["imp"]:
            # import dentro de função de TESTE roda quando o teste roda: custo 0
            g.ligar(p, alvos_import(pacote, nivel, mod, nomes), 1 if tardio and not e_teste else 0)
        # Menção por CAMINHO: a .py de fora dos testes é leitura do texto (catraca que lê server.py) — pesa só se
        # o próprio arquivo mudou, não o que ele importa. Teste que cita uma .py em geral a EXECUTA (subprocess,
        # runpy) e config (yaml/json) é tabela de despacho dinâmico: essas duas seguem no grafo.
        cands: set[str] = set()
        for s in info["str"]:
            if s in nos:
                cands.add(s)
            nome = s.rsplit("/", 1)[-1]
            if nome in nome_idx and "." in nome and nome not in _NOME_GENERICO:
                c_nome = [c for c in nome_idx[nome] if "/" not in s or c.endswith(s.lstrip("./"))]
                if len(c_nome) <= 3:     # nome solto que casa com muitos arquivos não identifica nenhum
                    cands.update(c_nome)
            if _DOTTED.match(s) and s.split(".")[0] in tops and s.rsplit(".", 1)[-1] not in _EXT_ARQ:
                g.ligar(p, resolver_mod(s), 0 if e_teste else 1)
        g.ligar(p, (c for c in cands if e_teste or not c.endswith(".py")), 0)
        g.mencoes[p].update(c for c in cands if not e_teste and c.endswith(".py") and c != p)

    # todo teste depende dos conftest.py dos diretórios acima dele (e o conftest raiz, se houver): do corpo do conftest
    # sempre; dos imports de uma fixture só se o teste pede a fixture pelo nome
    confs = [c for c in arq if c.rsplit("/", 1)[-1] == "conftest.py"]
    for t in (p for p in arq if TESTE_RE.match(p)):
        pede = set(cache[arq[t][0]].get("args", ()))
        for c in confs:
            pasta = c.rsplit("/", 1)[0] + "/" if "/" in c else ""
            if not t.startswith(pasta):
                continue
            g.ligar(t, [c], 0)
            pacote_c = (_modulo(c) or "").split(".")[:-1]
            for nome_fix, imps in cache[arq[c][0]].get("fix", {}).items():
                if nome_fix in pede:
                    for nivel, mod, nomes in imps:
                        g.ligar(t, alvos_import(pacote_c, nivel, mod, nomes), 0)
    return g


def catracas_do_portao(repo: Path, sha: str, arquivos: dict) -> set[str]:
    """A lista CATRACAS de tools/pre_push_gate.sh no commit — a fonte que test_regra_registro confere."""
    if "tools/pre_push_gate.sh" not in arquivos:
        return set()
    txt = _ler_blobs(repo, [arquivos["tools/pre_push_gate.sh"][0]])[arquivos["tools/pre_push_gate.sh"][0]]
    m = re.search(r'^CATRACAS="([^"]*)"', txt.decode("utf-8", errors="replace"), re.M)
    return {t for t in (m.group(1).split() if m else []) if t in arquivos}


def alcancados(g: Grafo, mud: list[str], max_tardias: int) -> dict[str, int]:
    """Quem depende (transitivamente) do que mudou → menor nº de arestas TARDIAS no caminho. BFS 0-1 na reversa; um
    caminho com mais de `max_tardias` arestas tardias não conta (sem esse teto, a cadeia de imports dentro de função
    — cruzamentos_intel → telegram_nucleo → intel_md → … — liga quase todo teste a quase todo módulo)."""
    rev = g.reversa()
    mud_set = set(mud)
    inicio = set(mud) | {a for a, ms in g.mencoes.items() if ms & mud_set}
    melhor = dict.fromkeys(inicio, 0)
    fila = deque(sorted(inicio))
    while fila:
        n = fila.popleft()
        for a, c in rev.get(n, {}).items():
            k = melhor[n] + c
            if k <= max_tardias and k < melhor.get(a, max_tardias + 1):
                melhor[a] = k
                (fila.appendleft if c == 0 else fila.append)(a)
    return melhor


@dataclass
class Selecao:
    testes: list[str]
    motivos: dict[str, int]
    mudados: list[str]
    suite_inteira: bool = False


def selecionar(repo: Path, base: str, sha: str, max_tardias: int = MAX_TARDIAS) -> Selecao:
    repo = Path(repo)
    mud = mudados(repo, base, sha)
    arq_sha = arvore(repo, sha)
    removidos = [m for m in mud if m not in arq_sha]
    g = montar(repo, sha, extras=removidos)
    testes_todos = sorted(p for p in g.arquivos if TESTE_RE.match(p))
    motivos: dict[str, int] = {}

    if any(m in GATILHOS_SUITE for m in mud):
        return Selecao(testes_todos, {"suite_inteira": len(testes_todos)}, mud, suite_inteira=True)

    alcance = alcancados(g, mud, max_tardias)
    por_grafo = {t for t in alcance if TESTE_RE.match(t) and t in g.arquivos}
    catracas = {t for t in testes_todos if CATRACA_RE.match(t)} | catracas_do_portao(repo, sha, g.arquivos)
    transversais = {t for t in g.varredura if TESTE_RE.match(t)}
    motivos = {"grafo": len(por_grafo), "catracas": len(catracas), "transversais": len(transversais)}
    sel = sorted(por_grafo | catracas | transversais)
    if set(sel) >= set(testes_todos):
        return Selecao(testes_todos, {**motivos, "suite_inteira": len(testes_todos)}, mud, suite_inteira=True)
    return Selecao(sel, motivos, mud)


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in {"selecionar", "explicar"}:
        print(__doc__, file=sys.stderr)
        return 2
    repo = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
    s = selecionar(repo, argv[1], argv[2])
    if argv[0] == "selecionar":
        print("\n".join(s.testes))
    else:
        print(json.dumps({"mudados": len(s.mudados), "testes": len(s.testes), "motivos": s.motivos,
                          "suite_inteira": s.suite_inteira}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
