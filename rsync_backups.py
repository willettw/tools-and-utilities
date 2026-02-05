#!/usr/bin/env python3
"""
rsync_backups.py - Execute rsync backup jobs from YAML configuration

PURPOSE:
    Unified rsync backup script that replaces multiple individual bash scripts.
    Reads backup job definitions from a YAML configuration file and executes
    rsync commands with proper logging and error handling.

USAGE:
    python rsync_backups.py [OPTIONS]

EXAMPLES:
    # Run all enabled backup jobs
    python rsync_backups.py

    # Run specific job(s)
    python rsync_backups.py --job desktop --job documents

    # Run with custom config file
    python rsync_backups.py --config /path/to/config.yml

    # Dry run (show what would be done)
    python rsync_backups.py --dry-run

    # Enable deletion with backup protection
    python rsync_backups.py --delete

    # Generate disk usage report
    python rsync_backups.py --report

    # Verbose output
    python rsync_backups.py --verbose

EXIT CODES:
    0 = Success (all jobs completed successfully)
    1 = Configuration error
    2 = One or more jobs failed

REQUIREMENTS:
    - PyYAML

VERSION: 1.0.0
REVISION HISTORY:
    1.0.0 - Initial implementation (2026-02-02)
"""

import argparse
import subprocess
import sys
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import yaml


def logit(message: str, logfile: Optional[str] = None, verbose: bool = False) -> None:
    """
    Log a message to file and optionally to stdout.
    
    Args:
        message: Message to log
        logfile: Path to log file
        verbose: If True, also print to stdout
    """
    if logfile:
        try:
            with open(logfile, 'a') as f:
                f.write(f"{message}\n")
        except Exception as e:
            print(f"ERROR: Failed to write to log file {logfile}: {e}", file=sys.stderr)
    
    if verbose:
        print(message)


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load configuration from YAML file.
    
    Args:
        config_path: Path to YAML configuration file
        
    Returns:
        Configuration dictionary
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If config file is invalid
    """
    config_file = Path(config_path)
    
    # Try current directory first, then /usr/local/etc/
    if not config_file.exists():
        alt_path = Path("/usr/local/etc") / config_path
        if alt_path.exists():
            config_file = alt_path
        else:
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    return config


def validate_config(config: Dict[str, Any]) -> bool:
    """
    Validate configuration structure.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        True if valid, False otherwise
    """
    if 'settings' not in config:
        print("ERROR: Missing 'settings' section in configuration", file=sys.stderr)
        return False
    
    if 'jobs' not in config:
        print("ERROR: Missing 'jobs' section in configuration", file=sys.stderr)
        return False
    
    if not isinstance(config['jobs'], list):
        print("ERROR: 'jobs' must be a list", file=sys.stderr)
        return False
    
    # Validate each job
    for idx, job in enumerate(config['jobs']):
        if 'name' not in job:
            print(f"ERROR: Job at index {idx} missing 'name'", file=sys.stderr)
            return False
        if 'source' not in job:
            print(f"ERROR: Job '{job['name']}' missing 'source'", file=sys.stderr)
            return False
        if 'destination' not in job:
            print(f"ERROR: Job '{job['name']}' missing 'destination'", file=sys.stderr)
            return False
    
    return True


def format_size(bytes_size: int) -> str:
    """
    Format bytes to human-readable size.
    
    Args:
        bytes_size: Size in bytes
        
    Returns:
        Human-readable size string
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"


