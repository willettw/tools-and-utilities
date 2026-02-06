#!/usr/bin/env python3
"""
Script to copy the latest version of each file from ~/Documents/JoplinExport 
to ~/knowledgebase while preserving directory structure and removing version suffixes.
"""

import os
import pathlib
import shutil
import re
from collections import defaultdict

# Source and destination paths
source_path = pathlib.Path.home() / "Documents" / "JoplinExport"
dest_path = pathlib.Path.home() / "knowledgebase"

def get_base_name_and_version(filename):
    """
    Extract base name and version number from a filename.
    Examples:
        'note.md' -> ('note', 0)
        'note-1.md' -> ('note', 1)
        'note-42.md' -> ('note', 42)
    """
    match = re.match(r'^(.+?)-(\d+)(\.\w+)$', filename)
    if match:
        base_name = match.group(1) + match.group(3)
        version = int(match.group(2))
        return (base_name, version)
    else:
        # No version suffix, this is version 0 (original)
        return (filename, 0)

def find_all_files(base_path):
    """Find all files recursively."""
    for root, dirs, files in os.walk(base_path):
        for file in files:
            yield pathlib.Path(root) / file

# Group files by their relative path and base name
file_groups = defaultdict(list)

print("Scanning files in JoplinExport...")
for file_path in find_all_files(source_path):
    # Get relative path from source
    rel_path = file_path.relative_to(source_path)
    rel_dir = rel_path.parent
    
    # Get base name and version
    base_name, version = get_base_name_and_version(file_path.name)
    
    # Group key is (relative_directory, base_name)
    key = (rel_dir, base_name)
    file_groups[key].append((version, file_path))

print(f"Found {len(file_groups)} unique files with potential versions.")

# Process each group and copy the latest version
copied_count = 0
for (rel_dir, base_name), versions in file_groups.items():
    # Sort by version number and get the highest
    versions.sort(reverse=True, key=lambda x: x[0])
    latest_version, latest_file = versions[0]
    
    # Construct destination path preserving directory structure
    dest_file = dest_path / rel_dir / base_name
    
    # Create destination directory if needed
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Copy the file
    if dest_file.exists():
        print(f"Skipping (already exists): {rel_dir / base_name}")
    else:
        print(f"Copying: {rel_dir / base_name} (version {latest_version})")
        shutil.copy2(latest_file, dest_file)
        copied_count += 1

print(f"\nCopy complete! Copied {copied_count} files to {dest_path}")