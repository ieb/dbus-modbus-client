from itertools import chain
import queue
import threading
import logging
import time
import traceback

from utils import *
import device
import devspec
import probe

log = logging.getLogger(__name__)

MODBUS_UNIT_MIN = 1
MODBUS_UNIT_MAX = 247

class ScanAborted(Exception):
    pass

class Scanner:
    """
    Scanner scan the bus finding devices.
    The scan runs in its own thread as a daemon.
    It runs once and then stops.
    It collects devices which can be retrieved later.
    """
    def __init__(self):
        self.devices = []
        self.running = None
        self.total = None
        self.done = None
        self.lock = threading.Lock()
        self.num_found = 0

    def progress(self, n, dev):
        if not self.running:
            raise ScanAborted()

        self.done += n

        if dev:
            self.num_found += 1
            with self.lock:
                self.devices.append(dev)

    def run(self):
        try:
            t0 = time.time()
            self.scan()
            t1 = time.time()
        except ScanAborted:
            pass
        except:
            log.warning('Exception during bus scan')
            traceback.print_exc()

        if self.running:
            log.info('Scan completed in %d seconds', t1 - t0)
        else:
            log.info('Scan aborted')

        self.running = False

    def start(self):
        self.done = 0
        self.running = True

        t = threading.Thread(target=self.run)
        t.daemon = True
        t.start()

        return True

    def stop(self):
        self.running = False

    def get_devices(self):
        with self.lock:
            d = self.devices
            self.devices = []
            return d


class SerialScanner(Scanner):
    def __init__(self, tty, rates, mode, timeout=0.1, full=False):
        super().__init__()
        self.tty = tty
        self.rates = rates
        self.mode = mode
        self.timeout = timeout
        self.full = full

    def progress(self, n, dev):
        super().progress(n, dev)
        if self.num_found:
            time.sleep(1)

    def scan_units(self, units, rate):
        mlist = [devspec.create(self.mode, self.tty, rate, u) for u in units]
        d = probe.probe(mlist, self.progress, 1, timeout=self.timeout)
        return d[0]

    def scan(self):
        # get all the defined units of all of the device types
        units = probe.get_units(self.mode)
        # get all the baud rates 
        rates = self.rates or probe.get_rates(self.mode)

        for r in rates:
            log.info('Scanning %s @ %d bps (quick)', self.tty, r)
            found = self.scan_units(units, r)
            if found:
                rates = [r]
                break

        if not self.full:
            return

        # if nothing found perform a full scan of all rates, this is slow.
        units = set(range(MODBUS_UNIT_MIN, MODBUS_UNIT_MAX + 1)) - \
            set(d.unit for d in found)

        for r in rates:
            log.info('Scanning %s @ %d bps (full)', self.tty, r)
            self.scan_units(units, r)

    def start(self):
        self.total = MODBUS_UNIT_MAX
        return super().start()

__all__ = ['NetScanner', 'SerialScanner']
