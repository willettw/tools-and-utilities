#!/usr/bin/env python3
"""
organize_ebooks.py
Organizes and inventories ebooks in a library folder.
Author: wwillett
Date: 2026-02-27
Description: Recursively scans a library folder, compiles an inventory of ebooks, extracts metadata, and logs actions using logit from custom_python_modules.
"""

import os
import sys
import yaml
import csv
sys.path.insert(0, '/usr/lib/custom_python_modules')
from myfuncs import logit

import argparse

# Supported ebook formats
EBOOK_FORMATS = ['epub', 'rtf', 'doc', 'docx', 'pdf', 'mobi', 'azw3', 'txt']

# Argument parsing
parser = argparse.ArgumentParser(description='Organize and inventory ebooks.')
parser.add_argument('--verbose', action='store_true', default=False, help='Print all logged messages to stdout')
parser.add_argument('--debug', action='store_true', default=False, help='Print all messages to stdout')
parser.add_argument('--logfile', type=str, default='/home/wwillett/logs/', help='Logfile location')
parser.add_argument('--library', type=str, help='Root folder to begin processing')
parser.add_argument('--inventory', type=str, help='File for inventory of library contents')
parser.add_argument('--config', type=str, default='organize_ebooks.yml', help='YAML config file')

args = parser.parse_args()


# Load YAML config: check current directory first, then fallback
config_path = args.config if args.config else 'organize_ebooks.yml'
if not os.path.exists(config_path):
    config_path = '/usr/local/etc/organize_ebooks.yml'
if os.path.exists(config_path):
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
else:
    config = {}

# Use YAML defaults if args not provided
library = args.library if args.library else config.get('library')
inventory = args.inventory if args.inventory else config.get('inventory')
logdir = args.logfile if args.logfile else config.get('logfile', '/home/wwillett/logs/')
script_basename = os.path.splitext(os.path.basename(__file__))[0]
logfile = os.path.join(logdir, script_basename + '.log')
verbose = args.verbose if args.verbose else config.get('verbose', False)
debug = args.debug if args.debug else config.get('debug', False)

# Setup logging
log = logit(logfile=logfile, verbose=verbose, debug=debug)

# Verify library folder exists
if not library or not os.path.isdir(library):
    log.error(f"Library folder '{library}' does not exist or not specified.")
    sys.exit(1)

# Inventory headers
HEADERS = ['Title', 'Author', 'Series', 'Number', 'filename', 'folder', 'comment']

# Helper: extract metadata from filename/folder

def extract_metadata(path):
    # Example: "Author - Series - Number - Title.ext" or "Author/Series/Number/Title.ext"
    basename = os.path.basename(path)
    folder = os.path.dirname(path)
    title, author, series, number = '', '', '', ''
    comment = ''
    parts = basename.split(' - ')
    if len(parts) == 4:
        author, series, number, title = parts
    elif len(parts) == 3:
        author, series, title = parts
    elif len(parts) == 2:
        author, title = parts
    else:
        title = basename
        comment = 'Could not parse metadata'
    return title, author, series, number, basename, folder, comment

# Helper: check if folder is single ebook

def is_single_ebook_folder(folder):
    files = os.listdir(folder)
    ebook_files = [f for f in files if f.split('.')[-1].lower() in EBOOK_FORMATS]
    if len(ebook_files) == 1:
        return True
    return False

inventory_rows = []
for root, dirs, files in os.walk(library):
    # Check if folder is single ebook
    if is_single_ebook_folder(root):
        ebook_file = [f for f in files if f.split('.')[-1].lower() in EBOOK_FORMATS][0]
        path = os.path.join(root, ebook_file)
        metadata = extract_metadata(root)
        inventory_rows.append(metadata)
    else:
        for f in files:
            ext = f.split('.')[-1].lower()
            if ext in EBOOK_FORMATS:
                path = os.path.join(root, f)
                metadata = extract_metadata(path)
                inventory_rows.append(metadata)

# Write inventory.csv
with open(inventory, 'w', newline='') as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(HEADERS)
    for row in inventory_rows:
        writer.writerow(row)

logit(f"Inventory written to {inventory}", logfile=logfile, debug=debug, verbose=verbose)


# Validate and enrich inventory
with open(inventory, 'r') as csvfile:
    reader = csv.DictReader(csvfile)
    rows = list(reader)


def try_extract_fields(row):
    # Try to extract missing fields from filename and folder
    filename = row['filename']
    folder = row['folder']
    basename = os.path.basename(filename)
    foldername = os.path.basename(folder)
    # Special handling for Amber Short stories
    if 'Amber Short' in basename:
        row['Author'] = 'Zelazny, Roger'
        row['Series'] = 'Amber'
        # Title is last part after ' - '
        parts = basename.split(' - ')
        if len(parts) > 1:
            row['Title'] = parts[-1].split('(')[0].strip()
        return row
    # Patterns: "Author - Series - Number - Title", "Author - Series - Title", "Author - Title"
    parts = basename.split(' - ')
    if not row['Author'] and len(parts) > 0:
        row['Author'] = parts[0].replace(',', '').strip()
    if not row['Series'] and len(parts) > 2:
        row['Series'] = parts[1].strip()
    if not row['Number'] and len(parts) > 2:
        # Try to extract number from second or third part
        for p in parts:
            if p.strip().isdigit():
                row['Number'] = p.strip()
                break
        if not row['Number'] and len(parts) > 2:
            # Try to extract number from foldername
            for token in foldername.split():
                if token.isdigit():
                    row['Number'] = token
                    break
    if not row['Title'] and len(parts) > 1:
        row['Title'] = parts[-1].strip()
    # Try to extract from folder if still missing
    if not row['Title']:
        row['Title'] = foldername
    return row

