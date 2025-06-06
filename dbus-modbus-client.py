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

import device
import devspec
import mdns
import probe
from scan import *
from utils import *
import watchdog

# Only enable the devices known to be present
import eastron_sdm230
import growatt_pv_v120


import logging
log = logging.getLogger(__name__)

NAME = os.path.basename(__file__)
VERSION = '1.62'

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
    def __init__(self, name):
        self.name = name
        self.devices = []
        self.failed = []
        self.failed_time = 0
        self.scanner = None
        self.scan_time = time.time()
        self.auto_scan = False
        self.err_exit = False
        self.keep_failed = True
        self.remove_failed_devices = False
        self.svc = None
        self.watchdog = watchdog.Watchdog()

    def start_scan(self, full=False):
        if self.scanner:
            return

        log.info('Starting background scan')

        s = self.new_scanner(full)

        if s.start():
            self.scanner = s

    def stop_scan(self):
        if self.scanner:
            self.scanner.stop()

    def scan_update(self):
        # The scanner will or may be populating the devices it finds in the background.
        # get the list of devices
        # these are new devices that were not previously present.
        devices = self.scanner.get_devices()
        # drop devices that are already active.
        new_devices = []
        for d in devices:
            active = False
            for active_device in self.devices:
                if active_device.unit == d.unit:
                    active = True
                    log.info(f'Device found Already active {d}')
                    continue
                else:
                    log.info(f'No match {d.unit} == {active_device.unit}')
            if active:
                d.destroy()
            else:
                new_devices.append(d)

        for d in new_devices:
            # try to initialise new devices
            try:
                log.info(f'Try init on {d}')
                self.init_device(d, False)
                self.devices.append(d)
            except:
                log.info('Error initialising %s, skipping', d)
                traceback.print_exc()

        # save devices found
        self.save_devices()

    def scan_complete(self):
        self.scan_time = time.time()

        if not self.devices and self.err_exit:
            os._exit(1)

    def set_scan(self, path, val):
        if val:
            self.start_scan()
        else:
            self.stop_scan()

        return True

    def init_device(self, dev, nosave=False, enable=True):
        dev.init(self.dbusconn, enable)
        dev.last_seen = time.time()
        dev.last_warn = time.time()
        dev.nosave = nosave

    def del_device(self, dev):
        log.info(f'delete device {dev}')
        self.devices.remove(dev)
        dev.destroy()

    def dev_failed(self, dev):
        if not dev.nosave:
            self.failed.append(dev.spec)

    def update_device(self, dev):
        try:
            dev.update()
            dev.last_seen = time.time()
            dev.last_warn = time.time()
        except Exception as ex:
            if time.time() - dev.last_seen > FAIL_TIMEOUT:
                if time.time() - dev.last_warn > WARN_TIMEOUT:
                    dev.last_warn = time.time()
                    dev.log.info('Device failed: %s', ex)
                if self.remove_failed_devices:
                    if self.err_exit:
                        os._exit(1)
                    self.dev_failed(dev)
                    self.del_device(dev)

    def probe_filter(self, dev):
        return dev not in self.devices

    def probe_devices(self, devlist, nosave=False, enable=True):
        devs = set(devlist) - set(self.devices)
        devs, failed = probe.probe(devs, filt=self.probe_filter)



        for d in devs:
            try:
                log.info(f'Init {d} in probe_devices')
                self.init_device(d, nosave, enable)
                self.devices.append(d)
            except Exception as err:
                log.info(f'Init Failed {d} in probe_devices')
                log.info(f'Cause {err}')
                failed.append(d.spec)
                d.destroy()

        return failed

    def save_devices(self):
        devs = list(filter(lambda d: not d.nosave, self.devices))
        devstr = ','.join(sorted(map(str, devs + self.failed)))
        if devstr != self.settings['devices']:
            log.info(f'saving devices {devstr} ')
            self.settings['devices'] = devstr

    def update_devlist(self, old, new):
        log.info(f'Update device list old:{old} new:{new}')
        old = devspec.fromstrings(filter(None, old.split(',')))
        new = devspec.fromstrings(filter(None, new.split(',')))
        cur = set(self.devices)
        rem = old - new

        for d in rem & cur:
            dd = self.devices[self.devices.index(d)]
            self.del_device(dd)

        self.failed = self.probe_devices(new);
        self.save_devices()

    def setting_changed(self, name, old, new):
        if name == 'devices':
            self.update_devlist(old, new)
            return

    def init_settings(self):
        settings_path = '/Settings/ModbusClient/' + self.name
        SETTINGS = {
            'devices':  [settings_path + '/Devices', '', 0, 0],
            'autoscan': [settings_path + '/AutoScan', self.auto_scan, 0, 1],
        }

        self.dbusconn = private_bus()

        log.info('Waiting for localsettings')
        self.settings = SettingsDevice(self.dbusconn, SETTINGS,
                                       self.setting_changed, timeout=10)

    def init_devices(self, force_scan, force_devices=None):
        """
        If force_devices is not set then the device list which includes 
        protocol, port, and unit in comma seperated segments whill be read
        from devices. 

        If force_devices is set, it will be used.

        update dev list performs a probe, which removes devices that cant be seen, and 
        only those are scanned.

        """
        if force_devices is None:
            self.update_devlist('',self.settings['devices'])
        else:
            log.info(f'Forcing devices to {force_devices}')
            self.update_devlist(force_devices,force_devices)


        if not self.keep_failed:
            log.info(f'Not keeping failed devices {self.failed}')
            self.failed = []

        scan = force_scan

        if not self.devices or self.failed:
            if self.settings['autoscan']:
                scan = True

        if scan:
            self.start_scan(force_scan)
        else:
            log.info(f'not starting scan after init devices')

    def init(self, force_scan, force_devices=None):
        self.watchdog.start()
        self.init_settings()
        self.init_devices(force_scan, force_devices=force_devices)

    def update(self):
        if self.scanner:
            if self.svc:
                self.svc['/Scan'] = self.scanner.running
                self.svc['/ScanProgress'] = \
                    100 * self.scanner.done / self.scanner.total

            self.scan_update()

            if not self.scanner.running:
                log.info(f'Done scanning')
                self.scan_complete()
                self.scanner = None
                if self.svc:
                    self.svc['/ScanProgress'] = None

        for d in self.devices:
            self.update_device(d)

        if self.failed:
            now = time.time()

            if now - self.failed_time > FAILED_INTERVAL:
                self.failed = self.probe_devices(self.failed)
                self.failed_time = now

            if self.settings['autoscan']:
                if now - self.scan_time > SCAN_INTERVAL:
                    # rescan every 10m
                    self.start_scan()

        self.watchdog.update()

    def update_timer(self):
        try:
            self.update()
        except:
            log.error('Uncaught exception in update')
            traceback.print_exc()

        return True

