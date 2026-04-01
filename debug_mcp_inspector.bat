@echo off
set SCRIPT_DIR=%~dp0
npx @modelcontextprotocol/inspector ^
  uv --directory "%SCRIPT_DIR%" run python "%SCRIPT_DIR%research-assistant.py" ^
  --library_directory "%SCRIPT_DIR%test_data\pdfs" ^
  --chroma_db_path "%SCRIPT_DIR%test_data\pdfs_db" ^
  --limit_text -1 ^
  --update_db True
rem npx @modelcontextprotocol/inspector uv --directory "%SCRIPT_DIR%" run python "%SCRIPT_DIR%research-assistant.py" --library_directory C:\Users\hanisaf\Documents\Mendeley_Desktop --chroma_db_path C:\Users\hanisaf\Documents\Mendeley_Chroma --limit_text -1 --update_db False
rem uv run python research-assistant.py --library_directory test_data\pdfs --chroma_db_path test_data\pdfs_db