for row in rows:
    row = try_extract_fields(row)

import re
from ebooklib import epub
import PyPDF2
def normalize_author(name):
    # Lowercase, remove punctuation, split into words, sort for order-insensitive match
    if not name:
        return []
    name = re.sub(r'[^a-zA-Z0-9 ]', '', name.lower())
    return sorted(name.split())

def remove_number_tag(value):
    # Remove '(###)' if ### > 100
    if value:
        match = re.search(r'\((\d{3,})\)$', value.strip())
        if match:
            num = int(match.group(1))
            if num > 100:
                value = re.sub(r'\(\d{3,}\)$', '', value).strip()
    return value

def remove_seagate_tag(value):
    # Remove 'P__Seagate FreeAgentDesktop_Documents_Cali' from value
    if value:
        return value.replace('P__Seagate FreeAgentDesktop_Documents_Cali', '').strip()
    return value


    # Clean Author and Title fields
    row['Author'] = remove_seagate_tag(remove_number_tag(row['Author']))
    row['Title'] = remove_seagate_tag(remove_number_tag(row['Title']))

    missing = []
    if not row['Title']:
        missing.append('Title')
    if not row['Author']:
        missing.append('Author')
    if not row['Series']:
        missing.append('Series')
    if not row['Number']:
        missing.append('Number')
    if missing:
        row = try_extract_fields(row)
        # Check again after extraction
        still_missing = []
        for field in missing:
            if not row[field]:
                still_missing.append(field)
        if still_missing:
            row['comment'] = f"Missing or unparseable: {', '.join(still_missing)}"
        else:
            row['comment'] = f"Fields auto-extracted: {', '.join(missing)}"
    else:
        row['comment'] = row.get('comment', '')

known_authors = config.get('known_authors', [])
normalized_known_authors = [normalize_author(a) for a in known_authors]
for row in rows:
    title_norm = normalize_author(row['Title'])
    for author, author_norm in zip(known_authors, normalized_known_authors):
        # If all words in known author are in the title (order-insensitive)
        if author_norm and all(word in title_norm for word in author_norm):
            # Swap Title and Author
            row['Title'], row['Author'] = row['Author'], row['Title']
            row['comment'] = row.get('comment', '') + ' | Swapped Title and Author due to known author match'
            break

# Final step: update ebook metadata for each row
def update_epub_metadata(filepath, title, author, series, number):
    try:
        book = epub.read_epub(filepath)
        changed = False
        if title:
            book.set_title(title)
            changed = True
        if author:
            book.set_authors([author])
            changed = True
        if series:
            book.add_metadata('DC', 'series', series)
            changed = True
        if number:
            book.add_metadata('DC', 'series_index', str(number))
            changed = True
        if changed:
            epub.write_epub(filepath, book)
        return changed, None
    except Exception as e:
        return False, str(e)

def update_pdf_metadata(filepath, title, author):
    try:
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            writer = PyPDF2.PdfWriter()
            writer.append_pages_from_reader(reader)
            info = reader.metadata or {}
            if title:
                writer.add_metadata({'/Title': title})
            if author:
                writer.add_metadata({'/Author': author})
            # PyPDF2 does not support custom fields for series/number
            with open(filepath, 'wb') as out_f:
                writer.write(out_f)
        return True, None
    except Exception as e:
        return False, str(e)

for row in rows:
    filename = row['filename']
    ext = filename.split('.')[-1].lower()
    fullpath = os.path.join(row['folder'], filename)
    changed = False
    error = None
    if ext == 'epub':
        changed, error = update_epub_metadata(fullpath, row['Title'], row['Author'], row['Series'], row['Number'])
    elif ext == 'pdf':
        changed, error = update_pdf_metadata(fullpath, row['Title'], row['Author'])
    # Add more formats as needed
    if changed:
        logit(f"Updated metadata for {fullpath}: Title='{row['Title']}', Author='{row['Author']}', Series='{row['Series']}', Number='{row['Number']}'", logfile=logfile, debug=debug, verbose=verbose)
    elif error:
        logit(f"Failed to update metadata for {fullpath}: {error}", logfile=logfile, debug=debug, verbose=verbose)

# Rewrite inventory with comments
with open(inventory, 'w', newline='') as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=HEADERS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

logit("Inventory validation and enrichment complete.", logfile=logfile, debug=debug, verbose=verbose)
