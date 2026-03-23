#!/usr/bin/env python3
# structure from https://github.com/anthropics/dxt/blob/main/examples/file-manager-python/server/main.py
# some code from https://github.com/labeveryday/mcp_pdf_reader

from io import BytesIO
import re
import mimetypes
import os
import argparse
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from urllib.parse import quote
from datetime import datetime
import chromadb
from chromadb.config import Settings 
import tempfile
import logging
import fitz  # PyMuPDF
import pytesseract
from typing import Any, Dict, List, Optional, Tuple
from fastmcp import FastMCP
from PIL import Image
from chromadb.api import ClientAPI
from chroma_manager import ChromaManager

# Configure logging
description="Research Assistant MCP Server"
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(description)


# Parse command line arguments
parser = argparse.ArgumentParser(description=description)
parser.add_argument(
    "--library_directory", default=os.path.expanduser("~/Downloads/pdfs"))
parser.add_argument(
    "--chroma_db_path", default=os.path.expanduser("~/Downloads/pdfs_db"))
parser.add_argument("--limit_text", default=-1)
parser.add_argument(
    "--update_db", default=False, 
    help="Update the ChromaDB database with new PDFs in the library directory",)

args = parser.parse_args()

# System prompt for research assistant
SYSTEM_PROMPT = """If available, use the research assistant tools and cite the sources using APA style (Author year). Refer to information from the sources and do not make things up."""

# Initialize server
mcp = FastMCP(description)

# Initialize ChromaDB client
chroma_manager: Optional[ChromaManager] = None
chroma_client: Optional[ClientAPI] = None
chroma_collection: Optional[chromadb.Collection] = None

# In-memory index of registered resources for quick lookup/search
# Key: URI, Value: dict(name, path, size, mtime, pages)
root : Path 
RESOURCE_INDEX: dict[str, dict] = {}

