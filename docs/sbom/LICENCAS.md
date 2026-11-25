# Licenças das dependências Python (SBOM)

> Gerado por `tools/sbom_python.py` a partir de `docs/sbom/sbom-python.cdx.json` (CycloneDX 1.6). Não editar à mão.

## 1. Escopo

- **182 componentes** instalados num venv novo, montado só de `requirements-dev.lock` + `requirements-sei.lock` (`pip install --require-hashes --no-deps`), Linux aarch64, Python 3.12 (VM-2).
- Coluna *camadas*: `prod` = requirements.lock · `dev` = requirements-dev.lock · `sei` = requirements-sei.lock.
- Pinados no lock e fora do SBOM (marcador de outra plataforma, não instalados no aarch64): colorama, httpx2-jsfetch, opencv-python.
- No SBOM e fora dos locks (ferramenta do venv): pip.

## 2. Quadro por classe

| Classe | Pacotes |
|---|---:|
| copyleft forte | 4 |
| proprietária | 1 |
| desconhecida | 1 |
| copyleft fraco | 7 |
| permissiva | 169 |

## 3. Para decisão do dono

> **Atenção:** o painel é servido publicamente e o repositório é público. Os pacotes abaixo têm licença copyleft forte (GPL/AGPL), proprietária ou desconhecida. Nada foi removido — só marcado. AGPL alcança uso por rede (§13); GPL alcança distribuição.

| Classe | Pacote | Versão | Licença declarada/concluída | Camadas | Nota |
|---|---|---|---|---|---|
| **copyleft forte** | `pymupdf4llm` | 2.1 | AGPL-3.0 (repositório) | prod, dev, sei | wheel 2.1 sem arquivo fora do .dist-info e sem campo de licença; o LICENSE de github.com/pymupdf/pymupdf4llm é a GNU AGPL v3 |
| **copyleft forte** | `pymupdf` | 2.1 | Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License | prod, dev, sei | SBOM cru sem licença; texto do campo License/classificador lido pelo pip-licenses |
| **copyleft forte** | `igraph` | 1.0.0 | GNU General Public License (GPL) | prod, dev, sei | SBOM cru sem licença; texto do campo License/classificador lido pelo pip-licenses |
| **copyleft forte** | `leidenalg` | 0.12.0 | GPL-3.0-or-later | prod, dev, sei |  |
| **desconhecida** | `pymupdf_layout` | 2.1 | NOASSERTION (meta-pacote vazio) | prod, dev, sei | wheel 2.1 sem arquivo fora do .dist-info e sem campo de licença (PyPI: license=None); puxado por pymupdf==2.1, cujo código é AGPL-3.0 ou comercial Artifex |
| **proprietária** | `nvidia-nccl-cu13` | 2.32.6 | LicenseRef-NVIDIA-Proprietary | prod, dev, sei |  |

## 4. Licença → pacotes