class NetClient(Client):
    def __init__(self):
        super().__init__('tcp')

    def new_scanner(self, full):
        return NetScanner(MODBUS_TCP_PORT, if_blacklist)

    def init_settings(self):
        super().init_settings()

        svcname = 'com.victronenergy.modbusclient.%s' % self.name
        self.svc = VeDbusService(svcname, self.dbusconn)
        self.svc.add_path('/Scan', False, writeable=True,
                          onchangecallback=self.set_scan)
        self.svc.add_path('/ScanProgress', None, gettextcallback=percent)

    def init(self, *args):
        super().init(*args)

        self.mdns = mdns.MDNS()
        self.mdns.start()
        self.mdns_check_time = 0
        self.mdns_query_time = 0
        self.mdns_query_interval = MDNS_QUERY_INTERVAL / 10
        self.mdns_fast_query = time.time()

    def update(self):
        super().update()

        now = time.time()

        if self.mdns_fast_query is not None:
            if now - self.mdns_fast_query > MDNS_QUERY_INTERVAL:
                self.mdns_fast_query = None
                self.mdns_query_interval = MDNS_QUERY_INTERVAL

        if now - self.mdns_query_time > self.mdns_query_interval:
            self.mdns_query_time = now
            self.mdns.req()

        if now - self.mdns_check_time > MDNS_CHECK_INTERVAL:
            self.mdns_check_time = now
            maddr = self.mdns.get_devices()
            if maddr:
                self.probe_devices(maddr, nosave=True, enable=False)

    def init_device(self, dev, *args):
        super().init_device(dev, *args)

        if dev.nosave:
            dev_path = '/Devices/' + dev.get_ident()
            with self.svc as s:
                s.add_path(dev_path + '/Enabled', int(dev.enabled),
                           writeable=True,
                           onchangecallback=partial(self.enable_device, dev))
                s.add_path(dev_path + '/Serial', dev.info['/Serial'])
                name = str(dev.info.get('/CustomName', '')) or dev.productname
                s.add_path(dev_path + '/Name', name)

    def del_device(self, dev):
        with self.svc as s:
            s.del_tree('/Devices/' + dev.get_ident())
        super().del_device(dev)

    def dev_failed(self, dev):
        super().dev_failed(dev)

        if dev.nosave:
            self.mdns_fast_query = time.time()
            self.mdns_query_interval = MDNS_QUERY_INTERVAL / 10

    def enable_device(self, dev, path, val):
        dev.set_enabled(bool(val))
        return True

