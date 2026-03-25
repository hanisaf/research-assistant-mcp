"""
Test the MCP server tools in-process by calling them as plain Python functions.
Run with: uv run python test_server.py
"""
import json
import sys
import importlib
import importlib.util
from pathlib import Path

# Point args at test data before the module parses sys.argv
sys.argv = [
    "research-assistant.py",
    "--library_directory", "test_data/pdfs",
    "--chroma_db_path", "test_data/pdfs_db",
    "--update_db", "False",
]

# Load module despite the hyphen in its filename
spec = importlib.util.spec_from_file_location(
    "research_assistant", Path(__file__).parent / "research-assistant.py"
)
ra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ra)

# Bootstrap the globals that __main__ normally sets up
ra.root = Path("test_data/pdfs").resolve()
ra.chroma_manager, ra.chroma_client, ra.chroma_collection = ra.initialize_chromadb(ra.root)
ra.register_pdfs("test_data/pdfs")

PDF = next(iter(ra.RESOURCE_INDEX.values()))["path"]   # first registered PDF

def show(label, result):
    print(f"\n=== {label} ===")
    print(json.dumps(result, indent=2, default=str))

show("get_pdf_info", ra.get_pdf_info(PDF))
show("search_title", ra.search_title("Safadi"))
show("search_content", ra.search_content("online communities", max_num_chunks=5, max_num_files=2))
show("read_pdf_text pages 1-2", ra.read_pdf_text(PDF, page_range_start=1, page_range_end=2))