def get_path_info(path: str) -> Tuple[Optional[int], Optional[int], Optional[int], str]:
    """
    Get disk usage information for a path.
    
    Args:
        path: Path to check
        
    Returns:
        Tuple of (used_bytes, free_bytes, total_bytes, status)
        status: 'OK', 'NOT_FOUND', or 'ERROR'
    """
    path_obj = Path(path).expanduser()
    
    # Check if path exists
    if not path_obj.exists():
        return None, None, None, 'NOT_FOUND'
    
    try:
        # Get filesystem stats
        stat = shutil.disk_usage(str(path_obj))
        
        # Get directory size if it's a directory
        if path_obj.is_dir():
            # Use du command for more accurate size
            try:
                result = subprocess.run(
                    ['du', '-sb', str(path_obj)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    timeout=30
                )
                if result.returncode == 0:
                    used_bytes = int(result.stdout.split()[0])
                else:
                    used_bytes = None
            except:
                used_bytes = None
        else:
            used_bytes = path_obj.stat().st_size
        
        return used_bytes, stat.free, stat.total, 'OK'
        
    except Exception as e:
        return None, None, None, f'ERROR: {e}'


def generate_report(config: Dict[str, Any]) -> None:
    """
    Generate a disk usage report for all backup jobs.
    
    Args:
        config: Configuration dictionary
    """
    print("\n" + "="*100)
    print("RSYNC BACKUP JOBS - DISK USAGE REPORT")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*100)
    
    # Header
    print(f"\n{'Job':<15} {'Location':<10} {'Path':<35} {'Used':<12} {'Free':<12} {'Total':<12} {'Status':<15}")
    print("-"*100)
    
    for job in config['jobs']:
        job_name = job['name']
        enabled_str = "✓" if job.get('enabled', True) else "✗"
        
        # Check source
        source = job['source']
        src_used, src_free, src_total, src_status = get_path_info(source)
        
        if src_status == 'OK':
            used_str = format_size(src_used) if src_used else 'N/A'
            free_str = format_size(src_free) if src_free else 'N/A'
            total_str = format_size(src_total) if src_total else 'N/A'
            status_str = f"{enabled_str} OK"
        else:
            used_str = 'N/A'
            free_str = 'N/A'
            total_str = 'N/A'
            status_str = f"{enabled_str} {src_status}"
        
        # Truncate path if too long
        display_source = source if len(source) <= 35 else '...' + source[-32:]
        
        print(f"{job_name:<15} {'Source':<10} {display_source:<35} {used_str:<12} {free_str:<12} {total_str:<12} {status_str:<15}")
        
        # Check destination
        destination = job['destination']
        dst_used, dst_free, dst_total, dst_status = get_path_info(destination)
        
        if dst_status == 'OK':
            used_str = format_size(dst_used) if dst_used else 'N/A'
            free_str = format_size(dst_free) if dst_free else 'N/A'
            total_str = format_size(dst_total) if dst_total else 'N/A'
            status_str = f"{enabled_str} OK"
        else:
            used_str = 'N/A'
            free_str = 'N/A'
            total_str = 'N/A'
            status_str = f"{enabled_str} {dst_status}"
        
        # Truncate path if too long
        display_dest = destination if len(destination) <= 35 else '...' + destination[-32:]
        
        print(f"{'':<15} {'Dest':<10} {display_dest:<35} {used_str:<12} {free_str:<12} {total_str:<12} {status_str:<15}")
        print("-"*100)
    
    print("\nLegend: ✓ = Enabled, ✗ = Disabled")
    print("Note: 'Used' for source shows directory size, for destination shows disk usage at that path")
    print("="*100 + "\n")


def build_rsync_command(job: Dict[str, Any], config: Dict[str, Any], 
                        enable_delete: bool = False) -> List[str]:
    """
    Build rsync command from job configuration.
    
    Args:
        job: Job configuration dictionary
        config: Global configuration dictionary
        enable_delete: Whether to enable --delete and backup options
        
    Returns:
        List of command components
    """
    from datetime import datetime
    cmd = ['rsync']
    
    # Add rsync options (job-specific overrides global)
    if 'rsync_options' in job:
        options = job['rsync_options']
    elif 'rsync_options' in config['settings']:
        options = config['settings']['rsync_options'].copy()
    else:
        options = []
    
    # Add delete options if requested
    if enable_delete:
        backup_deleted_dir = config['settings'].get('backup_deleted_dir', '/mnt/data2/backups/deleted')
        date_str = datetime.now().strftime(config['settings'].get('log_date_format', '%Y%m%d'))
        job_name = job['name']
        
        delete_options = [
            '--delete',
            '--backup',
            f'--backup-dir={backup_deleted_dir}/{date_str}/{job_name}'
        ]
        options = delete_options + options
    
    # Process options and replace templates
    processed_options = []
    for opt in options:
        # Replace template variables
        if '{backup_deleted_dir}' in opt:
            backup_dir = config['settings'].get('backup_deleted_dir', '/mnt/data2/backups/deleted')
            opt = opt.replace('{backup_deleted_dir}', backup_dir)
        if '{date}' in opt:
            date_str = datetime.now().strftime(config['settings'].get('log_date_format', '%Y%m%d'))
            opt = opt.replace('{date}', date_str)
        if '{job_name}' in opt:
            opt = opt.replace('{job_name}', job['name'])
        processed_options.append(opt)
    
    cmd.extend(processed_options)
    
    # Add global exclude patterns (unless disabled for this job)
    if job.get('use_global_excludes', True) and 'exclude_patterns' in config['settings']:
        for pattern in config['settings']['exclude_patterns']:
            cmd.extend(['--exclude', pattern])
    
    # Add job-specific exclude patterns
    if 'exclude_patterns' in job:
        for pattern in job['exclude_patterns']:
            cmd.extend(['--exclude', pattern])
    
    # Add exclude-from if specified
    if 'exclude_from' in job:
        cmd.extend(['--exclude-from', job['exclude_from']])
    
    # Add source and destination
    cmd.append(job['source'])
    cmd.append(job['destination'])
    
    return cmd


