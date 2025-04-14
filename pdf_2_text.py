#!/usr/bin/env python3

"""
Script Name: pdf_2_text.py
Description: Extracts text from a PDF file and writes it to an output file or prints it to the console.
Author: wwillett
Date: 3/28/25
Usage: Run this script with the appropriate arguments to extract text from a PDF file.
Notes: Ensure the required Python libraries are installed.
"""

import argparse
import pdfplumber
import sys
from pathlib import Path
import warnings
import os

# Add the path to myfuncs
sys.path.append("/home/wwillett/repos/scripts/custom_python_modules")
from myfuncs import logit


def clean_text(text):
    """Clean the extracted text by removing lines with 'EpicUUID:' and replacing GUIDs."""
    import re
    cleaned_lines = []
    for line in text.splitlines():
        if "EpicUUID:" in line:
            continue  # Skip lines containing "EpicUUID:"
        if re.match(r"^Caboodle Developer's Guide \d+$", line.strip()):
            continue  # Skip lines with 'Caboodle Developer's Guide' followed by a page number
        if line.strip().startswith(tuple("0123456789abcdefABCDEF")) and len(line.strip()) == 36:
            cleaned_lines.append("\n")  # Replace GUIDs with a newline
        else:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def extract_text(infile, outfile=None, verbose=False):
    """Extract text from a PDF file."""
    try:
        # Suppress warnings from pdfplumber and redirect stderr
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with open(os.devnull, "w") as devnull:
                with pdfplumber.open(infile) as pdf:
                    text = ""
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if verbose:
                            logit(f"Extracted text from page {page.page_number}", None, False, verbose)
                        text += page_text + "\n"
        
        # Clean the extracted text
        text = clean_text(text)
        
        if outfile:
            with open(outfile, "w") as f:
                f.write(text)
            logit(f"Text written to {outfile}", None, False, verbose)
        else:
            print(text)
    except Exception as e:
        logit(f"Error processing file {infile}: {e}", None, False, verbose)


def main():
    """Main function to parse arguments and execute the script."""
    parser = argparse.ArgumentParser(description="Extract text from a PDF file.")
    parser.add_argument(
        "-i", "--infile", required=False, default="/home/wwillett/Downloads/Caboodle Developer's Guide.pdf",
        help="Path to the input PDF file."
    )
    parser.add_argument(
        "-o", "--outfile", required=False, default="/tmp/Caboodle_Developers_Guide.txt",
        help="Path to the output text file."
    )
    parser.add_argument("-l", "--logfile", help="Path to the log file.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output.")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug mode.")

    try:
        args = parser.parse_args()
    except SystemExit:
        logit("Error parsing arguments. Please check your input.", None, args.debug, args.verbose)
        return

    # Debugging: Print parsed arguments if debug mode is enabled
    if args.debug:
        logit(f"Parsed arguments: {args}", None, args.debug, args.verbose)

    # Validate input file
    infile_path = Path(args.infile)
    if not infile_path.is_file():
        logit(f"Input file {args.infile} does not exist.", None, args.debug, args.verbose)
        sys.exit(1)

    # Validate output file
    if args.outfile:
        outfile_path = Path(args.outfile)
        if outfile_path.exists():
            response = input(f"Output file {args.outfile} already exists. Overwrite? (y/n): ").strip().lower()
            if response != 'y':
                logit("Operation canceled by the user.", None, args.debug, args.verbose)
                sys.exit(0)

    # Configure logging
    if args.logfile:
        logit(f"Logging to {args.logfile}", args.logfile, args.debug, args.verbose)

    if args.debug:
        logit("Debug mode enabled", None, args.debug, args.verbose)

    # Extract text
    extract_text(args.infile, args.outfile, args.verbose)


if __name__ == "__main__":
    main()
