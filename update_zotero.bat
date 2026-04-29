@echo off
set SCRIPT_DIR=%~dp0
uv run python .\research-assistant.py --library_directory C:\Users\hanisaf\Zotero\storage --chroma_db_path C:\Users\hanisaf\Documents\Zotero_Chroma  --limit_text -1 --update_db True
