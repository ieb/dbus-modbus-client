#! /usr/bin/python3 -u

from argparse import ArgumentParser
import dbus
import dbus.mainloop.glib
import faulthandler
from functools import partial
import os
import signal
import sys
import time
import traceback
from gi.repository import GLib

sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext', 'velib_python'))
from settingsdevice import SettingsDevice
from vedbus import VeDbusService

from utils import *
import watchdog


import client
from devspec import SerialDevSpec


# Only enable the devices known to be present
import eastron_sdm230
import growatt_pv_v120


import logging
log = logging.getLogger(__name__)

NAME = os.path.basename(__file__)
VERSION = '2.01'

__all__ = ['NAME', 'VERSION']


MODBUS_TCP_PORT = 502

FAIL_TIMEOUT = 3600
WARN_TIMEOUT = 600
FAILED_INTERVAL = 10
MDNS_CHECK_INTERVAL = 5
MDNS_QUERY_INTERVAL = 60
SCAN_INTERVAL = 60
UPDATE_INTERVAL = 100

if_blacklist = [
    'ap0',
]

def percent(path, val):
    return '%d%%' % val

class Client:
    def __init__(self, tty, rate, mode):
        self.tty = tty
        self.rate = rate
        self.mode = mode
        self.devices = []
        self.failed = []
        self.failed_time = 0
        self.scanner = None
        self.scan_time = time.time()
        self.auto_scan = False
        self.err_exit = False
        self.svc = None
        self.watchdog = watchdog.Watchdog()

 
    def init(self, force_scan, force_devices=None):
        self.watchdog.start()
        self.init_settings()
        self.init_devices()

    def init_settings(self):
        settings_path = '/Settings/Client/' + self.tty
        SETTINGS = {
            'devices':  [settings_path + '/Devices', '', 0, 0],
            'autoscan': [settings_path + '/AutoScan', 0, 0, 1],
        }

        self.dbusconn = private_bus()

        log.info('Waiting for localsettings')
        self.settings = SettingsDevice(self.dbusconn, SETTINGS,
                                       self.setting_changed, timeout=10)

    def init_devices(self):

        # hard code the devices based on the configuration.
        # which for simplicity I am simpyl going to hard code here.
        # This avoids scanning which fragments python memory

        modbus = client.make_client(self.tty, self.rate, self.mode)

        self.devices = [
            growatt_pv_v120.GrowattPVInverter(SerialDevSpec(self.mode,self.tty,self.rate,1), modbus, 'Growatt MIN 4200-TL'),
            eastron_sdm230.Eastron_SDM230v2(SerialDevSpec(self.mode,self.tty,self.rate,2), modbus, 'SDM230Modbusv2')
        ]



    def update_timer(self):
        try:
            for d in self.devices:
                self.update_device(d)

            self.watchdog.update()
        except:
            log.error('Uncaught exception in update')
            traceback.print_exc()

        return True


    def update_device(self, dev):
        try:
            if dev.init(self.dbusconn, True):
                dev.update()
                dev.last_seen = time.time()
                dev.last_warn = time.time()         
        except Exception as ex:
            if time.time() - dev.last_seen > FAIL_TIMEOUT:
                if time.time() - dev.last_warn > WARN_TIMEOUT:
                    dev.last_warn = time.time()
                    dev.log.info('Device failed: %s', ex)


    def setting_changed(self, name, old, new):
        pass







def main():
    parser = ArgumentParser(add_help=True)
    parser.add_argument('-d', '--debug', help='enable debug logging',
                        action='store_true')
    parser.add_argument('-f', '--force-scan', action='store_true')
    parser.add_argument('-F', '--force-devices')
    parser.add_argument('-m', '--mode', choices=['ascii', 'rtu'], default='rtu')
    parser.add_argument('--models', action='store_true',
                        help='List supported device models')
    parser.add_argument('--leak',
                        help='Enable memory leak detection', default=600)
    parser.add_argument('-P', '--probe', action='append')
    parser.add_argument('-r', '--rate', type=int)
    parser.add_argument('-s', '--serial')
    parser.add_argument('-x', '--exit', action='store_true',
                        help='exit on error')

    args = parser.parse_args()

    logging.basicConfig(format='%(asctime)s %(levelname)s %(name)-10s %(message)s',
                        level=(logging.DEBUG if args.debug else logging.INFO))

    logging.getLogger('pymodbus.client.sync').setLevel(logging.CRITICAL)
    logging.getLogger('pymodbus.protocol').setLevel(logging.DEBUG)



    log.info('%s v%s', NAME, VERSION)

    signal.signal(signal.SIGINT, lambda s, f: os._exit(1))
    faulthandler.register(signal.SIGUSR1)
    faulthandler.enable()

    dbus.mainloop.glib.threads_init()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    mainloop = GLib.MainLoop()

    tty = os.path.basename(args.serial)
    client = Client(tty, args.rate, args.mode)

    client.err_exit = args.exit
    client.init(args.force_scan, force_devices=args.force_devices)

    GLib.timeout_add(UPDATE_INTERVAL, client.update_timer)

    checkLeakPeriod = int(args.leak)
    if checkLeakPeriod > 0:
        log.info('Detect leaks')
        from gc_debug import LeakDetector
        leak_detector = LeakDetector()
        GLib.timeout_add_seconds(checkLeakPeriod, leak_detector.detect_leak)

    mainloop.run()

if __name__ == '__main__':
    main()
