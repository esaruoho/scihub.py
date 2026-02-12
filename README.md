scihub.py
[![Python](https://img.shields.io/badge/Python-3%2B-blue.svg)](https://www.python.org)
=========

scihub.py is an unofficial API for Sci-Hub. scihub.py can search for papers on Google Scholar and download papers from Sci-Hub. It can be imported independently or used from the command-line.

If you believe in open access to scientific papers, please donate to Sci-Hub.

Features
--------
* Download specific articles directly or via Sci-Hub by DOI, PMID, or URL
* Download a collection of articles by passing in a file of identifiers
* Search for articles on Google Scholar and download them
* Automatic mirror rotation with fallback across multiple Sci-Hub mirrors
* Rate limiting to reduce CAPTCHA triggers during batch downloads
* Override mirrors with `-m` flag when domains change

**Note**: Sci-Hub has not added new papers since 2021 (pending an Indian court case). Papers up through 2021 should be available. CAPTCHAs may still appear after many consecutive downloads — rate limiting helps but cannot eliminate them entirely.

Setup
-----
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Quick install (shell wrapper)

To use `scihub` as a command from anywhere:

```bash
# Make the wrapper executable
chmod +x scihub.sh

# Symlink to somewhere on your PATH
ln -s /path/to/sci-hub/scihub.sh ~/.local/bin/scihub
```

Usage
-----

### Shell wrapper (quickest)

```bash
# Download by DOI — PDF lands in current directory
scihub 10.1038/nature12373

# Download by URL
scihub https://www.nature.com/articles/nature12373

# Batch download from a file of DOIs (one per line)
scihub -f dois.txt

# Search Google Scholar
scihub -s "CRISPR gene editing"

# Search and download top 5 results
scihub -sd "quantum entanglement" -l 5

# Save to a specific directory
scihub 10.1038/nature12373 -o ~/papers/

# Use a specific mirror (can be repeated)
scihub 10.1038/nature12373 -m https://sci-hub.ru
```

### Command-line (without wrapper)

```bash
source venv/bin/activate

python scihub/scihub.py [-h] [-d (DOI|PMID|URL)] [-f path] [-s query]
                        [-sd query] [-l N] [-o path] [-v] [-p PROXY] [-m URL]
```

| Flag | Description |
|------|-------------|
| `-d`, `--download` | Download a single paper by DOI, PMID, or URL |
| `-f`, `--file` | Path to a file of identifiers (one per line) |
| `-s`, `--search` | Search Google Scholar and print results |
| `-sd`, `--search_download` | Search Google Scholar and download results |
| `-l`, `--limit` | Number of search results (default: 10) |
| `-o`, `--output` | Output directory for downloaded papers |
| `-v`, `--verbose` | Enable verbose/debug logging |
| `-p`, `--proxy` | Proxy URL (e.g. `socks5://user:pass@host:port`) |
| `-m`, `--mirror` | Override Sci-Hub mirror URL (can be repeated) |

### Python API

#### fetch

```python
from scihub import SciHub

sh = SciHub()

# fetch specific article (don't download to disk)
# returns {'pdf': PDF_DATA, 'url': SOURCE_URL, 'name': GENERATED_NAME}
result = sh.fetch('10.1038/nature12373')
```

#### download

```python
from scihub import SciHub

sh = SciHub()

# download to disk — if no path given, a unique name is generated
result = sh.download('10.1038/nature12373', destination='./papers/', path='paper.pdf')
```

#### search

```python
from scihub import SciHub

sh = SciHub()

# search Google Scholar
results = sh.search('CRISPR gene editing', limit=5)

# download each result via Sci-Hub
for paper in results['papers']:
    sh.download(paper['url'], destination='./papers/')
```

#### custom mirrors

```python
from scihub import SciHub

# use specific mirrors instead of built-in defaults
sh = SciHub(mirrors=['https://sci-hub.ru', 'https://sci-hub.vg'])

result = sh.download('10.1038/nature12373')
```

License
-------
MIT
