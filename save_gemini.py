import os
import subprocess
from datetime import datetime
import re
import time

# Configuration
VAULT_PATH = os.path.expanduser("~/knowledgebase/tobofiled")
LOG_FILE = os.path.expanduser("~/logs/save_gemini.log")

def log_message(message):
    """Log a message to the log file."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a') as f:
        f.write(f"{datetime.now().isoformat()} - {message}\n")

def log_execution():
    """Log when the program was run."""
    log_message("Program executed")

def get_clipboard():
    """Get the current clipboard content using wl-paste (Wayland) or xclip (X11)."""
    # Try wl-paste first (for Wayland)
    try:
        result = subprocess.run(['wl-paste'], capture_output=True, text=True)
        log_message(f"wl-paste returncode: {result.returncode}, stderr: '{result.stderr.strip()}', stdout length: {len(result.stdout)}")
        if result.returncode == 0 and result.stdout.strip():
            log_message("Got content from wl-paste (Wayland)")
            return result.stdout
    except FileNotFoundError:
        log_message("wl-paste not found (not on Wayland)")
    except Exception as e:
        log_message(f"wl-paste exception: {e}")
    
    # Ensure DISPLAY is set for X11 clipboard access
    env = os.environ.copy()
    if 'DISPLAY' not in env:
        env['DISPLAY'] = ':0'  # Default X display
        log_message(f"DISPLAY not set, using :0")
    else:
        log_message(f"Using DISPLAY: {env['DISPLAY']}")
    
    # Try xclip clipboard selection (Ctrl+C on X11)
    try:
        result = subprocess.run(['xclip', '-selection', 'clipboard', '-o'], 
                               capture_output=True, text=True, env=env)
        log_message(f"xclip CLIPBOARD returncode: {result.returncode}, stderr: '{result.stderr.strip()}', stdout length: {len(result.stdout)}")
        if result.returncode == 0 and result.stdout.strip():
            log_message("Got content from xclip CLIPBOARD selection")
            return result.stdout
    except Exception as e:
        log_message(f"xclip CLIPBOARD exception: {e}")
    
    # Try xclip primary selection as fallback (highlight + middle-click)
    try:
        result = subprocess.run(['xclip', '-selection', 'primary', '-o'], 
                               capture_output=True, text=True, env=env)
        log_message(f"xclip PRIMARY returncode: {result.returncode}, stderr: '{result.stderr.strip()}', stdout length: {len(result.stdout)}")
        if result.returncode == 0 and result.stdout.strip():
            log_message("Got content from xclip PRIMARY selection")
            return result.stdout
    except Exception as e:
        log_message(f"xclip PRIMARY exception: {e}")
    
    log_message("No content found in any clipboard selection")
    return ""

def slugify(text):
    # Standardizes the first line to create a safe filename
    text = text.split('\n')[0][:50]
    return re.sub(r'[^\w\s-]', '', text).strip().replace(' ', '_')

def main():
    log_execution()
    
    # Small delay to let clipboard operations complete
    time.sleep(0.1)
    
    if not os.path.exists(VAULT_PATH):
        os.makedirs(VAULT_PATH)

    try:
        content = get_clipboard()
        if not content.strip():
            log_message("Clipboard is empty")
            return

        # Find the next available file number
        existing_files = [f for f in os.listdir(VAULT_PATH) if f.startswith('file') and f.endswith('.md')]
        numbers = []
        for f in existing_files:
            match = re.match(r'file(\d+)\.md', f)
            if match:
                numbers.append(int(match.group(1)))
        
        next_number = max(numbers) + 1 if numbers else 1
        filename = f"file{next_number}.md"
        
        full_path = os.path.join(VAULT_PATH, filename)

        with open(full_path, 'w') as f:
            f.write(content)
        
        log_message(f"Successfully created file: {filename}")
            
        # Optional: Send a desktop notification so you know it worked
        subprocess.run(['notify-send', 'Obsidian', f'Saved to {filename}'])
        
    except Exception as e:
        log_message(f"Error: {str(e)}")
        subprocess.run(['notify-send', 'Error', str(e)])

if __name__ == "__main__":
    main()