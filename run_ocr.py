#!/usr/bin/env python3

import argparse
import os
import tempfile
import shutil
import subprocess
from custom_python_modules.myfuncs import logit

def process_file(input_file, output_file, in_place, logfile, debug, verbose):
    if not input_file.lower().endswith('.pdf'):
        if debug:
            logit(f"Skipped non-PDF file: {input_file}", logfile, debug)
        return
    
    if in_place:
        temp_file = tempfile.NamedTemporaryFile(delete=False).name
        result = subprocess.run(
            ['ocrmypdf', '--redo-ocr', input_file, temp_file],
            stdout=None if not verbose else subprocess.PIPE,
            stderr=None if not verbose else subprocess.PIPE
        )
        if result.stderr and debug:
            logit(result.stderr.decode(), logfile, debug)
        shutil.move(temp_file, input_file)
        logit(f"Processed and overwritten: {input_file}", logfile, debug)
    else:
        result = subprocess.run(
            ['ocrmypdf', '--redo-ocr', input_file, output_file],
            stdout=None if not verbose else subprocess.PIPE,
            stderr=None if not verbose else subprocess.PIPE
        )
        if result.stderr and not verbose:
            logit(result.stderr.decode(), logfile, debug)
        logit(f"Processed: {input_file} -> {output_file}", logfile, debug)
    
    print('.', end='', flush=True)

def main():
    parser = argparse.ArgumentParser(description="Run OCR on PDF files.")
    parser.add_argument('--input-folder', default=os.getcwd(), help="Input folder (default: current directory)")
    parser.add_argument('--input-file', help="Input file (optional)")
    parser.add_argument('--output-folder', default=None, help="Output folder (default: input folder)")
    parser.add_argument('--output-file', help="Output file (default: input file)")
    parser.add_argument('--verbose', action='store_true', help="Enable verbose output")
    parser.add_argument('--logfile', help="Log file")
    parser.add_argument('--debug', action='store_true', help="Enable debug mode")

    args = parser.parse_args()

    input_folder = args.input_folder
    input_file = args.input_file
    output_folder = args.output_folder or input_folder
    output_file = args.output_file
    verbose = args.verbose
    logfile = args.logfile
    debug = args.debug
    in_place = not args.output_folder

    if verbose or debug:
        print(f"input_folder: {input_folder}")
        print(f"input_file: {input_file}")
        print(f"output_folder: {output_folder}")
        print(f"output_file: {output_file}")
        print(f"verbose: {verbose}")
        print(f"logfile: {logfile}")
        print(f"debug: {debug}")
        print(f"in_place: {in_place}")

    logit("Script started", logfile, debug)

    if input_file:
        output_file = output_file or input_file
        process_file(os.path.join(input_folder, input_file), os.path.join(output_folder, output_file), in_place, logfile, debug, verbose)
    else:
        for file_name in os.listdir(input_folder):
            if file_name.lower().endswith('.pdf'):
                unique_output_file = args.output_file or file_name
                process_file(os.path.join(input_folder, file_name), os.path.join(output_folder, unique_output_file), in_place, logfile, debug, verbose)

    logit("Script ended", logfile, debug)

if __name__ == "__main__":
    main()