def normalize_and_validate_file_path(file_path: str) -> Path:
    """Validate that the file path exists and is a PDF"""
    path = Path(file_path)
    # resolve path within root
    if not path.is_absolute():
        path = root.joinpath(path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not path.suffix.lower() == '.pdf':
        raise ValueError(f"File is not a PDF: {file_path}")
    return path

def get_page_range(doc: fitz.Document, page_range: Optional[Dict[str, int]] = None) -> Tuple[int, int]:
    """Get validated page range for the document"""
    total_pages = len(doc)
    
    if page_range is None:
        return 0, total_pages - 1
    
    start = int(page_range.get('start', 1)) - 1  # Convert to 0-based indexing
    end = int(page_range.get('end', total_pages)) - 1
    
    start = max(0, min(start, total_pages - 1))
    end = max(start, min(end, total_pages - 1))
    
    return start, end

@mcp.tool()
def read_pdf_text(file_path: str, page_range_start: Optional[int|str] = None, page_range_end: Optional[int|str] = None) -> Dict[str, Any]:
    """
    Extract plain text content from a PDF file.
    It supports selective page reading for efficient processing
    of large documents when you only need specific sections.
    
    Args:
        file_path (str): Path to the PDF file to read. Can be absolute or relative to 
                        the configured library directory.
        page_range_start (Optional[int|str], optional): Starting page number for extraction 
                                                       (1-indexed). If None, starts from first page.
        page_range_end (Optional[int|str], optional): Ending page number for extraction 
                                                     (1-indexed). If None, reads to last page.
    
    Returns:
        Dict[str, Any]: Dictionary containing:
            - success (bool): Whether extraction was successful
            - file_path (str): Resolved path to the PDF file
            - pages_processed (str): Range of pages processed (e.g., "1-5")
            - total_pages (int): Total number of pages in the PDF
            - pages_text (List[Dict]): Per-page text data with page numbers and word counts
            - combined_text (str): All extracted text concatenated
            - total_word_count (int): Total word count across all processed pages
            - total_character_count (int): Total character count including whitespace
            - error (str, optional): Error message if success is False
        
    Performance Notes:
        - For large PDFs, consider using page ranges to limit processing
        - Text extraction is fast but memory usage scales with document size
        - Use this for searchable PDFs; for scanned documents, use read_pdf_with_ocr()
        
    Error Handling:
        Returns success=False with error message for:
        - File not found or inaccessible
        - Non-PDF files
        - Corrupted or password-protected PDFs
        - Invalid page range specifications
    
    Hint: When search results return specific page numbers, consider using page_range
    to read only relevant pages (e.g., page_range_start=5, page_range_end=7) rather than the entire
    document. This is more efficient for obtaining targeted information around search hits.
    For comprehensive analysis, omit page_range to read the full document.
    """
    try:
        path = normalize_and_validate_file_path(file_path)
        
        with fitz.open(str(path)) as doc:
            if page_range_start is not None or page_range_end is not None:
                page_range = {
                    "start": page_range_start,
                    "end": page_range_end
                }
            else:
                page_range = None
            start_page, end_page = get_page_range(doc, page_range)
            
            pages_text = []
            total_text = ""
            
            for page_num in range(start_page, end_page + 1):
                page = doc[page_num]
                page_text = page.get_text()
                pages_text.append({
                    "page_number": page_num + 1,
                    "text": page_text,
                    "word_count": len(page_text.split())
                })
                total_text += page_text + "\n"
            
            return {
                "success": True,
                "file_path": str(path),
                "pages_processed": f"{start_page + 1}-{end_page + 1}",
                "total_pages": len(doc),
                "pages_text": pages_text,
                "combined_text": total_text.strip(),
                "total_word_count": len(total_text.split()),
                "total_character_count": len(total_text)
            }
            
    except Exception as e:
        logger.error(f"Error reading PDF text: {e}")
        return {
            "success": False,
            "error": str(e),
            "file_path": file_path
        }

@mcp.tool()
def extract_pdf_images(file_path: str, output_dir: Optional[str] = None, page_range_start: Optional[int|str] = None, page_range_end: Optional[int|str] = None) -> Dict[str, Any]:
    """
    Extract all images from a PDF file and save them as PNG files.
        
    Args:
        file_path (str): Path to the PDF file to process. Can be absolute or relative 
                        to the configured library directory.
        output_dir (Optional[str], optional): Directory path where extracted images will be saved.
                                            If None, creates a temporary directory with prefix 'pdf_images_'.
        page_range_start (Optional[int|str], optional): Starting page number for image extraction 
                                                       (1-indexed). If None, starts from first page.
        page_range_end (Optional[int|str], optional): Ending page number for image extraction 
                                                     (1-indexed). If None, processes to last page.
    
    Returns:
        Dict[str, Any]: Dictionary containing:
            - success (bool): Whether extraction was successful
            - file_path (str): Resolved path to the PDF file  
            - output_directory (str): Directory where images were saved
            - pages_processed (str): Range of pages processed (e.g., "1-5")
            - images_extracted (int): Total number of images successfully extracted
            - images (List[Dict]): Detailed information about each extracted image:
                * page_number (int): PDF page where image was found
                * image_index (int): Index of image on that page
                * filename (str): Generated filename for the image
                * path (str): Full path to the saved image file
                * width (int): Image width in pixels
                * height (int): Image height in pixels  
                * size_bytes (int): File size of the extracted image
            - error (str, optional): Error message if success is False
            
    Error Handling:
        Returns success=False with error message for:
        - File not found or inaccessible PDF files
        - Permission errors when creating output directory
        - Corrupted or password-protected PDFs
        - Individual image extraction failures are logged but don't stop processing    
    """
    try:
        path = normalize_and_validate_file_path(file_path)
        
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="pdf_images_")
        else:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        extracted_images = []
        
        with fitz.open(str(path)) as doc:
            if page_range_start is not None or page_range_end is not None:
                page_range = {
                    "start": page_range_start,
                    "end": page_range_end
                }
            else:
                page_range = None
            start_page, end_page = get_page_range(doc, page_range)
            
            for page_num in range(start_page, end_page + 1):
                page = doc[page_num]
                image_list = page.get_images()
                
                for img_index, img in enumerate(image_list):
                    try:
                        # Get image data
                        xref = img[0]
                        pix = fitz.Pixmap(doc, xref)
                        
                        # Skip if image is too small or has alpha channel issues
                        if pix.width < 10 or pix.height < 10:
                            pix = None
                            continue
                        
                        # Convert to PNG if needed
                        if pix.n - pix.alpha < 4:  # GRAY or RGB
                            img_data = pix.tobytes("png")
                        else:  # CMYK: convert to RGB first
                            pix1 = fitz.Pixmap(fitz.csRGB, pix)
                            img_data = pix1.tobytes("png")
                            pix1 = None
                        
                        # Save image
                        img_filename = f"page_{page_num + 1}_img_{img_index + 1}.png"
                        img_path = Path(output_dir) / img_filename
                        
                        with open(img_path, "wb") as img_file:
                            img_file.write(img_data)
                        
                        extracted_images.append({
                            "page_number": page_num + 1,
                            "image_index": img_index + 1,
                            "filename": img_filename,
                            "path": str(img_path),
                            "width": pix.width,
                            "height": pix.height,
                            "size_bytes": len(img_data)
                        })
                        
                        pix = None
                        
                    except Exception as img_error:
                        logger.warning(f"Failed to extract image {img_index + 1} from page {page_num + 1}: {img_error}")
                        continue
        
        return {
            "success": True,
            "file_path": str(path),
            "output_directory": output_dir,
            "pages_processed": f"{start_page + 1}-{end_page + 1}",
            "images_extracted": len(extracted_images),
            "images": extracted_images
        }
        
    except Exception as e:
        logger.error(f"Error extracting PDF images: {e}")
        return {
            "success": False,
            "error": str(e),
            "file_path": file_path
        }

