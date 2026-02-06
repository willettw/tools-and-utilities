#!/usr/bin/env python3
"""
Script Name: merge_pdfs.py
Description: This script merges multiple PDF files into a single PDF file.
Author: Weston Willett
Date: 2023-10-06
"""

import argparse
from PyPDF2 import PdfMerger

# Parse command-line arguments
def parse_arguments():
    parser = argparse.ArgumentParser(description="Merge multiple PDF files into one.")
    parser.add_argument("--input", nargs='+', required=True, help="List of input PDF files to merge.")
    parser.add_argument("--output", required=True, help="Output PDF file name.")
    return parser.parse_args()

args = parse_arguments()

merger = PdfMerger()
for fname in args.input:
    merger.append(fname)
merger.write(args.output)
merger.close()
