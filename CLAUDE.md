# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Model Context Protocol (MCP) server that exposes PDF processing and semantic search capabilities to AI assistants. It wraps ChromaDB vector search and PDF extraction tools as MCP tools/resources.

## Development Commands

```bash
# Run the server
uv run python research-assistant.py

# Run with custom paths
uv run python research-assistant.py \
  --library_directory /path/to/pdfs \
  --chroma_db_path /path/to/db \
  --update_db True

# Debug with MCP Inspector (requires Node.js)
./debug_mcp_inspector.sh
```

The debug script uses `../test_data/pdfs/` and `../test_data/pdfs_db/` as test fixtures.

## Architecture

**Entry point**: `research-assistant.py` — FastMCP server that registers 7 tools and PDF resources.

**Three-layer design:**
- `research-assistant.py`: MCP protocol layer — tool definitions, resource registration, argument parsing
- `chroma_manager.py`: ChromaDB wrapper — embeddings, device selection (CUDA > MPS > CPU), sync operations
- `pdf_processor.py`: PDF extraction — text, images, OCR, chunking strategies (page/semantic/recursive)

**Startup sequence:**
1. Parse args, create `ChromaManager`, load/create ChromaDB collection
2. Scan `library_directory` for PDFs, register each as `library://{relative-path}` MCP resource
3. Optionally sync new/modified/deleted PDFs into ChromaDB (`--update_db True`)
4. Start FastMCP server

## MCP Tools

| Tool | Purpose |
|------|---------|
| `search_content` | Vector similarity search via ChromaDB |
| `search_title` | Filename token-overlap search |
| `read_pdf_text` | Extract text by page range |
| `read_pdf_with_ocr` | Text + Tesseract OCR on images |
| `extract_pdf_images` | Save embedded images to disk |
| `get_pdf_info` | File metadata and structure summary |
| `analyze_pdf_structure` | Page-level content categorization |

## Key Dependencies

- `fastmcp` 2.x — MCP server framework
- `chromadb` 1.0.20 — pinned; uses `PersistentClient` API
- `sentence-transformers` 2.2.2 — embedding model `all-MiniLM-L6-v2` (384-dim)
- `PyMuPDF` (fitz) — primary PDF library for images/structure
- `pypdf` — fallback text extraction
- `numpy` < 2.0.0 — required for ChromaDB/torch compatibility

## ChromaDB Schema

Each chunk stored with ID `{filename}_{chunk_index}_{page_number}` and metadata: `filename`, `filepath`, `page_number`, `chunk_index`, `chunk_type`, `chunk_size`, `total_pages`, `file_size`, `apa_reference`, `extraction_date`.

## Important Notes


- OCR requires `tesseract` binary installed on the system

- Below is how to configure the MCP with Claude in `claude_desktop_config.json`

Mac

```
    "research-assistant": {                                                                                
      "command": "/opt/homebrew/bin/uv",                    
      "args": [                                                                                            
        "--directory", "/Users/hanisaf/Projects/research-assistant-mcp",
        "run", "python",                                                                                   
        "/Users/hanisaf/Projects/research-assistant-mcp/research-assistant.py",                            
        "--library_directory", "/Users/hanisaf/Documents/Mendeley_Desktop",                                
        "--chroma_db_path", "/Users/hanisaf/Documents/Mendeley_Chroma",                                    
        "--limit_text", "-1"                                
      ],                                                                                                   
      "env": {}                                             
    }```

Windows

```
    "research assistant": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\Users\\hanisaf\\Projects\\research-assistant-mcp",
        "run", "python",
        "research-assistant.py",
        "--library_directory",
        "C:\\Users\\hanisaf\\Documents\\Mendeley_Desktop",
        "--chroma_db_path",
        "C:\\Users\\hanisaf\\Documents\\Mendeley_Chroma",
        "--limit_text",
        "-1"
      ],
      "env": {}
    }
```