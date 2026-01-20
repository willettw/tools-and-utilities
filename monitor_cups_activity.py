#!/usr/bin/env python3
"""
monitor_cups_activity.py - Monitor and report CUPS print activity

PURPOSE:
    Collects print job activity by printer and user on RHEL 8+ systems.
    Generates CSV reports and optionally emails results to specified recipients.
    Works with syslog-based CUPS logging.

USAGE:
    monitor_cups_activity.py [OPTIONS]

OPTIONS:
    --config FILE        Configuration file (default: monitor_cups_activity.yml)
    --output FILE        Output CSV file path
    --hours N           Hours back to monitor (default: 24)
    --email ADDRESS     Email recipient for results
    --verbose           Enable verbose output
    --debug             Enable debug output (implies verbose)
    --dry-run           Show what would be done without executing
    --help              Show this help message

EXAMPLES:
    # Run with default settings
    monitor_cups_activity.py

    # Run with custom time period and email
    monitor_cups_activity.py --hours 48 --email admin@company.com

    # Debug mode with verbose output
    monitor_cups_activity.py --debug --dry-run

EXIT CODES:
    0 = Success
    1 = Error (missing dependencies, invalid config, etc.)
    2 = Warning (partial success, some data missing)

VERSION: 2.0.0
AUTHOR: wwillett@institute.org
"""

import argparse
import csv
import logging
import os
import re
import smtplib
import socket
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Dict, List, Tuple, Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# Script information
SCRIPT_NAME = Path(__file__).name
SCRIPT_VERSION = "2.0.0"

# Default configuration
DEFAULT_CONFIG_LOCATIONS = [
    "/usr/local/etc/monitor_cups_activity.yml",
    "/etc/monitor_cups_activity.yml",
    "/etc/cups/monitor_cups_activity.yml",
    Path.home() / ".config/monitor_cups_activity/config.yml",
    Path(__file__).parent / "monitor_cups_activity.yml",
]

DEFAULT_OUTPUT_FILE = "/home/wwillett/logs/print_activity.csv"
DEFAULT_LOG_FILE = "/home/wwillett/logs/monitor_cups_activity.log"
DEFAULT_TIME_PERIOD = 24
DEFAULT_EMAIL = "wwillett@institute.org"
DEFAULT_TEMP_DIR = "/tmp"
DEFAULT_SYSLOG_FILE = "/var/log/messages"

# CUPS settings
CUPS_CONFIG = "/etc/cups/cups-files.conf"
CUPS_PAGE_LOG = "/var/log/cups/page_log"
CUPS_SERVICE = "cups"


