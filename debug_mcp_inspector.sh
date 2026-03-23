#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
npx @modelcontextprotocol/inspector \
  "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/research-assistant.py" \
  --library_directory "$SCRIPT_DIR/../test_data/pdfs" \
  --chroma_db_path "$SCRIPT_DIR/../test_data/pdfs_db" \
  --limit_text -1 \
  --update_db True
# npx @modelcontextprotocol/inspector "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/research-assistant.py" --library_directory /Users/hanisaf/Documents/Mendeley_Desktop --chroma_db_path /Users/hanisaf/Documents/Mendeley_Chroma --limit_text -1 --update_db False