@mcp.tool()
def read_pdf_with_ocr(file_path: str, page_range_start: Optional[int|str] = None, page_range_end: Optional[int|str] = None, ocr_language: str = "eng") -> Dict[str, Any]:
    """
    Extract text from PDF including OCR text from images
    
    Args:
        file_path: Path to the PDF file
        page_range: Optional dict with 'start' and 'end' page numbers (1-indexed)
        ocr_language: OCR language code (default: 'eng')
    
    Returns:
        Dictionary containing extracted text from both text and images
    """
    try:
        path = normalize_and_validate_file_path(file_path)
        
        with fitz.open(str(path)) as doc:
            if page_range_start is not None or page_range_end is not None:
                page_range = {
                    "start": page_range_start,
                    "end": page_range_end
                }
            else:
                page_range = None
            start_page, end_page = get_page_range(doc, page_range)
            
            pages_data = []
            total_text = ""
            total_ocr_text = ""
            
            for page_num in range(start_page, end_page + 1):
                page = doc[page_num]
                
                # Extract regular text
                page_text = page.get_text()
                
                # Extract and OCR images
                image_texts = []
                image_list = page.get_images()
                
                for img_index, img in enumerate(image_list):
                    try:
                        xref = img[0]
                        pix = fitz.Pixmap(doc, xref)
                        
                        # Skip very small images
                        if pix.width < 50 or pix.height < 50:
                            pix = None
                            continue
                        
                        # Convert to PIL Image for OCR
                        if pix.n - pix.alpha < 4:  # GRAY or RGB
                            img_data = pix.tobytes("png")
                        else:  # CMYK: convert to RGB first
                            pix1 = fitz.Pixmap(fitz.csRGB, pix)
                            img_data = pix1.tobytes("png")
                            pix1 = None
                        
                        # Perform OCR
                        with Image.open(BytesIO(img_data)) as pil_image:
                            ocr_text = pytesseract.image_to_string(
                                pil_image, 
                                lang=ocr_language,
                                config='--psm 6'  # Uniform block of text
                            ).strip()
                            
                            if ocr_text:
                                image_texts.append({
                                    "image_index": img_index + 1,
                                    "ocr_text": ocr_text,
                                    "confidence": "high" if len(ocr_text) > 10 else "low"
                                })
                        
                        pix = None
                        
                    except Exception as ocr_error:
                        logger.warning(f"OCR failed for image {img_index + 1} on page {page_num + 1}: {ocr_error}")
                        continue
                
                # Combine all OCR text from this page
                page_ocr_text = "\n".join([img["ocr_text"] for img in image_texts])
                
                page_data = {
                    "page_number": page_num + 1,
                    "text": page_text,
                    "ocr_text": page_ocr_text,
                    "images_with_text": image_texts,
                    "combined_text": f"{page_text}\n{page_ocr_text}".strip(),
                    "text_word_count": len(page_text.split()),
                    "ocr_word_count": len(page_ocr_text.split())
                }
                
                pages_data.append(page_data)
                total_text += page_text + "\n"
                total_ocr_text += page_ocr_text + "\n"
            
            combined_all_text = f"{total_text}\n{total_ocr_text}".strip()
            
            return {
                "success": True,
                "file_path": str(path),
                "pages_processed": f"{start_page + 1}-{end_page + 1}",
                "total_pages": len(doc),
                "ocr_language": ocr_language,
                "pages_data": pages_data,
                "summary": {
                    "total_text_word_count": len(total_text.split()),
                    "total_ocr_word_count": len(total_ocr_text.split()),
                    "combined_word_count": len(combined_all_text.split()),
                    "combined_character_count": len(combined_all_text),
                    "images_processed": sum(len(p["images_with_text"]) for p in pages_data)
                },
                "combined_text": total_text.strip(),
                "combined_ocr_text": total_ocr_text.strip(),
                "all_text_combined": combined_all_text
            }
            
    except Exception as e:
        logger.error(f"Error reading PDF with OCR: {e}")
        return {
            "success": False,
            "error": str(e),
            "file_path": file_path
        }

