#!/usr/bin/env python3
"""
Clean HTML from Markdown Files

This script walks through all markdown files in the knowledgebase directory,
detects HTML code, and either converts it to markdown or strips it out.
"""

import re
from pathlib import Path
from bs4 import BeautifulSoup
import html2text
from datetime import datetime

def has_html_tags(content):
    """Check if content contains HTML tags."""
    # Look for common HTML tags (opening or closing, with or without attributes)
    html_pattern = r'</?(?:div|span|p|a|img|table|tr|td|th|ul|ol|li|h[1-6]|br|hr|strong|em|b|i|pre|code|blockquote)(?:\s|>|/)'
    return bool(re.search(html_pattern, content, re.IGNORECASE))

def clean_html_from_markdown(content):
    """
    Convert HTML to markdown or strip it if conversion isn't feasible.
    
    Args:
        content: The markdown file content that may contain HTML
        
    Returns:
        Tuple of (cleaned content, changed flag)
    """
    if not has_html_tags(content):
        return content, False  # No changes needed
    
    # Configure html2text converter
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = False
    h.ignore_emphasis = False
    h.body_width = 0  # Don't wrap lines
    h.unicode_snob = True
    h.skip_internal_links = False
    
    # First, try to convert the entire content as HTML
    # This works best for files that are entirely or mostly HTML
    try:
        soup = BeautifulSoup(content, 'html.parser')
        if soup.find():  # Has HTML tags
            # Try html2text conversion
            converted = h.handle(content).strip()
            if converted != content.strip():
                # Successfully converted and it's different from original
                # Final cleanup: remove any remaining HTML tags (orphaned closing tags, etc.)
                converted = remove_remaining_html(converted)
                return converted, True
        else:
            # No properly formed HTML elements, but might have orphaned tags
            # Use BeautifulSoup to strip any remaining tags
            text_only = soup.get_text()
            if text_only != content and has_html_tags(content):
                # Content had HTML that was stripped
                cleaned = remove_remaining_html(text_only)
                return cleaned, True
    except:
        pass  # Fall back to line-by-line processing
    
    # Fall back to line-by-line processing for mixed markdown/HTML content
    lines = content.split('\n')
    cleaned_lines = []
    i = 0
    changed = False
    
    while i < len(lines):
        line = lines[i]
        
        # Check if this line contains HTML
        if has_html_tags(line):
            # Collect consecutive lines that might be part of the same HTML block
            html_block = [line]
            j = i + 1
            
            # Look ahead for more HTML lines or continuation
            while j < len(lines):
                next_line = lines[j]
                # If next line is empty and we have unclosed tags, continue
                # If next line has HTML, continue
                # Otherwise, stop
                if has_html_tags(next_line):
                    html_block.append(next_line)
                    j += 1
                elif next_line.strip() == '' and has_unclosed_tags('\n'.join(html_block)):
                    html_block.append(next_line)
                    j += 1
                else:
                    break
            
            # Try to convert the HTML block
            html_content = '\n'.join(html_block)
            
            try:
                # Parse with BeautifulSoup to check if it's valid HTML
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # If it's mostly HTML (not just inline tags in markdown), convert it
                if soup.find():
                    # Convert to markdown
                    converted = h.handle(html_content).strip()
                    
                    # If conversion resulted in something meaningful, use it
                    if converted:
                        cleaned_lines.append(converted)
                        changed = True
                    else:
                        # Just strip the HTML tags but keep text content
                        text_only = soup.get_text(separator='\n', strip=True)
                        if text_only:
                            cleaned_lines.append(text_only)
                            changed = True
                else:
                    # Not really HTML, keep as is
                    cleaned_lines.extend(html_block)
                    
            except Exception as e:
                # If parsing/conversion fails, try to strip HTML tags
                try:
                    soup = BeautifulSoup(html_content, 'html.parser')
                    text_only = soup.get_text(separator='\n', strip=True)
                    if text_only:
                        cleaned_lines.append(text_only)
                        changed = True
                except:
                    # If even stripping fails, keep original
                    cleaned_lines.extend(html_block)
            
            i = j
        else:
            # No HTML in this line, keep as is
            cleaned_lines.append(line)
            i += 1
    
    result = '\n'.join(cleaned_lines)
    
    # Final cleanup: remove any remaining HTML tags (orphaned closing tags, etc.)
    if changed:
        result = remove_remaining_html(result)
    
    return result, changed