class CUPSMonitor:
    """Main class for monitoring CUPS print activity."""
    
    def __init__(self):
        self.config_file: Optional[str] = None
        self.output_file: str = DEFAULT_OUTPUT_FILE
        self.log_file: str = DEFAULT_LOG_FILE
        self.time_period_hours: int = DEFAULT_TIME_PERIOD
        self.start_date: Optional[datetime] = None
        self.end_date: Optional[datetime] = None
        self.email_recipient: Optional[str] = DEFAULT_EMAIL
        self.temp_dir: str = DEFAULT_TEMP_DIR
        self.verbose: bool = False
        self.debug: bool = False
        self.dry_run: bool = False
        self.stdout_mode: bool = False
        self.syslog_file: str = DEFAULT_SYSLOG_FILE
        
        # IRIS database settings
        self.iris_instance: str = "poc"
        self.iris_namespace: str = "poc"
        self.iris_routine: str = "EPRInfo^ZwwUtilities"
        
        # Email settings
        self.email_subject: str = f"CUPS Print Activity Report - {socket.gethostname()}"
        self.attach_csv: bool = True
        self.include_summary: bool = True
        
        # Logging
        self.logger: logging.Logger = logging.getLogger(SCRIPT_NAME)
        
    def setup_logging(self):
        """Configure logging based on settings."""
        # Set logger level
        self.logger.setLevel(logging.DEBUG if self.debug else logging.INFO)
        
        # Clear any existing handlers
        self.logger.handlers.clear()
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        if self.debug:
            console_handler.setLevel(logging.DEBUG)
        elif self.verbose:
            console_handler.setLevel(logging.INFO)
        else:
            console_handler.setLevel(logging.WARNING)
        
        console_format = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s',
                                          datefmt='%Y-%m-%d %H:%M:%S')
        console_handler.setFormatter(console_format)
        self.logger.addHandler(console_handler)
        
        # File handler
        if self.log_file:
            try:
                log_dir = Path(self.log_file).parent
                log_dir.mkdir(parents=True, exist_ok=True)
                
                file_handler = logging.FileHandler(self.log_file)
                file_handler.setLevel(logging.DEBUG)
                file_format = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s',
                                               datefmt='%Y-%m-%d %H:%M:%S')
                file_handler.setFormatter(file_format)
                self.logger.addHandler(file_handler)
            except Exception as e:
                print(f"Warning: Could not create log file {self.log_file}: {e}", file=sys.stderr)
    
    def load_yaml_config(self, config_file: str) -> bool:
        """Load configuration from YAML file."""
        if not os.path.isfile(config_file):
            self.logger.warning(f"Configuration file not found: {config_file}")
            self.logger.info("Using default configuration values")
            return True
        
        self.logger.info(f"Using configuration file: {config_file}")
        self.logger.debug(f"Loading configuration from: {config_file}")
        
        if not HAS_YAML:
            self.logger.warning("PyYAML not installed, using basic parsing")
            return self._load_yaml_basic(config_file)
        
        try:
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            
            if not config or 'defaults' not in config:
                self.logger.warning("Invalid config format, using defaults")
                return True
            
            defaults = config['defaults']
            
            # Load settings from config (these will be overridden by command-line args later if provided)
            self.output_file = defaults.get('output_file', self.output_file)
            self.time_period_hours = int(defaults.get('time_period_hours', self.time_period_hours))
            self.logger.debug(f"Loaded time_period_hours from config: {self.time_period_hours}")
            self.log_file = defaults.get('log_file', self.log_file)
            self.temp_dir = defaults.get('temp_dir', self.temp_dir)
            
            # Date range settings
            if 'start_date' in defaults and defaults['start_date']:
                try:
                    self.start_date = datetime.strptime(defaults['start_date'], '%Y-%m-%d')
                    self.logger.debug(f"Loaded start_date from config: {self.start_date}")
                except ValueError as e:
                    self.logger.warning(f"Invalid start_date in config: {e}")
            
            if 'end_date' in defaults and defaults['end_date']:
                try:
                    self.end_date = datetime.strptime(defaults['end_date'], '%Y-%m-%d')
                    self.end_date = self.end_date.replace(hour=23, minute=59, second=59)
                    self.logger.debug(f"Loaded end_date from config: {self.end_date}")
                except ValueError as e:
                    self.logger.warning(f"Invalid end_date in config: {e}")
            
            # IRIS settings
            if 'iris' in defaults:
                iris_cfg = defaults['iris']
                self.iris_instance = iris_cfg.get('instance', self.iris_instance)
                self.iris_namespace = iris_cfg.get('namespace', self.iris_namespace)
                self.iris_routine = iris_cfg.get('routine', self.iris_routine)
            
            # Email settings
            if 'email' in defaults:
                email_cfg = defaults['email']
                self.email_recipient = email_cfg.get('recipient', self.email_recipient)
                subject = email_cfg.get('subject', self.email_subject)
                # Expand $(hostname) in subject line
                subject = subject.replace('$(hostname)', socket.gethostname())
                self.email_subject = subject
                self.attach_csv = email_cfg.get('attach_csv', True)
                self.include_summary = email_cfg.get('include_summary_in_body', True)
            
            # Boolean flags (if not set by command line)
            if not self.debug:
                self.debug = defaults.get('debug', False)
            if not self.verbose:
                self.verbose = defaults.get('verbose', False)
            if not self.dry_run:
                self.dry_run = defaults.get('dry_run', False)
            
            self.logger.debug("Configuration loaded successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error loading config: {e}")
            return False
    
    def _load_yaml_basic(self, config_file: str) -> bool:
        """Basic YAML parsing without PyYAML."""
        try:
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if ':' not in line or line.startswith('#'):
                        continue
                    
                    if 'output_file:' in line and self.output_file == DEFAULT_OUTPUT_FILE:
                        self.output_file = line.split(':', 1)[1].strip().strip('"\'')
                    elif 'time_period_hours:' in line and self.time_period_hours == DEFAULT_TIME_PERIOD:
                        try:
                            self.time_period_hours = int(line.split(':', 1)[1].strip())
                        except ValueError:
                            pass
                    elif 'log_file:' in line and self.log_file == DEFAULT_LOG_FILE:
                        self.log_file = line.split(':', 1)[1].strip().strip('"\'')
            
            return True
        except Exception as e:
            self.logger.error(f"Error in basic config parsing: {e}")
            return False
    
    def check_dependencies(self) -> bool:
        """Check for required dependencies."""
        # Check if syslog file exists
        if not os.path.isfile(self.syslog_file):
            self.logger.error(f"Syslog file not found: {self.syslog_file}")
            self.logger.error("Please specify a valid syslog file with --syslog option")
            return False
        
        # Check if we have read permissions
        if not os.access(self.syslog_file, os.R_OK):
            self.logger.error(f"No read permission for: {self.syslog_file}")
            self.logger.error(f"Try running with: sudo python3 {__file__}")
            self.logger.error(f"Or specify a readable log file with --syslog option")
            return False
        
        return True
    
    def collect_syslog_messages(self) -> Dict[Tuple[str, str, str], int]:
        """
        Collect CUPS logs from /var/log/messages.
        
        Returns:
            Dictionary with (printer, user, date) tuples as keys and job counts as values.
        """
        # Determine time range
        if self.start_date and self.end_date:
            time_start = self.start_date
            time_end = self.end_date
            period_desc = f"{time_start.strftime('%Y-%m-%d')} to {time_end.strftime('%Y-%m-%d')}"
        else:
            time_end = datetime.now()
            time_start = time_end - timedelta(hours=self.time_period_hours)
            period_desc = f"last {self.time_period_hours} hours"
        
        self.logger.debug(f"Collecting CUPS logs from {self.syslog_file} ({period_desc})")
        
        if self.dry_run:
            self.logger.info(f"DRY RUN: Would collect logs from {self.syslog_file}")
            return {("dry-run-printer", "dry-run-user", "2025-11-07"): 5}
        
        self.logger.debug(f"Time range: {time_start} to {time_end}")
        
        print_jobs: Dict[Tuple[str, str, str], int] = defaultdict(int)
        parse_errors = 0
        lines_processed = 0
        
        try:
            with open(self.syslog_file, 'r') as f:
                for line in f:
                    # Skip if not CUPS related
                    if 'cupsd' not in line.lower():
                        continue
                    
                    lines_processed += 1
                    
                    # Parse timestamp (format: Nov  6 16:54:17 or Nov  2 13:43:25)
                    try:
                        # Extract month, day, time
                        parts = line.split()
                        if len(parts) < 3:
                            continue
                        
                        month_str = parts[0]
                        day_str = parts[1]
                        time_str = parts[2]
                        
                        # Build datetime (use current year, adjust if needed)
                        current_year = datetime.now().year
                        # Use single space - strptime handles extra whitespace
                        timestamp_str = f"{current_year} {month_str} {day_str} {time_str}"
                        log_time = datetime.strptime(timestamp_str, "%Y %b %d %H:%M:%S")
                        
                        # Adjust year if log date is in the future (crossed year boundary)
                        if log_time > datetime.now():
                            log_time = log_time.replace(year=current_year - 1)
                        
                        # Skip if outside time range
                        if log_time < time_start or log_time > time_end:
                            continue
                            
                        # Get the date string for this log entry
                        log_date = log_time.strftime('%Y-%m-%d')
                        
                    except (ValueError, IndexError) as e:
                        # If we can't parse timestamp, skip the line
                        parse_errors += 1
                        if parse_errors <= 5:
                            self.logger.debug(f"Failed to parse timestamp: {line[:50]}... Error: {e}")
                        continue
                    
                    # Look for REQUEST lines with POST /printers/
                    if 'REQUEST' in line and 'POST /printers/' in line:
                        # Extract printer name
                        match = re.search(r'POST /printers/(\S+)', line)
                        if match:
                            printer = match.group(1)
                            user = "localhost"  # Default user
                            
                            # Count Create-Job as a new print job
                            if 'Create-Job' in line:
                                print_jobs[(printer, user, log_date)] += 1
                                self.logger.debug(f"Found print job: {printer} by {user} on {log_date}")
        
        except Exception as e:
            self.logger.error(f"Error reading syslog: {e}")
            return {}
        
        self.logger.debug(f"Processed {lines_processed} CUPS log lines")
        if parse_errors > 0:
            self.logger.debug(f"Timestamp parse errors: {parse_errors}")
        self.logger.debug(f"Collected {len(print_jobs)} unique printer/user/date combinations")
        total_jobs = sum(print_jobs.values())
        self.logger.debug(f"Total jobs: {total_jobs}")
        
        if not print_jobs:
            self.logger.warning(f"No print job entries found in {self.syslog_file} for {period_desc}")
        
        return print_jobs
    
    def collect_file_logs(self) -> Dict[Tuple[str, str, str], int]:
        """Collect CUPS logs from file-based logging (legacy)."""
        self.logger.debug(f"Collecting CUPS logs from file: {CUPS_PAGE_LOG}")
        
        if not os.path.isfile(CUPS_PAGE_LOG):
            self.logger.error(f"CUPS page log not found: {CUPS_PAGE_LOG}")
            return {}
        
        if self.dry_run:
            self.logger.info(f"DRY RUN: Would collect file logs from: {CUPS_PAGE_LOG}")
            return {("dry-run-printer", "dry-run-user", "2025-11-07"): 3}
        
        print_jobs: Dict[Tuple[str, str, str], int] = defaultdict(int)
        
        try:
            with open(CUPS_PAGE_LOG, 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 5:
                        printer = parts[0]
                        user = parts[1]
                        # For file-based logs, use current date as we don't have timestamp info
                        date = datetime.now().strftime('%Y-%m-%d')
                        print_jobs[(printer, user, date)] += 1
        
        except Exception as e:
            self.logger.error(f"Error reading page log: {e}")
            return {}
        
        self.logger.debug(f"Collected {len(print_jobs)} entries from file log")
        return print_jobs
    
    def get_epr_info(self, printer: str) -> List[Tuple[str, str, str]]:
        """
        Get EPR information from IRIS for a printer.
        
        Args:
            printer: Printer name
            
        Returns:
            List of tuples (EPR_ID, EPR_Name, Default_Command) for all EPR entries.
            If multiple EPR entries exist (MAIN, ALT, OPT), returns all of them.
        """
        if self.dry_run:
            return [("DRY-001", "Dry Run Printer", "DRY-CMD")]
        
        # Build IRIS command using echo and pipe to pass the command to irissession
        # This is needed because irissession doesn't handle complex commands well as arguments
        iris_routine_call = f'd {self.iris_routine}("{printer}")'
        cmd = f'echo \'{iris_routine_call}\' | irissession {self.iris_instance} -U{self.iris_namespace}'
        
        self.logger.debug(f"Getting EPR info for printer: {printer}")
        self.logger.debug(f"Command: {cmd}")
        
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                universal_newlines=True
            )
            
            if result.returncode != 0:
                self.logger.warning(f"IRIS command failed for {printer}: {result.stderr.strip()}")
                return []
            
            # Parse output - expected format (whitespace-separated):
            # EPR_ID    EPR_Name    Default_Command
            # Example: 240590    PTR-WAL-121-059-MAIN    /epic/bin/print.ksh '/usr/bin/lp -dUFH-WL-059' '\033&l1H'
            # May return multiple rows (MAIN, ALT, OPT) - we return all of them
            output = result.stdout.strip()
            if not output:
                self.logger.debug(f"No EPR info found for {printer}")
                return []
            
            self.logger.debug(f"Raw IRIS output for {printer}: {repr(output)}")
            
            # Process all non-empty lines
            epr_entries = []
            lines = output.split('\n')
            self.logger.debug(f"IRIS output has {len(lines)} lines")
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Skip lines that look like IRIS prompts or system info
                if line.startswith('PRD>') or line.startswith('USER>') or '>' in line[:10]:
                    self.logger.debug(f"Skipping prompt line: {line}")
                    continue
                
                # Skip IRIS system info lines
                if line.startswith('Node:') or line.startswith('Instance:'):
                    self.logger.debug(f"Skipping system info line: {line}")
                    continue
                
                # Split on whitespace, limiting to 3 parts (EPR_ID, EPR_Name, and rest is Default_Command)
                parts = line.split(None, 2)
                self.logger.debug(f"Line split into {len(parts)} parts: {parts[:2] if len(parts) >= 2 else parts}")
                
                if len(parts) >= 3:
                    epr_id = parts[0].strip()
                    epr_name = parts[1].strip()
                    default_cmd = parts[2].strip()
                    epr_entries.append((epr_id, epr_name, default_cmd))
                    self.logger.debug(f"EPR info for {printer}: ID={epr_id}, Name={epr_name}, Cmd={default_cmd}")
                else:
                    self.logger.debug(f"Skipping incomplete line ({len(parts)} parts): {line}")
            
            if not epr_entries:
                self.logger.warning(f"No valid EPR info found for {printer}")
            else:
                self.logger.debug(f"Found {len(epr_entries)} EPR entries for {printer}")
            
            return epr_entries
                
        except subprocess.TimeoutExpired:
            self.logger.warning(f"Timeout getting EPR info for {printer}")
            return []
        except FileNotFoundError:
            self.logger.warning("irissession command not found - EPR info will not be available")
            return []
        except Exception as e:
            self.logger.warning(f"Error getting EPR info for {printer}: {e}")
            return []
    
    def detect_cups_logging_method(self) -> bool:
        """
        Detect CUPS logging method.
        
        Returns:
            True if syslog-based, False if file-based
        """
        self.logger.debug("Detecting CUPS logging method")
        
        # Check config file
        if os.path.isfile(CUPS_CONFIG):
            try:
                with open(CUPS_CONFIG, 'r') as f:
                    if any('AccessLog' in line and 'syslog' in line for line in f):
                        self.logger.info("Detected syslog-based CUPS logging")
                        return True
            except Exception:
                pass
        
        # Check if page_log has redirect message
        if os.path.isfile(CUPS_PAGE_LOG):
            try:
                with open(CUPS_PAGE_LOG, 'r') as f:
                    content = f.read(500)  # Read first 500 chars
                    if 'moved into' in content.lower() and 'syslog' in content.lower():
                        self.logger.info("Detected syslog-based CUPS logging (redirected)")
                        return True
            except Exception:
                pass
        
        # Default to syslog on modern systems
        self.logger.info("Defaulting to syslog-based logging")
        return True
    
    def generate_summary(self, print_jobs: Dict[Tuple[str, str, str], int], output_file: str):
        """Generate print activity summary CSV."""
        self.logger.debug("Generating print activity summary")
        
        if self.dry_run:
            self.logger.info(f"DRY RUN: Would generate summary to: {output_file if not self.stdout_mode else 'stdout'}")
            return
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Determine period description
        if self.start_date and self.end_date:
            period_desc = f"{self.start_date.strftime('%Y-%m-%d')} to {self.end_date.strftime('%Y-%m-%d')}"
        else:
            period_desc = f"Last {self.time_period_hours} hours"
        
        # Log summary to log file
        if print_jobs:
            # Count total jobs and unique printers
            total_jobs = sum(print_jobs.values())
            unique_printers = len(set(printer for printer, user, date in print_jobs.keys()))
            unique_dates = len(set(date for printer, user, date in print_jobs.keys()))
            
            # Aggregate totals and most recent date by printer across all dates
            # Also get EPR info for each printer
            printer_totals: Dict[str, int] = defaultdict(int)
            printer_most_recent: Dict[str, str] = {}
            printer_epr_info: Dict[str, List[Tuple[str, str, str]]] = {}
            
            for (printer, user, date), count in print_jobs.items():
                printer_totals[printer] += count
                # Update most recent date for this printer
                if printer not in printer_most_recent or date > printer_most_recent[printer]:
                    printer_most_recent[printer] = date
                # Get EPR info (only once per printer)
                if printer not in printer_epr_info:
                    printer_epr_info[printer] = self.get_epr_info(printer)
            
            self.logger.info(f"=== CUPS Print Activity Summary ({timestamp}) ===")
            self.logger.info(f"Monitoring period: {period_desc}")
            self.logger.info(f"Host: {socket.gethostname()}")
            self.logger.info(f"Total print jobs: {total_jobs}")
            self.logger.info(f"Unique printers: {unique_printers}")
            self.logger.info(f"Date range in data: {unique_dates} day(s)")
            self.logger.info("")
            self.logger.info("=== Printer Totals (Sorted by Job Count) ===")
            for printer in sorted(printer_totals.keys(), key=lambda p: printer_totals[p], reverse=True):
                self.logger.info(f"{printer}: {printer_totals[printer]}")
            
            # Output CSV data
            if self.stdout_mode:
                # Print to stdout
                print("printer,most_recent_date,total_jobs,EPR_ID,EPR_Name,Default_Command")
                for printer in sorted(printer_totals.keys()):
                    most_recent = printer_most_recent[printer]
                    total = printer_totals[printer]
                    epr_entries = printer_epr_info.get(printer, [])
                    
                    if epr_entries:
                        # Print one row per EPR entry
                        for epr_id, epr_name, default_cmd in epr_entries:
                            print(f"{printer},{most_recent},{total},{epr_id},{epr_name},{default_cmd}")
                    else:
                        # No EPR entries, print one row with empty EPR fields
                        print(f"{printer},{most_recent},{total},,,")
            else:
                # Write to CSV file
                try:
                    # Ensure output directory exists
                    output_path = Path(output_file)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Write/overwrite file with current data
                    with open(output_file, 'w', newline='') as f:
                        writer = csv.writer(f, delimiter=' ')
                        
                        # Write header
                        writer.writerow(['printer', 'most_recent_date', 'total_jobs', 'EPR_ID', 'EPR_Name', 'Default_Command'])
                        
                        # Write data sorted by printer name
                        for printer in sorted(printer_totals.keys()):
                            most_recent = printer_most_recent[printer]
                            total = printer_totals[printer]
                            epr_entries = printer_epr_info.get(printer, [])
                            
                            if epr_entries:
                                # Write one row per EPR entry
                                for epr_id, epr_name, default_cmd in epr_entries:
                                    writer.writerow([printer, most_recent, total, epr_id, epr_name, default_cmd])
                            else:
                                # No EPR entries, write one row with empty EPR fields
                                writer.writerow([printer, most_recent, total, '', '', ''])
                    
                    self.logger.info(f"CSV data written to: {output_file}")
                    self.logger.info(f"Wrote {len(printer_totals)} rows (one per printer)")
                    
                except Exception as e:
                    self.logger.error(f"Error writing CSV: {e}")
                    raise
        else:
            self.logger.info(f"No print activity detected for {period_desc}")
    
    def send_email_report(self, output_file: str, recipient: str) -> bool:
        """Send email report."""
        if not recipient:
            self.logger.debug("No email recipient specified, skipping email")
            return True
        
        # Split comma-separated recipients and clean
        recipients = [r.strip() for r in recipient.split(',') if r.strip()]
        
        if not recipients:
            self.logger.debug("No valid email recipients specified, skipping email")
            return True
        
        # Validate all email addresses
        email_pattern = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
        invalid_emails = [r for r in recipients if not email_pattern.match(r)]
        
        if invalid_emails:
            self.logger.error(f"Invalid email address format: {', '.join(invalid_emails)}")
            return False
        
        self.logger.debug(f"Preparing to send email report to: {', '.join(recipients)}")
        
        # Determine period description
        if self.start_date and self.end_date:
            period_desc = f"{self.start_date.strftime('%Y-%m-%d')} to {self.end_date.strftime('%Y-%m-%d')}"
        else:
            period_desc = f"Last {self.time_period_hours} hours"
        
        if self.dry_run:
            self.logger.info(f"DRY RUN: Would send email to {', '.join(recipients)}")
            if self.attach_csv:
                self.logger.info(f"DRY RUN: Would attach file: {output_file}")
            return True
        
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = f"{SCRIPT_NAME}@{socket.gethostname()}"
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = self.email_subject
            
            
            body = f"""CUPS Print Activity Report
==========================

Host: {socket.gethostname()}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Period: {period_desc}

"""
            
            if self.include_summary and os.path.isfile(output_file):
                body += "Report Contents:\n"
                body += "-" * 40 + "\n"
                with open(output_file, 'r') as f:
                    body += f.read()
            else:
                body += "See attached CSV file for detailed report.\n"
            
            body += f"\nGenerated by: {SCRIPT_NAME} v{SCRIPT_VERSION}\n"
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Attach CSV if requested
            if self.attach_csv and os.path.isfile(output_file):
                self.logger.debug(f"Attaching CSV file: {output_file}")
                with open(output_file, 'rb') as f:
                    part = MIMEBase('text', 'csv')
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', 
                                  f'attachment; filename={Path(output_file).name}')
                    msg.attach(part)
                self.logger.debug(f"CSV file attached successfully")
            elif self.attach_csv:
                self.logger.warning(f"attach_csv is True but file does not exist: {output_file}")
            else:
                self.logger.debug(f"Skipping CSV attachment (attach_csv={self.attach_csv})")
            
            # Send email using local sendmail
            with smtplib.SMTP('localhost') as server:
                server.send_message(msg)
            
            self.logger.info(f"Email report sent to: {', '.join(recipients)}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error sending email: {e}")
            return False
    
    def run(self) -> int:
        """Main execution."""
        exit_code = 0
        
        self.logger.info(f"=== {SCRIPT_NAME} v{SCRIPT_VERSION} starting ===")
        self.logger.debug(f"Script: {__file__}")
        
        # Log the time period being used
        if self.start_date and self.end_date:
            self.logger.debug(f"Date range: {self.start_date.strftime('%Y-%m-%d')} to {self.end_date.strftime('%Y-%m-%d')}")
        else:
            self.logger.debug(f"Monitoring period: {self.time_period_hours} hours")
        
        self.logger.debug(f"Output file: {self.output_file}")
        
        # Check dependencies
        if not self.check_dependencies():
            self.logger.error("Dependency check failed")
            return 1
        
        # Detect logging method and collect data
        use_syslog = self.detect_cups_logging_method()
        
        if use_syslog:
            print_jobs = self.collect_syslog_messages()
        else:
            print_jobs = self.collect_file_logs()
        
        if not print_jobs:
            self.logger.warning("No print jobs found")
            exit_code = 2
        
        # Generate summary
        try:
            self.generate_summary(print_jobs, self.output_file)
        except Exception as e:
            self.logger.error(f"Failed to generate summary: {e}")
            return 1
        
        # Send email if configured
        if self.email_recipient:
            if not self.send_email_report(self.output_file, self.email_recipient):
                self.logger.warning("Failed to send email report")
                exit_code = 2
        
        self.logger.info(f"=== {SCRIPT_NAME} completed successfully ===")
        self.logger.info(f"Output file: {self.output_file}")
        
        return exit_code