@mcp.tool()
def get_pdf_info(file_path: str) -> Dict[str, Any]:
    """
    Get comprehensive metadata and structural information about a PDF file.
    
    This function provides detailed information about PDF files including document metadata,
    file statistics, page details, and content analysis. It's useful for understanding
    document structure before processing or for generating document summaries.
    
    Args:
        file_path (str): Path to the PDF file to analyze. Can be absolute or relative 
                        to the configured library directory.
    
    Returns:
        Dict[str, Any]: Comprehensive information dictionary containing:
            - success (bool): Whether analysis completed successfully
            - file_path (str): Resolved path to the PDF file
            - file_info (Dict): File system information:
                * size_bytes (int): File size in bytes
                * size_mb (float): File size in megabytes (rounded to 2 decimals)
                * created (float): Creation timestamp
                * modified (float): Last modification timestamp
            - pdf_metadata (Dict): PDF document metadata:
                * title (str): Document title from metadata
                * author (str): Document author from metadata
                * subject (str): Document subject/description
                * creator (str): Application that created the PDF
                * producer (str): Application that produced the PDF
                * creation_date (str): PDF creation date
                * modification_date (str): PDF last modification date
            - document_stats (Dict): Document content statistics:
                * total_pages (int): Number of pages in the PDF
                * total_images (int): Total number of embedded images
                * pages_with_text (int): Number of pages containing text
                * pages_with_images (int): Number of pages containing images
                * is_encrypted (bool): Whether PDF is password protected
                * can_extract_text (bool): Whether text extraction is possible
            - page_details (List[Dict]): Per-page detailed information
            - error (str, optional): Error message if success is False
    
    Usage Examples:
        # Get basic PDF information
        info = get_pdf_info("document.pdf")
        
        # Check if PDF is suitable for text extraction
        info = get_pdf_info("report.pdf")
        if info["success"] and not info["document_stats"]["is_encrypted"]:
            print(f"Ready to process {info['document_stats']['total_pages']} pages")
    
    Analysis Features:
        - Extracts all available PDF metadata fields
        - Analyzes content distribution across pages
        - Identifies pages with text vs. image-only content
        - Measures page dimensions for layout analysis
        - Detects encryption and text extraction capabilities
        
    Performance Notes:
        - Fast operation that doesn't extract full content
        - Memory usage is minimal regardless of PDF size
        - Suitable for batch analysis of large PDF collections
        
    Error Handling:
        Returns success=False with error message for:
        - File not found or inaccessible
        - Non-PDF files or corrupted PDF files
        - Permission errors when accessing the file
    """
    try:
        path = normalize_and_validate_file_path(file_path)
        file_stats = path.stat()
        
        with fitz.open(str(path)) as doc:
            # Get basic document info
            metadata = doc.metadata
            
            # Count images across all pages
            total_images = 0
            page_info = []
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                images_on_page = len(page.get_images())
                total_images += images_on_page
                
                page_info.append({
                    "page_number": page_num + 1,
                    "images_count": images_on_page,
                    "text_length": len(page.get_text()),
                    "has_text": bool(page.get_text().strip()),
                    "page_width": page.rect.width,
                    "page_height": page.rect.height
                })
            
            return {
                "success": True,
                "file_path": str(path),
                "file_info": {
                    "size_bytes": file_stats.st_size,
                    "size_mb": round(file_stats.st_size / (1024 * 1024), 2),
                    "created": file_stats.st_ctime,
                    "modified": file_stats.st_mtime
                },
                "pdf_metadata": {
                    "title": metadata.get("title", ""),
                    "author": metadata.get("author", ""),
                    "subject": metadata.get("subject", ""),
                    "creator": metadata.get("creator", ""),
                    "producer": metadata.get("producer", ""),
                    "creation_date": metadata.get("creationDate", ""),
                    "modification_date": metadata.get("modDate", "")
                },
                "document_stats": {
                    "total_pages": len(doc),
                    "total_images": total_images,
                    "pages_with_text": sum(1 for p in page_info if p["has_text"]),
                    "pages_with_images": sum(1 for p in page_info if p["images_count"] > 0),
                    "is_encrypted": doc.needs_pass,
                    "can_extract_text": not doc.is_closed
                },
                "page_details": page_info
            }
            
    except Exception as e:
        logger.error(f"Error getting PDF info: {e}")
        return {
            "success": False,
            "error": str(e),
            "file_path": file_path
        }

