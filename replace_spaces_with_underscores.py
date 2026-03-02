#!/usr/bin/env python3
"""
Script Name: replace_spaces_with_underscores.py
Description: Normalizes file and directory names recursively, merges conflicts,
             and moves directories without ebooks to a deleted-folder location.
Author: wwillett
Date: 2026-03-02
"""

import filecmp
import os
import re
import sys


TRAILING_GROUP_PATTERN = re.compile(r'_\([^\)]*\)$')
MULTI_UNDERSCORE_PATTERN = re.compile(r'_+')
DEFAULT_DELETED_FOLDER = '/mnt/data/deleted_ebook_folders'
EBOOK_EXTENSIONS = {
    '.epub', '.mobi', '.azw', '.azw3', '.pdf', '.txt', '.rtf', '.doc', '.docx',
    '.fb2', '.lit', '.prc', '.djvu', '.djv', '.cbz', '.cbr'
}


def strip_trailing_groups(name_part):
    previous = None
    current = name_part
    while previous != current:
        previous = current
        current = TRAILING_GROUP_PATTERN.sub('', current)
    return current


def normalize_name(name, is_file):
    normalized = name.replace(' ', '_').replace(',', '_').replace("'", '').replace('’', '')
    if is_file:
        base, ext = os.path.splitext(normalized)
        base = strip_trailing_groups(base)
        base = MULTI_UNDERSCORE_PATTERN.sub('_', base)
        return f"{base}{ext}"
    normalized = strip_trailing_groups(normalized)
    normalized = MULTI_UNDERSCORE_PATTERN.sub('_', normalized)
    return normalized


def unique_path(path):
    base, ext = os.path.splitext(path)
    index = 1
    candidate = f"{base}__dup{index}{ext}"
    while os.path.exists(candidate):
        index += 1
        candidate = f"{base}__dup{index}{ext}"
    return candidate


def move_file_with_conflict_handling(src_file, dst_file):
    if not os.path.exists(dst_file):
        os.rename(src_file, dst_file)
        return

    if os.path.isdir(dst_file):
        fallback = unique_path(dst_file)
        os.rename(src_file, fallback)
        return

    try:
        if filecmp.cmp(src_file, dst_file, shallow=False):
            os.remove(src_file)
            return
    except OSError:
        pass

    fallback = unique_path(dst_file)
    os.rename(src_file, fallback)


def merge_directories(src_dir, dst_dir):
    for item in os.listdir(src_dir):
        src_item = os.path.join(src_dir, item)
        dst_item = os.path.join(dst_dir, item)

        if os.path.isdir(src_item):
            if os.path.exists(dst_item):
                if os.path.isdir(dst_item):
                    merge_directories(src_item, dst_item)
                else:
                    fallback = unique_path(dst_item)
                    os.rename(src_item, fallback)
            else:
                os.rename(src_item, dst_item)
        else:
            move_file_with_conflict_handling(src_item, dst_item)

    if not os.listdir(src_dir):
        os.rmdir(src_dir)
    else:
        print(f"Warning: Could not remove '{src_dir}': not empty after merge.")


def move_non_ebook_folders(root_folder, deleted_folder):
    os.makedirs(deleted_folder, exist_ok=True)

    has_ebook = {}
    no_ebook_dirs = []

    for dirpath, dirnames, filenames in os.walk(root_folder, topdown=False):
        contains_ebook = any(
            os.path.splitext(filename)[1].lower() in EBOOK_EXTENSIONS
            for filename in filenames
        )

        if not contains_ebook:
            for dirname in dirnames:
                child_path = os.path.join(dirpath, dirname)
                if has_ebook.get(child_path, False):
                    contains_ebook = True
                    break

        has_ebook[dirpath] = contains_ebook
        if dirpath != root_folder and not contains_ebook:
            no_ebook_dirs.append(dirpath)

    no_ebook_set = set(no_ebook_dirs)
    top_level_candidates = []

    for directory in sorted(no_ebook_dirs, key=lambda path: path.count(os.sep)):
        parent = os.path.dirname(directory)
        has_no_ebook_ancestor = False
        while parent and parent != root_folder and parent != '/':
            if parent in no_ebook_set:
                has_no_ebook_ancestor = True
                break
            next_parent = os.path.dirname(parent)
            if next_parent == parent:
                break
            parent = next_parent

        if not has_no_ebook_ancestor:
            top_level_candidates.append(directory)

    moved_count = 0
    for source_dir in top_level_candidates:
        if not os.path.isdir(source_dir):
            continue

        destination_dir = os.path.join(deleted_folder, os.path.basename(source_dir))
        if os.path.exists(destination_dir):
            destination_dir = unique_path(destination_dir)

        os.rename(source_dir, destination_dir)
        moved_count += 1

    return moved_count

def replace_spaces_with_underscores(root_folder):
    for dirpath, dirnames, filenames in os.walk(root_folder, topdown=False):
        for filename in filenames:
            new_filename = normalize_name(filename, is_file=True)
            if new_filename != filename:
                old_path = os.path.join(dirpath, filename)
                new_path = os.path.join(dirpath, new_filename)
                move_file_with_conflict_handling(old_path, new_path)

        for dirname in dirnames:
            new_dirname = normalize_name(dirname, is_file=False)
            if new_dirname != dirname:
                old_dir = os.path.join(dirpath, dirname)
                new_dir = os.path.join(dirpath, new_dirname)
                if os.path.exists(new_dir):
                    if os.path.isdir(new_dir):
                        merge_directories(old_dir, new_dir)
                    else:
                        fallback = unique_path(new_dir)
                        os.rename(old_dir, fallback)
                else:
                    os.rename(old_dir, new_dir)

def main():
    if len(sys.argv) not in (2, 3):
        print(f"Usage: {sys.argv[0]} <folder> [deleted_folder]")
        sys.exit(1)

    folder = sys.argv[1]
    deleted_folder = sys.argv[2] if len(sys.argv) == 3 else DEFAULT_DELETED_FOLDER

    if not os.path.isdir(folder):
        print(f"Error: {folder} is not a valid directory.")
        sys.exit(1)

    replace_spaces_with_underscores(folder)
    moved_count = move_non_ebook_folders(folder, deleted_folder)
    print(f"Moved non-ebook folders: {moved_count}")

if __name__ == "__main__":
    main()