def run_rsync_job(job: Dict[str, Any], config: Dict[str, Any], 
                  args: argparse.Namespace) -> bool:
    """
    Execute a single rsync backup job.
    
    Args:
        job: Job configuration
        config: Global configuration
        args: Command-line arguments
        
    Returns:
        True if successful, False otherwise
    """
    job_name = job['name']
    
    # Check if job is enabled
    if not job.get('enabled', True):
        logit(f"Skipping disabled job: {job_name}", args.logfile, args.verbose)
        return True
    
    # Setup logging
    log_dir = Path(config['settings']['log_directory']).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    
    date_format = config['settings'].get('log_date_format', '%Y%m%d')
    date_str = datetime.now().strftime(date_format)
    job_logfile = log_dir / f"rsync_{job_name}.out.{date_str}"
    
    # Log job start
    start_time = datetime.now()
    start_msg = f"{start_time}"
    logit(start_msg, str(job_logfile), False)
    
    if args.verbose:
        description = job.get('description', job_name)
        print(f"\n{'='*60}")
        print(f"Job: {description}")
        print(f"Source: {job['source']}")
        print(f"Destination: {job['destination']}")
        print(f"Log: {job_logfile}")
        print(f"{'='*60}")
    
    # Build rsync command
    cmd = build_rsync_command(job, config, args.delete)
    
    if args.verbose or args.dry_run:
        print(f"Command: {' '.join(cmd)}")
        if args.delete:
            backup_dir = config['settings'].get('backup_deleted_dir', '/mnt/data2/backups/deleted')
            print(f"  (Delete mode enabled - deleted files backed up to {backup_dir}/)")
    
    if args.dry_run:
        print("(Dry run - not executing)")
        return True
    
    # Execute rsync
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=config['settings'].get('timeout', 3600)
        )
        
        # Log output
        logit(result.stdout, str(job_logfile), False)
        
        # Log end time
        end_time = datetime.now()
        end_msg = f"{end_time}"
        logit(end_msg, str(job_logfile), False)
        logit("", str(job_logfile), False)  # Blank line
        
        if result.returncode == 0:
            success_msg = f"Job '{job_name}' completed successfully"
            logit(success_msg, args.logfile, args.verbose)
            return True
        else:
            error_msg = f"Job '{job_name}' failed with exit code {result.returncode}"
            logit(error_msg, args.logfile, True)
            if args.verbose:
                print(result.stdout)
            return False
            
    except subprocess.TimeoutExpired:
        timeout = config['settings'].get('timeout', 3600)
        error_msg = f"Job '{job_name}' timed out after {timeout} seconds"
        logit(error_msg, args.logfile, True)
        logit(error_msg, str(job_logfile), False)
        return False
    except Exception as e:
        error_msg = f"Job '{job_name}' failed with error: {e}"
        logit(error_msg, args.logfile, True)
        logit(error_msg, str(job_logfile), False)
        return False