| Classe | Licença | Nº | Pacotes |
|---|---|---:|---|
| copyleft forte | AGPL-3.0 (repositório) | 1 | `pymupdf4llm` 2.1 |
| copyleft forte | Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License | 1 | `pymupdf` 2.1 |
| copyleft forte | GNU General Public License (GPL) | 1 | `igraph` 1.0.0 |
| copyleft forte | GPL-3.0-or-later | 1 | `leidenalg` 0.12.0 |
| proprietária | LicenseRef-NVIDIA-Proprietary | 1 | `nvidia-nccl-cu13` 2.32.6 |
| desconhecida | NOASSERTION (meta-pacote vazio) | 1 | `pymupdf_layout` 2.1 |
| copyleft fraco | LGPL-3.0-only | 3 | `fpdf2` 2.9.0, `psycopg` 3.3.9, `psycopg-binary` 3.3.9 |
| copyleft fraco | LGPL-2.1-or-later OR License :: OSI Approved :: GNU Lesser General Public License v2 or later (LGPLv2+) | 1 | `crc32c` 2.9.post0 |
| copyleft fraco | License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL) | 1 | `python-bidi` 0.6.12 |
| copyleft fraco | MPL-2.0 AND MIT | 1 | `tqdm` 4.70.1 |
| copyleft fraco | MPL-2.0 OR License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0) | 1 | `certifi` 2026.11.20 |
| permissiva | MIT | 65 | `alembic` 1.20.1, `annotated-doc` 0.0.7, `annotated-types` 0.8.0, `anyio` 4.16.0, `attrs` 26.1.0, `beautifulsoup4` 4.15.0, `charset-normalizer` 3.5.3, `colorlog` 6.12.0, `ddddocr` 1.6.1, `docstring_parser` 0.18.0, `duckdb` 2.0.1, `et_xmlfile` 2.0.0, `executing` 2.3.0, `fastapi` 0.165.0, `filelock` 4.3.1, `fonttools` 4.68.0, `greenlet` 3.0.3, `h11` 0.16.0, `httptools` 0.9.0, `imagesize` 2.0.1, `iniconfig` 2.3.1, `jedi` 0.20.1, `jiter` 0.19.0, `Mako` 1.4.3, `markdown-it-py` 4.3.0, `mdurl` 0.1.2, `narwhals` 2.29.0, `onnxruntime` 1.32.0, `openpyxl` 3.1.5, `parso` 0.8.7, `pdfminer.six` 20260107, `pdfplumber` 0.11.11, `pip` 26.3, `pluggy` 1.7.0, `pure_eval` 0.2.4, `py-cpuinfo` 9.0.0, `pydantic` 2.14.4, `pydantic_core` 2.50.5, `pyee` 11.1.0, `pyparsing` 3.3.3, `pytest` 9.2.0, `python-bcb` 0.4.2, `python-docx` 1.2.0, `PyYAML` 6.0.2, `pyzbar` 0.1.9, `RapidFuzz` 3.14.6, `rich` 15.0.0, `ruamel.yaml` 0.19.1, `ruff` 0.17.6, `setuptools` 84.2.1, `six` 1.17.0, `soupsieve` 4.1.3, `splink` 5.0.0, `SQLAlchemy` 2.1.9, `sqlglot` 30.35.0, `stack-data` 0.6.3, `tabulate` 0.10.0, `texttable` 1.7.3, `trio-websocket` 0.12.2, `truststore` 0.10.5, `typing-inspection` 0.4.5, `urllib3` 2.8.0, `watchfiles` 1.3.0, `wcwidth` 0.9.5, `wsproto` 1.3.2 |
| permissiva | BSD-3-Clause | 30 | `click` 8.5.1, `cloudpickle` 3.1.3, `contourpy` 1.4.0, `fsspec` 2026.9.0, `httpcore` 1.0.9, `httpcore2` 2.16.2, `httpx2` 2.16.2, `idna` 3.20, `ipython` 9.19.1, `joblib` 1.6.0, `jsonpickle` 4.1.4, `lazy-loader` 0.6, `lxml` 6.1.3, `MarkupSafe` 3.0.4, `matplotlib-inline` 0.2.2, `networkx` 3.7, `pandas` 3.1.1, `prettytable` 3.19.0, `psutil` 7.2.2, `pycparser` 3.12, `pypdf` 7.1.1, `python-dateutil` 4.0.0, `python-dotenv` 1.2.4, `scikit-learn` 1.9.1, `shapely` 2.2.0, `starlette` 1.10.0, `threadpoolctl` 3.8.0, `tifffile` 2026.11.16, `uvicorn` 0.54.0, `websockets` 17.4 |
| permissiva | Apache-2.0 | 14 | `hf-xet` 1.8.0, `modelscope` 1.40.3, `ninja` 1.13.2, `opentelemetry-api` 1.45.2, `paddlex` 3.4.3, `pyarrow` 26.0.1, `python-multipart` 0.0.34, `selenium` 4.54.0, `tenacity` 9.2.1, `tzdata` 2026.6, `webdriver-manager` 4.1.2, `websocket-client` 1.9.2, `xgboost` 3.4.1, `zxing-cpp` 3.2.0 |
| permissiva | License :: OSI Approved :: BSD License | 14 | `cycler` 0.12.1, `hmmlearn` 0.3.3, `ipython_pygments_lexers` 1.1.1, `Jinja2` 3.1.6, `kiwisolver` 1.5.1, `mpmath` 1.3.0, `numba` 0.68.1, `prompt_toolkit` 3.0.53, `python-louvain` 0.16, `scikit-image` 0.26.0, `scipy` 1.18.1, `sympy` 1.14.0, `traitlets` 5.16.1, `xlrd` 2.0.2 |
| permissiva | Apache-2.0 OR License :: OSI Approved :: Apache Software License | 6 | `aistudio_sdk` 0.3.9, `anthropic` 2.14.0, `huggingface_hub` 2.4.0, `modelscope-hub` 0.7.2, `playwright` 1.44.0, `requests` 2.34.2 |
| permissiva | License :: OSI Approved :: Apache Software License | 5 | `flatbuffers` 25.12.19, `opencv-contrib-python` 4.10.0.84, `opencv-python-headless` 5.1.0.95, `pytesseract` 0.3.13, `sortedcontainers` 2.4.0 |
| permissiva | Apache License 2.0 | 3 | `bce-python-sdk` 0.9.79, `easyocr` 1.7.2, `paddleocr` 3.4.1 |
| permissiva | BSD | 3 | `PySocks` 1.7.1, `pyvis` 0.3.2, `torchvision` 0.29.2+cpu |
| permissiva | BSD-2-Clause | 3 | `ImageIO` 2.38.2, `Pygments` 2.21.0, `pyod` 3.6.9 |
| permissiva | MIT OR Apache-2.0 | 3 | `outcome` 1.3.0.post0, `sniffio` 1.3.1, `trio` 0.35.0 |
| permissiva | ISC | 2 | `pexpect` 4.9.0, `ptyprocess` 0.7.0 |
| permissiva | MIT OR License :: OSI Approved | 2 | `future` 1.0.0, `pyclipper` 1.4.0 |
| permissiva | 0BSD | 1 | `chardet` 7.7.0 |
| permissiva | 3-Clause BSD License | 1 | `protobuf` 7.36.2 |
| permissiva | Apache 2.0 | 1 | `asttokens` 3.0.2 |
| permissiva | Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND ISC AND MIT AND Zlib | 1 | `torch` 2.15.0+cpu |
| permissiva | Apache-2.0 OR BSD-2-Clause | 1 | `packaging` 26.4 |
| permissiva | Apache-2.0 OR BSD-3-Clause | 1 | `cryptography` 50.0.2 |
| permissiva | BSD-2-Clause AND Apache-2.0 WITH LLVM-exception | 1 | `llvmlite` 0.50.0 |
| permissiva | BSD-2-Clause AND Unlicense AND MIT | 1 | `pycryptodome` 4.6.0 |
| permissiva | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 1 | `numpy` 2.5.5 |
| permissiva | BSD-3-Clause AND TCL | 1 | `ujson` 6.1.0 |
| permissiva | BSD-3-Clause OR License :: OSI Approved :: BSD License | 1 | `httpx` 0.28.1 |
| permissiva | BSD-3-Clause, Apache-2.0, dependency licenses | 1 | `pypdfium2` 5.15.2 |
| permissiva | MIT OR License :: DFSG approved | 1 | `pytest-timeout` 2.4.0 |
| permissiva | MIT OR License :: OSI Approved :: Apache Software License | 1 | `uvloop` 0.23.0 |
| permissiva | MIT-0 | 1 | `cffi` 2.1.1 |
| permissiva | MIT-CMU | 1 | `pillow` 13.0.0 |
| permissiva | PSF-2.0 | 1 | `typing_extensions` 4.16.0 |
| permissiva | Python-2.0 | 1 | `matplotlib` 3.11.2 |
| permissiva | any-OSI | 1 | `apsw` 3.54.1.0 |