@mcp.tool()
def analyze_pdf_structure(file_path: str) -> Dict[str, Any]:
    """
    Analyze PDF structure including pages, images, and text blocks
    
    Args:
        file_path: Path to the PDF file
    
    Returns:
        Dictionary containing detailed structural analysis
    """
    try:
        path = normalize_and_validate_file_path(file_path)
        
        with fitz.open(str(path)) as doc:
            structure_analysis = {
                "document_structure": {
                    "total_pages": len(doc),
                    "is_encrypted": doc.needs_pass,
                    "pdf_version": doc.pdf_version() if hasattr(doc, 'pdf_version') else "unknown"
                },
                "content_analysis": {
                    "pages_with_text": 0,
                    "pages_with_images": 0,
                    "pages_text_only": 0,
                    "pages_images_only": 0,
                    "pages_mixed_content": 0,
                    "total_text_blocks": 0,
                    "total_images": 0
                },
                "page_details": []
            }
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Get text blocks
                text_blocks = page.get_text("dict")["blocks"]
                text_block_count = len([block for block in text_blocks if "lines" in block])
                
                # Get images
                images = page.get_images()
                image_count = len(images)
                
                # Get text
                page_text = page.get_text().strip()
                has_text = bool(page_text)
                has_images = image_count > 0
                
                # Categorize page content
                if has_text and has_images:
                    content_type = "mixed"
                    structure_analysis["content_analysis"]["pages_mixed_content"] += 1
                elif has_text:
                    content_type = "text_only"
                    structure_analysis["content_analysis"]["pages_text_only"] += 1
                elif has_images:
                    content_type = "images_only"
                    structure_analysis["content_analysis"]["pages_images_only"] += 1
                else:
                    content_type = "empty"
                
                if has_text:
                    structure_analysis["content_analysis"]["pages_with_text"] += 1
                if has_images:
                    structure_analysis["content_analysis"]["pages_with_images"] += 1
                
                structure_analysis["content_analysis"]["total_text_blocks"] += text_block_count
                structure_analysis["content_analysis"]["total_images"] += image_count
                
                page_detail = {
                    "page_number": page_num + 1,
                    "content_type": content_type,
                    "text_blocks": text_block_count,
                    "image_count": image_count,
                    "text_length": len(page_text),
                    "dimensions": {
                        "width": page.rect.width,
                        "height": page.rect.height
                    },
                    "rotation": page.rotation
                }
                
                structure_analysis["page_details"].append(page_detail)
            
            # Add summary statistics
            structure_analysis["summary"] = {
                "content_distribution": {
                    "text_only_pages": structure_analysis["content_analysis"]["pages_text_only"],
                    "images_only_pages": structure_analysis["content_analysis"]["pages_images_only"],
                    "mixed_content_pages": structure_analysis["content_analysis"]["pages_mixed_content"],
                    "empty_pages": len(doc) - sum([
                        structure_analysis["content_analysis"]["pages_text_only"],
                        structure_analysis["content_analysis"]["pages_images_only"],
                        structure_analysis["content_analysis"]["pages_mixed_content"]
                    ])
                },
                "avg_images_per_page": round(structure_analysis["content_analysis"]["total_images"] / len(doc), 2),
                "avg_text_blocks_per_page": round(structure_analysis["content_analysis"]["total_text_blocks"] / len(doc), 2)
            }
            
            return {
                "success": True,
                "file_path": str(path),
                **structure_analysis
            }
            
    except Exception as e:
        logger.error(f"Error analyzing PDF structure: {e}")
        return {
            "success": False,
            "error": str(e),
            "file_path": file_path
        }