def remove_remaining_html(text):
    """Remove any remaining HTML tags including orphaned closing tags."""
    # Remove all HTML tags (opening, closing, self-closing)
    # This pattern matches: <tag>, </tag>, <tag/>, <tag attr="value">
    cleaned = re.sub(r'<[^>]+>', '', text)
    
    # Clean up excessive blank lines that may result from tag removal
    # Replace 3+ consecutive newlines with just 2
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    
    return cleaned

def has_unclosed_tags(text):
    """Check if text has unclosed HTML tags."""
    # Simple check for common unclosed tags
    opening_tags = len(re.findall(r'<(?:div|span|p|table|ul|ol)(?:\s|>|/)', text, re.IGNORECASE))
    closing_tags = len(re.findall(r'</(?:div|span|p|table|ul|ol)>', text, re.IGNORECASE))
    return opening_tags > closing_tags

def process_markdown_file(file_path):
    """
    Process a single markdown file to clean HTML.
    
    Args:
        file_path: Path to the markdown file
        
    Returns:
        True if file was modified, False otherwise
    """
    try:
        # Read the file
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Clean HTML from content
        cleaned_content, changed = clean_html_from_markdown(content)
        
        # Only write if changes were made
        if changed:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(cleaned_content)
            return True
        
        return False
        
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False

def main():
    """Main function to process all markdown files in knowledgebase."""
    knowledgebase_path = Path.home() / 'knowledgebase'
    
    if not knowledgebase_path.exists():
        print(f"Error: {knowledgebase_path} does not exist")
        return
    
    # Setup logging
    log_dir = Path.home() / 'logs'
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = log_dir / f'clean_html_from_markdown_{timestamp}.log'
    
    print(f"Scanning {knowledgebase_path} for markdown files with HTML...")
    print(f"Logging changes to: {log_file}")
    
    # Find all markdown files
    markdown_files = list(knowledgebase_path.rglob('*.md'))
    total_files = len(markdown_files)
    
    print(f"Found {total_files} markdown files to check")
    
    # Process each file
    modified_count = 0
    processed_count = 0
    
    with open(log_file, 'w', encoding='utf-8') as log:
        log.write(f"HTML Cleaning Log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log.write(f"Knowledgebase: {knowledgebase_path}\n")
        log.write(f"Total files to check: {total_files}\n")
        log.write("=" * 80 + "\n\n")
        
        for md_file in markdown_files:
            processed_count += 1
            
            # Show progress every 50 files
            if processed_count % 50 == 0:
                percentage = (processed_count / total_files) * 100
                print(f"Progress: {processed_count}/{total_files} ({percentage:.1f}%) - {modified_count} modified")
            
            if process_markdown_file(md_file):
                modified_count += 1
                relative_path = md_file.relative_to(knowledgebase_path)
                percentage = (processed_count / total_files) * 100
                print(f"[{percentage:.1f}%] Cleaned: {relative_path}")
                
                # Log the modified file
                log.write(f"[{datetime.now().strftime('%H:%M:%S')}] {relative_path}\n")
                log.flush()  # Ensure it's written immediately
        
        # Write summary to log
        log.write("\n" + "=" * 80 + "\n")
        log.write(f"\nSummary:\n")
        log.write(f"Total files checked: {total_files}\n")
        log.write(f"Files modified: {modified_count}\n")
        log.write(f"Files unchanged: {total_files - modified_count}\n")
        log.write(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    print(f"\nComplete!")
    print(f"Total files checked: {total_files}")
    print(f"Files modified: {modified_count}")
    print(f"Files unchanged: {total_files - modified_count}")

if __name__ == '__main__':
    main()