class SerialClient(Client):
    def __init__(self, tty, rate, mode):
        super().__init__(tty)
        self.tty = tty
        self.rate = rate
        self.mode = mode
        self.auto_scan = True
        # set to true to rescan the bus periodically so that when 
        # a device sleeps it can be reactivated when it wakes up.
        # same behavior as with the net client.
        # may need to add more overrides here.
        self.keep_failed = True 

    def new_scanner(self, full):
        return SerialScanner(self.tty, self.rate, self.mode, full=full)

def list_models():
    models = []
    for d in probe.device_types:
        models += d.get_models()

    models.sort(key=lambda x: ''.join(x).lower())
    models.insert(0, ('Manufacturer', 'Type', 'Model'))

    def maxlen(m, n):
        return max(len(x[n]) for x in m)

    w = (maxlen(models, 0), maxlen(models, 1), maxlen(models, 2))
    models.insert(1, list(map(lambda x: '-' * x, w)))

    def newval(l, m, n):
        return m[n] if m[n] != l[n] or m[0] != l[0] else ''

    last = (None, None, None)
    for m in models:
        v = list(map(partial(newval, last, m), range(3)))
        print('| %-*s | %-*s | %-*s |' % (w[0], v[0], w[1], v[1], w[2], v[2]))
        last = m

def print_info(_, d):
    if not d:
        return

    d.device_init()
    d.read_info()

    for i in sorted(d.info.items()):
        d.log.info('%-20s %s', *i)

def probe_info(devlist):
    probe.probe(map(devspec.fromstring, devlist), print_info)

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
    parser.add_argument('-r', '--rate', type=int, action='append')
    parser.add_argument('-s', '--serial')
    parser.add_argument('-x', '--exit', action='store_true',
                        help='exit on error')

    args = parser.parse_args()

    logging.basicConfig(format='%(asctime)s %(levelname)s %(name)-10s %(message)s',
                        level=(logging.DEBUG if args.debug else logging.INFO))

    logging.getLogger('pymodbus.client.sync').setLevel(logging.CRITICAL)
    logging.getLogger('pymodbus.protocol').setLevel(logging.DEBUG)



    if args.models:
        list_models()
        return

    if args.probe:
        probe_info(args.probe)
        return

    log.info('%s v%s', NAME, VERSION)

    signal.signal(signal.SIGINT, lambda s, f: os._exit(1))
    faulthandler.register(signal.SIGUSR1)
    faulthandler.enable()

    dbus.mainloop.glib.threads_init()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    mainloop = GLib.MainLoop()

    if args.serial:
        tty = os.path.basename(args.serial)
        client = SerialClient(tty, args.rate, args.mode)
    else:
        client = NetClient()

    client.err_exit = args.exit
    log.info("Force Scan is %s ", args.force_scan)
    log.info("Force Devices is %s ", args.force_devices)
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