@mcp.tool()
def search_title(query: str, top_n: int = 10) -> Dict[str, Any]:
    """
    Select the single most relevant files by counting token overlap
    between the query and the file name. Returns a ranked list.
    Useful for searching for an author.
    
    Args:
        query: Search term to match against filenames
        top_n: Number of results to return (default: 10)
    
    Note: When citing results from this search, use APA format (Author year)
    based on the filename or extracted metadata from the PDF sources.
    
    Hint: Adjust top_n based on search scope needs:
    - Use lower values (3-5) for focused searches when you need just the most relevant files
    - Use higher values (15-25) for broader exploration or when initial search yields few results
    - Start with default (10) for balanced coverage, then adjust based on result quality
    """

    def tokenize(text: str):
        return set(re.findall(r"[a-z0-9]+", (text or "").lower()))

    q_tokens = tokenize(query.lower())
    if not q_tokens:
        return {
            "query": query,
            "success": False,
            "error": "query is empty",
        }

    candidates = []

    if RESOURCE_INDEX:
        for uri, meta in RESOURCE_INDEX.items():
            name = meta.get("name") or uri
            filename = Path(name).name
            overlap = len(q_tokens & tokenize(filename.lower()))
            if overlap > 0:
                candidates.append({
                    "filename": filename,
                    "score": overlap,
                    #"uri": uri,
                    "meta": meta,
                })
    else:
        return  {
            "query": query,
            "success": False,
            "error": "No files available to search",
        }


    candidates.sort(key=lambda x: x["score"], reverse=True)

    return {
            "query": query,
            "success": True,
            "matches": candidates[:top_n],
        }