def find_default_config() -> Optional[str]:
    """Find the first existing config file from default locations."""
    # First check current working directory for a config with the script's basename
    script_basename = Path(__file__).stem  # Gets "monitor_cups_activity" from the script name
    cwd_config = Path.cwd() / f"{script_basename}.yml"
    if cwd_config.is_file():
        return str(cwd_config)
    
    # Then check the standard locations
    for config_path in DEFAULT_CONFIG_LOCATIONS:
        if isinstance(config_path, Path):
            config_path = str(config_path)
        if os.path.isfile(config_path):
            return config_path
    
    # Fall back to script directory
    script_dir_config = str(Path(__file__).parent / "monitor_cups_activity.yml")
    return script_dir_config


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Monitor and report CUPS print activity',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  {SCRIPT_NAME}
  {SCRIPT_NAME} --hours 48 --email admin@company.com
  {SCRIPT_NAME} --debug --dry-run
  {SCRIPT_NAME} --config /etc/cups/monitor_cups_activity.yml

Exit Codes:
  0 = Success
  1 = Error
  2 = Warning

Version: {SCRIPT_VERSION}
"""
    )
    
    default_config = find_default_config()
    
    parser.add_argument('--config', type=str, default=default_config,
                       help=f'Configuration file (default: {default_config})')
    parser.add_argument('--output', type=str, default=None,
                       help=f'Output CSV file path (default: from config or {DEFAULT_OUTPUT_FILE})')
    parser.add_argument('--hours', type=int, default=None,
                       help=f'Hours back to monitor (default: from config or {DEFAULT_TIME_PERIOD})')
    parser.add_argument('--start-date', type=str, default=None,
                       help='Start date for report (YYYY-MM-DD format). Use with --end-date.')
    parser.add_argument('--end-date', type=str, default=None,
                       help='End date for report (YYYY-MM-DD format). Use with --start-date.')
    parser.add_argument('--email', type=str, default=None,
                       help=f'Email recipient for results (default: from config or {DEFAULT_EMAIL})')
    parser.add_argument('--syslog', type=str, default=None,
                       help=f'Syslog file path (default: {DEFAULT_SYSLOG_FILE})')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose output')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug output (implies verbose)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without executing')
    parser.add_argument('--stdout', action='store_true',
                       help='Print CSV output to stdout instead of file')
    
    args = parser.parse_args()
    
    # Create monitor instance
    monitor = CUPSMonitor()
    
    # Apply command line arguments
    monitor.config_file = args.config
    monitor.verbose = args.verbose
    monitor.debug = args.debug
    monitor.dry_run = args.dry_run
    monitor.stdout_mode = args.stdout
    
    if monitor.debug:
        monitor.verbose = True
    
    # Setup logging first
    monitor.setup_logging()
    
    # Validate date range arguments
    if (args.start_date and not args.end_date) or (args.end_date and not args.start_date):
        monitor.logger.error("Both --start-date and --end-date must be specified together")
        sys.exit(1)
    
    if args.start_date and args.end_date:
        try:
            monitor.start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
            monitor.end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
            # Set end_date to end of day
            monitor.end_date = monitor.end_date.replace(hour=23, minute=59, second=59)
            
            if monitor.start_date > monitor.end_date:
                monitor.logger.error("Start date must be before or equal to end date")
                sys.exit(1)
        except ValueError as e:
            monitor.logger.error(f"Invalid date format. Use YYYY-MM-DD. Error: {e}")
            sys.exit(1)
    
    # Load config file
    if monitor.config_file and os.path.isfile(monitor.config_file):
        monitor.load_yaml_config(monitor.config_file)
    
    # Override with explicitly set command-line arguments (only if not None)
    if args.output is not None:
        monitor.output_file = args.output
    if args.hours is not None:
        monitor.time_period_hours = args.hours
        # If hours is specified, clear any date range
        monitor.start_date = None
        monitor.end_date = None
    if args.email is not None:
        monitor.email_recipient = args.email
    if args.syslog is not None:
        monitor.syslog_file = args.syslog
    
    # Run
    try:
        exit_code = monitor.run()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        monitor.logger.info("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        if monitor.logger:
            monitor.logger.error(f"Unexpected error: {e}", exc_info=True)
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
