#!/usr/bin/env python3
"""
find_most_recent_files.py

Searches for subdirectories named 'FULL' or 'DIFF' under /mnt/sqlbackups_nac,
and prints the path and file name of the most recent file in each, excluding specified folders.

Author: wwillett
Date: 2024-06
"""

import os

EXCLUDE_FOLDERS = {"master", "msdb", "model", "dbadmin","dbadmin_old","SSISDB","clarity_access_log","clarity_access_log_stage","msdb_old"}
def find_subdirs(root_path, target_names):
    matches = []
    for dirpath, dirnames, _ in os.walk(root_path):
        # Skip processing if any part of the path contains an excluded folder
        parts = set(os.path.normpath(dirpath).split(os.sep))
        if parts & EXCLUDE_FOLDERS:
            # Remove subdirs from dirnames to prevent descending further
            dirnames[:] = []
            continue
        for dirname in dirnames:
            if dirname in EXCLUDE_FOLDERS:
                # Prevent walking into excluded folders
                dirnames.remove(dirname)
                continue
            if dirname in target_names:
                matches.append(os.path.join(dirpath, dirname))
    return matches

def most_recent_file(folder, recursive=False):
    files = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(folder):
            # Skip excluded folders in subtrees
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_FOLDERS]
            for fname in filenames:
                files.append(os.path.join(dirpath, fname))
    else:
        files = [os.path.join(folder, f) for f in os.listdir(folder)
                 if os.path.isfile(os.path.join(folder, f))]
    if not files:
        return None
    return max(files, key=os.path.getmtime)

def get_var_name(path):
    # path example: /mnt/sqlbackups_nac/SRV-02-1215/clarity_access_log_hx/FULL/...
    parts = path.replace('/mnt/sqlbackups_nac/', '').split('/')
    if len(parts) < 4:
        return None
    server = parts[0].lower()
    db = parts[1].lower()
    typ = parts[2].lower()
    return f"@{db}_{typ}"

def main():
    root_paths = [
        "/mnt/sqlbackups_nac/SRV-02-1215",
        "/mnt/sqlbackups_nac/SRV-02-1217",
    ]
    for idx, root in enumerate(root_paths):
        subdirs = find_subdirs(root, {"FULL", "DIFF"})
        for subdir in subdirs:
            recursive = (root == "/mnt/sqlbackups_nac")
            recent = most_recent_file(subdir, recursive=recursive)
            if recent:
                win_path = recent.replace('/mnt', r'\\nac-nas-01').replace('/', '\\')
                var_name = get_var_name(recent)
                if var_name:
                    print(f"declare {var_name} varchar(255) = '{win_path}';")
        if idx < len(root_paths) - 1:
            print("\n")

if __name__ == "__main__":
    main()