@mcp.tool()
def search_content(query: str, max_num_chunks: int = 25, max_num_files: int = 5) -> Dict[str, Any]:
    """
    Select the most relevant resources using vector similarity search
    against content of the resources. Returns ranked results based on
    semantic similarity to the query.
    Useful for searching for a topic.
    
    Args:
        query: Search query to match against document content
        max_num_chunks: Maximum number of text chunks to retrieve (default: 25)
        max_num_files: Maximum number of unique files to return (default: 5)
    
    Note: When citing results from this search, use APA format (Author year)
    based on the filename.
    
    Hint: Adjust parameters based on search scope and depth needs:
    - For focused research: Use lower values (max_num_chunks=10-15, max_num_files=2-3)
    - For comprehensive exploration: Use higher values (max_num_chunks=50-75, max_num_files=8-12)  
    - For broad overview: Increase max_num_files (8-10) with moderate chunks (20-30)
    - For deep dive: Increase max_num_chunks (40-60) with fewer files (3-5)
    - Start with defaults and adjust based on result relevance and coverage
    """
    if not query.strip():
        return {
            "query": query,
            "success": False,
            "error": "Query is empty.",
        }

    
    if chroma_collection is None:
        return {
            "query": query,
            "success": False,
            "error": "ChromaDB collection not available. Please check the database path.",
        }
    
    try:
        # Query the ChromaDB collection
        results = chroma_collection.query(
            query_texts=[query],
            n_results=max_num_chunks  # Get top results
        )
        
        if not results['documents'] or not results['documents'][0]:
            return {
            "query": query,
            "success": False,
            "error": "No relevant documents found in the database.",
            }
        
        # aggregate by filename using the min distance
        documents = results['documents'][0] if results['documents'] else []
        distances = results['distances'][0] if results['distances'] else []
        metadatas = results['metadatas'][0] if results['metadatas'] else []
        ids = results['ids'][0] if results['ids'] else []
        
        # Aggregate by filename, keeping the minimum distance for each file
        filename_distances = {}
        filename_matches = {}
        filename_pages = {}
        # Track per-file page hits with their distances for later sorting
        file_pages: dict[str, list[tuple[float, int, float]]] = {}
        for doc_id, document, distance, metadata in zip(ids, documents, distances, metadatas):
            # Extract filename from metadata or document ID
            filename = metadata.get('filename', doc_id) if metadata else doc_id
            page_number = metadata.get('page_number') if metadata else None

            # Keep the minimum distance (best match) for each filename
            if filename not in filename_distances or distance < filename_distances[filename]:
                filename_distances[filename] = distance
                filename_matches[filename] = document
                filename_pages[filename] = page_number
        
            # collect from metadatas the pages where the match was found and the similarity score
            # sort by distance (lower is better)
            # report only page number and similarity score
            # Note: page is already available in metadata
            if metadata:
                page = metadata.get('page_number')
                if isinstance(page, int):
                    # Convert distance to similarity (lower distance => higher similarity)
                    similarity = 2 - distance
                    file_pages.setdefault(filename, []).append((distance, page, similarity))
        # Sort by distance (ascending - lower is better) and take top max_num_files
        sorted_files = sorted(filename_distances.items(), key=lambda x: x[1])[:max_num_files]
        
        candidates = []
        for i, (filename, distance) in enumerate(sorted_files):
            # Convert distance to similarity score (lower distance = higher similarity)
            similarity = 2 - distance  # Assuming distance is in [0, 2]
            record = {"rank": i, "filename": filename, 
                      "best_match_similarity": f"{similarity:.4f}",
                      "best_match_text": filename_matches[filename],
                      "best_match_page": filename_pages[filename]
                      }
            # Attach page-level hits sorted by distance (best first), deduplicated by page
            if filename in file_pages:
                # Sort by distance ascending and deduplicate pages keeping best (lowest distance)
                seen_pages = set()
                page_entries = []
                for d, p, s in sorted(file_pages[filename], key=lambda x: x[0]):
                    if p in seen_pages:
                        continue
                    seen_pages.add(p)
                    page_entries.append({"page": p, "similarity": f"{s:.4f}"})
                record["all_matches_number"] = len(page_entries)
                record["all_matches_pages"] = page_entries
            candidates.append(record)
        return {
            "query": query,
            "success": True,
            "matches": candidates,
            }
    
    except Exception as e:
        return  {
            "query": query,
            "success": False,
            "error": f"Error querying ChromaDB: {str(e)}",
            }
    
