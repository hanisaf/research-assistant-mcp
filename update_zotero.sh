#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
uv --directory "$SCRIPT_DIR" run python "$SCRIPT_DIR/research-assistant.py" \
  --library_directory /Users/hanisaf/Zotero/storage \
  --chroma_db_path /Users/hanisaf/Documents/Zotero_Chroma \
  --limit_text -1 \
  --update_db True