def main() -> int:
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Execute rsync backup jobs from YAML configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--config', '-c',
        type=str,
        default='rsync_backups.yml',
        help='Configuration file path (default: rsync_backups.yml)'
    )
    parser.add_argument(
        '--job', '-j',
        type=str,
        action='append',
        dest='jobs',
        help='Run specific job(s) by name (can be specified multiple times)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output'
    )
    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Show what would be done without executing'
    )
    parser.add_argument(
        '--delete',
        action='store_true',
        help='Enable deletion of files at destination that were removed from source (with backup)'
    )
    parser.add_argument(
        '--report',
        action='store_true',
        help='Generate disk usage report for all backup jobs (does not run backups)'
    )
    parser.add_argument(
        '--logfile',
        type=str,
        help='Main log file path (default: /home/wwillett/logs/rsync_backups.log)'
    )
    
    args = parser.parse_args()
    
    # Setup main logging
    if args.logfile:
        args.logfile = str(Path(args.logfile).expanduser())
    else:
        args.logfile = "/home/wwillett/logs/rsync_backups.log"
    
    # Ensure log directory exists
    log_dir = Path(args.logfile).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Start logging
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logit("="*80, args.logfile, args.verbose)
    logit("RSYNC BACKUPS - STARTING", args.logfile, args.verbose)
    logit(f"Time: {timestamp}", args.logfile, args.verbose)
    if args.dry_run:
        logit("Mode: DRY RUN", args.logfile, args.verbose)
    if args.delete:
        logit("Delete mode: ENABLED (deleted files will be backed up)", args.logfile, args.verbose)
    logit("="*80, args.logfile, args.verbose)
    
    try:
        # Load and validate configuration
        logit("Loading configuration...", args.logfile, args.verbose)
        config = load_config(args.config)
        
        if not validate_config(config):
            logit("Configuration validation failed", args.logfile, True)
            return 1
        
        # Handle report mode
        if args.report:
            generate_report(config)
            return 0
        
        # Filter jobs if specific jobs requested
        jobs_to_run = config['jobs']
        if args.jobs:
            jobs_to_run = [j for j in config['jobs'] if j['name'] in args.jobs]
            if not jobs_to_run:
                logit(f"ERROR: No matching jobs found for: {', '.join(args.jobs)}", 
                      args.logfile, True)
                return 1
            logit(f"Running {len(jobs_to_run)} selected job(s): {', '.join(args.jobs)}", 
                  args.logfile, args.verbose)
        else:
            enabled_count = sum(1 for j in jobs_to_run if j.get('enabled', True))
            logit(f"Running {enabled_count} enabled job(s) from configuration", 
                  args.logfile, args.verbose)
        
        # Execute jobs
        results = {}
        for job in jobs_to_run:
            success = run_rsync_job(job, config, args)
            results[job['name']] = success
        
        # Summary
        logit("="*80, args.logfile, args.verbose)
        logit("BACKUP SUMMARY", args.logfile, args.verbose)
        logit("="*80, args.logfile, args.verbose)
        
        total = len(results)
        successful = sum(1 for s in results.values() if s)
        failed = total - successful
        
        for job_name, success in results.items():
            status = "SUCCESS" if success else "FAILED"
            logit(f"  {job_name}: {status}", args.logfile, args.verbose)
        
        logit("-"*80, args.logfile, args.verbose)
        logit(f"Total jobs: {total}", args.logfile, args.verbose)
        logit(f"Successful: {successful}", args.logfile, args.verbose)
        logit(f"Failed: {failed}", args.logfile, args.verbose)
        
        end_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logit("="*80, args.logfile, args.verbose)
        logit(f"RSYNC BACKUPS - COMPLETED at {end_timestamp}", args.logfile, args.verbose)
        logit("="*80, args.logfile, args.verbose)
        
        return 0 if failed == 0 else 2
        
    except FileNotFoundError as e:
        logit(f"ERROR: {e}", args.logfile, True)
        return 1
    except yaml.YAMLError as e:
        logit(f"ERROR: Invalid YAML configuration: {e}", args.logfile, True)
        return 1
    except Exception as e:
        logit(f"ERROR: Unexpected error: {e}", args.logfile, True)
        import traceback
        logit(traceback.format_exc(), args.logfile, args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