def register_pdfs(
    library: str,
    include_globs: tuple[str, ...] = ("**/*.pdf",),
    ignore_dirs: tuple[str, ...] = (".git", ".svn", "__pycache__"),
    follow_symlinks: bool = False,
    max_bytes: int | None = None,
) -> None:
    """
    Walk `library` and register concrete MCP resources for matching files as
    `library://<percent-encoded-relative-path>`.
    """
    logger.info("Registering resources in {root} ...")
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Library does not exist or is not a directory: {library}")

    # Clear and rebuild the index each time
    RESOURCE_INDEX.clear()

    def make_resource(uri: str, target: Path, display_name: str, description: str, mime: str):
        # Define a unique resource function bound to this file & URI
        @mcp.resource(
            uri,
            name=display_name,                    # resource name shown to clients
            description=description,
            mime_type=mime,
        )
        def _file_resource() -> bytes:
            # Return raw bytes so binary files work too
            return target.read_bytes()
        
        return _file_resource

    # Build a list of candidate paths honoring ignore rules
    candidates: list[Path] = []
    for pattern in include_globs:
        try:
            for p in root.glob(pattern):
                # Enforce directory ignore rules
                parts = set(p.parts)
                if any(ig in parts for ig in ignore_dirs):
                    continue
                if not follow_symlinks and p.is_symlink():
                    continue
                if not p.exists() or not p.is_file():
                    continue
                if max_bytes is not None:
                    try:
                        if p.stat().st_size > max_bytes:
                            continue
                    except Exception:
                        # If we cannot stat, skip conservatively
                        continue
                candidates.append(p)
        except Exception:
            # Ignore malformed patterns or traversal errors
            continue

    # Deterministic ordering
    candidates.sort(key=lambda x: x.as_posix())

    for p in candidates:
        try:
            rel = p.relative_to(root).as_posix()        # posix-style path
            uri = f"library://{quote(rel, safe='/')}" # keep slashes, encode spaces, etc.

            size = p.stat().st_size
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            mime, _ = mimetypes.guess_type(p.name)
            mime = mime or "application/pdf"  # default to PDF since we target PDFs by default

            desc_bits = [p.name]
            description = " | ".join(desc_bits)

            # Use relative path as the display name to disambiguate duplicates
            display_name = rel

            make_resource(uri, p, display_name, description, mime)

            # Populate index for later search
            RESOURCE_INDEX[uri] = {
                "name": display_name,
                "path": str(p),
                "size": size,
                "mtime": mtime.timestamp(),
                "mime": mime,
            }
        except PermissionError:
            # Skip unreadable files, keep going
            continue
        except Exception:
            # Never let a single bad file break registration
            continue

def initialize_chromadb(library_root: Path) -> tuple[Optional[ChromaManager], Optional[ClientAPI], Optional[chromadb.Collection]]:
    """Initialize ChromaDB client and collection in read-only mode."""
    manager: Optional[ChromaManager] = None
    client: Optional[ClientAPI] = None
    collection: Optional[chromadb.Collection] = None

    try:
        # Prepare ChromaDB settings
        settings_config = Settings(anonymized_telemetry=False)

        manager = ChromaManager(args.chroma_db_path, settings_config)
        client = manager.client
        
        # Get the first available collection (assuming there's one)
        collections = client.list_collections()
        if collections:
            collection = collections[0]
            manager.collection
            logger.info(f"Connected to ChromaDB collection: {collection.name}")
        else:
            logger.warning("Warning: No collections found in ChromaDB")

        if args.update_db=='True':
            logger.info("updating ChromaDB with new PDFs from the library directory...")
            manager.sync_database(
                library_root.as_posix(),
                progress_callback=lambda i, msg: logger.info(" " + str(i) + "% " + msg),
            )

    except Exception as e:
        logger.error(f"Error initializing ChromaDB: {e}")
        return None, None, None

    return manager, client, collection

if __name__ == "__main__":
    logger.info(description)
    logger.info(f"Arguments: `{args}`")
    # Register library files as MCP resources
    logger.info(f"Using library directory: {args.library_directory}")
    root = Path(args.library_directory).expanduser().resolve()
    # Initialize ChromaDB
    chroma_manager, chroma_client, chroma_collection = initialize_chromadb(root)
    logger.info(f"ChromaDB initialized: manager={chroma_manager is not None}, client={chroma_client is not None}, collection={chroma_collection is not None}")
    logger.info("Registering PDF files in the library...")
    register_pdfs(args.library_directory)
    logger.info(f"Registered {len(RESOURCE_INDEX)} PDF resources.")
    # Run the server
    mcp.run()
