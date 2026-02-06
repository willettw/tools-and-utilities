# Monitor CUPS Activity - Installation Guide

## Standard Linux Installation Locations

### ✅ **Executable Location**
```bash
# Install script to standard location for custom utilities
sudo cp monitor_cups_activity /usr/local/bin/
sudo chmod +x /usr/local/bin/monitor_cups_activity
```

### ✅ **Configuration File Locations (in order of preference)**

The script automatically searches these locations:

1. **System-wide (Recommended)**:
   ```bash
   sudo cp monitor_cups_activity.yml /etc/monitor_cups_activity.yml
   sudo chown root:root /etc/monitor_cups_activity.yml
   sudo chmod 644 /etc/monitor_cups_activity.yml
   ```

2. **CUPS-specific directory**:
   ```bash
   sudo cp monitor_cups_activity.yml /etc/cups/monitor_cups_activity.yml
   sudo chown root:lp /etc/cups/monitor_cups_activity.yml
   sudo chmod 644 /etc/cups/monitor_cups_activity.yml
   ```

3. **User-specific** (for non-root users):
   ```bash
   mkdir -p ~/.config/monitor_cups_activity/
   cp monitor_cups_activity.yml ~/.config/monitor_cups_activity/config.yml
   ```

## 📋 **Complete Installation Commands**

### **Method 1: System-wide Installation (Recommended)**
```bash
# Copy files to standard locations
sudo cp monitor_cups_activity /usr/local/bin/
sudo cp monitor_cups_activity.yml /etc/
sudo chmod +x /usr/local/bin/monitor_cups_activity
sudo chmod 644 /etc/monitor_cups_activity.yml

# Test the installation
monitor_cups_activity --help
monitor_cups_activity --debug --dry-run
```

### **Method 2: CUPS-integrated Installation**
```bash
# Install in CUPS directory structure
sudo cp monitor_cups_activity /usr/local/bin/
sudo cp monitor_cups_activity.yml /etc/cups/
sudo chmod +x /usr/local/bin/monitor_cups_activity
sudo chmod 644 /etc/cups/monitor_cups_activity.yml
sudo chown root:lp /etc/cups/monitor_cups_activity.yml
```

## 🔄 **Automated Scheduling**

### **Add to Crontab for Regular Monitoring**
```bash
# Edit root crontab for system-wide monitoring
sudo crontab -e

# Add line for hourly monitoring:
0 * * * * /usr/local/bin/monitor_cups_activity

# Or for daily monitoring at 6 AM:
0 6 * * * /usr/local/bin/monitor_cups_activity --hours 24

# Or for weekly Monday morning reports:
0 6 * * 1 /usr/local/bin/monitor_cups_activity --hours 168 --email admin@company.com
```

## 📁 **Standard File Locations After Installation**

```
/usr/local/bin/monitor_cups_activity           # Executable script
/etc/monitor_cups_activity.yml                 # System configuration
/var/log/print_activity.csv                    # Output data (appended)
/var/log/monitor_cups_activity.log             # Script log file
```

## ✅ **Verification Commands**

```bash
# Check installation
which monitor_cups_activity
monitor_cups_activity --help

# Test configuration detection
monitor_cups_activity --debug --dry-run

# Verify permissions
ls -la /usr/local/bin/monitor_cups_activity
ls -la /etc/monitor_cups_activity.yml
```

## 🎯 **Why These Locations?**

- **`/usr/local/bin/`**: Standard for locally-installed custom utilities
- **`/etc/`**: Standard for system-wide configuration files  
- **`/etc/cups/`**: Keeps CUPS-related configs together
- **`/var/log/`**: Standard for system log files
- **`~/.config/`**: User-specific configurations (XDG Base Directory spec)

## 📧 **Email Configuration**

The script will automatically email results to `wwillett@institute.org` as configured. Make sure your system has `mail` or `sendmail` configured for outbound email.

This follows all Linux Filesystem Hierarchy Standard (FHS) conventions!