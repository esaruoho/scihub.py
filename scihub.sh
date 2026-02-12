#!/bin/bash
# scihub — download research papers by DOI, URL, or search query
# Usage:
#   scihub 10.1038/nature12373              # download by DOI
#   scihub -f dois.txt                      # batch download from file
#   scihub -s "CRISPR gene editing"         # search Google Scholar
#   scihub -sd "quantum entanglement" -l 3  # search and download top 3

SCIHUB_DIR="/Users/esaruoho/work/sci-hub"

# If first arg doesn't start with -, treat it as a DOI/URL to download
if [ $# -ge 1 ] && [[ ! "$1" =~ ^- ]]; then
    exec "$SCIHUB_DIR/venv/bin/python3" "$SCIHUB_DIR/scihub/scihub.py" -d "$@"
else
    exec "$SCIHUB_DIR/venv/bin/python3" "$SCIHUB_DIR/scihub/scihub.py" "$@"
fi
