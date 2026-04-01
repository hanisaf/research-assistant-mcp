@echo off
set SCRIPT_DIR=%~dp0
uv run python .\research-assistant.py --library_directory C:\Users\hanisaf\Documents\Mendeley_Desktop --chroma_db_path C:\Users\hanisaf\Documents\Mendeley_Chroma  --limit_text -1 --update_db True

@REM npx @modelcontextprotocol/inspector ^
@REM   uv --directory "%SCRIPT_DIR%" run python "%SCRIPT_DIR%research-assistant.py" ^
@REM   --library_directory C:\Users\hanisaf\Documents\Mendeley_Desktop ^
@REM   --chroma_db_path C:\Users\hanisaf\Documents\Mendeley_Chroma ^
@REM   --limit_text -1 ^
@REM   --update_db True
