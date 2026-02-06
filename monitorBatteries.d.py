#!/usr/bin/env python
#
# monitorBatteries.d.py
#
# check status every x mins
# report status if % remaining has changed more than 5%
# 
# Runs as a service
#

import time
import os
import signal
from datetime import datetime
from tesla_powerwall import (
    Powerwall,
    IslandMode
)

class SignalHandler:
    shutdown_requested = False

    def __init__(self):
        signal.signal(signal.SIGINT, self.request_shutdown)
        signal.signal(signal.SIGTERM, self.request_shutdown)

    def request_shutdown(self, *args):
        logit('Request to shutdown received, stopping')
        self.shutdown_requested = True

    def can_run(self):
        return not self.shutdown_requested


signal_handler = SignalHandler()

logfolder = "/home/wwillett/logs/"
logfile = logfolder + os.path.splitext(os.path.basename(__file__))[0] + ".log"

def logit(msg) :
    with open(logfile, 'a') as f:
        f.write(str(msg))

def go_on_grid():
    power_wall.set_island_mode(IslandMode.ONGRID)
    logit("Going ongrid")
    mailit("Going Ongrid")
    time.sleep(60)

def go_off_grid():
    power_wall.set_island_mode(IslandMode.OFFGRID)
    logit("Going Offgrid")
    mailit("Going Offgrid")
    time.sleep(60)

def get_battery_percentage():
    battery = power_wall.get_batteries()
    cap0 = battery[0].capacity
    cap1 = battery[1].capacity
    rem0 = battery[0].energy_remaining
    rem1 = battery[1].energy_remaining
    return ((rem0 + rem1) / (cap0 + cap1))*100

def mailit(message):
    import smtplib
    sender = 'weston.willett@gmail.com'
    receivers = ['8456613800@vtext.com']
    s = smtplib.SMTP('smtp.gmail.com', 587)
    s.starttls()
    s.login("weston.willett@gmail.com", "pzjazgsookbslfoj")
    s.sendmail(sender, receivers, message)         
    logit("Successfully sent email")
    s.quit    

def get_stat():
    x = ""
    stat = power_wall.get_grid_status()
    if stat.CONNECTED:
        x = "Connected"
    if stat.ISLANDED:
        x = "Islanded"
    return x
    
ip = "192.168.86.163"
password = "Tim-Dead-Wrong-5!"

power_wall = Powerwall(ip)
power_wall.login(password)

last_percent_remaining = 0

# Main
while signal_handler.can_run :
    grid_status = get_stat()
    percent_remaining = get_battery_percentage()

    if percent_remaining <= 10 and grid_status == "Islanded":
        go_on_grid()

    if percent_remaining > 20 and grid_status == "Connected":
        go_off_grid()
    
    if abs(round(percent_remaining) - round(last_percent_remaining)) >= 10 :
        logit(percent_remaining)
        msg = "Subject:Powerwall Update\nTo:Wes\n\nPercent Remaining : {:.2f}".format(percent_remaining) + "\n" + grid_status
        mailit(msg)
        last_percent_remaining = percent_remaining
        dt = datetime.now()
        line = str(dt.strftime("%Y")) + str(dt.strftime("%m")) + str(dt.strftime("%d")) + " | " + str(dt.strftime("%H")) + ":" + str(dt.strftime("%M")) + ":" + str(dt.strftime("%S")) + " | " + msg + '\n'
        logit(line)

    time.sleep(1800)
    logit("Percent Remaining = " + str(percent_remaining) + " : " + str(grid_status) + "\n")

