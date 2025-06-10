import os
import struct
import threading
import time

from pymodbus.client.sync import *
from pymodbus.utilities import computeCRC
import serial
import resource

import logging
log = logging.getLogger(__name__)

class ModbusExtras:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.refcount = 1
        self.in_transaction = False

    def get(self):
        self.refcount += 1
        return self

    def put(self):
        if self.refcount > 0:
            self.refcount -= 1
        if self.refcount == 0:
            self.close()

    def close(self):
        if self.refcount == 0 or self.in_transaction:
            super().close()

    def execute(self, *args):
        try:
            self.in_transaction = True
            return super().execute(*args)
        finally:
            self.in_transaction = False

    def read_registers(self, address, count, access, **kwargs):
        if access == 'holding':
            return self.read_holding_registers(address, count, **kwargs)

        if access == 'input':
            return self.read_input_registers(address, count, **kwargs)

        raise Exception('Invalid register access type: %s' % access)

class TcpClient(ModbusExtras, ModbusTcpClient):
    method = 'tcp'

class UdpClient(ModbusExtras, ModbusUdpClient):
    method = 'udp'

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, t):
        self._timeout = t
        if self.socket:
            self.socket.settimeout(t)

class SerialClient(ModbusExtras, ModbusSerialClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock = threading.RLock()


    def connect(self):
        """ Connect to the modbus serial server

        :returns: True if connection succeeded, False otherwise
        """
        if self.socket:
            return True
        try:
            #self.socket = BusyPollSerial(port=self.port,
            #                            timeout=self.timeout,
            #                            bytesize=self.bytesize,
            #                            stopbits=self.stopbits,
            #                            baudrate=self.baudrate,
            #                            parity=self.parity)
            self.socket = serial.Serial(port=self.port,
                                        timeout=self.timeout,
                                        bytesize=self.bytesize,
                                        stopbits=self.stopbits,
                                        baudrate=self.baudrate,
                                        parity=self.parity)
            if self.method == "rtu":
                if self._strict:
                    self.socket.interCharTimeout = self.inter_char_timeout
                self.last_frame_end = None
        except serial.SerialException as msg:
            _logger.error(msg)
            self.close()
        return self.socket is not None

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, t):
        self._timeout = t
        if self.socket:
            self.socket.timeout = t

    def put(self):
        super().put()
        if self.refcount == 0:
            del serial_ports[os.path.basename(self.port)]

    def execute(self, request=None):
        with self.lock:
            #if request.unit_id == 5:
            #    self.breakout = True
            #    self.socket.breakout = True
            #else:
            #    self.breakout = False
            #    self.socket.breakout = False
            #self.socket.unit_id = request.unit_id
            return super().execute(request)

    def __enter__(self):
        print(f'>>>')
        self.lock.acquire()
        return super().__enter__()

    def __exit__(self, *args):
        super().__exit__(*args)
        self.lock.release()
        print(f'<<<')


class BusyPollSerial(serial.Serial):
    """\
    Poll based read implementation. Not all systems support poll properly.
    However this one has better handling of errors, such as a device
    disconnecting while it's in use (e.g. USB-serial unplugged).
    """


    def read(self, size=1):
        """\
        Read size bytes from the serial port. If a timeout is set it may
        return less characters as requested. With no timeout it will block
        until the requested number of bytes is read.

        Reading is done using repated read since select with a timeout causes 
        a memory leak.
        """
        if not self.is_open:
            raise serial.PortNotOpenError()
        read = bytearray()
        start_read = time.time()
        interbyteTimeout = 0
        readTimeout = 0
        nreads = 0
        if size > 0:
            while len(read) < size:
                if self.breakout and False:
                    break
                else:
                    nreads = nreads + 1
                    buf = os.read(self.fd, size - len(read))
                    end_read = time.time()
                    # test for timeouts.
                    #if self._inter_byte_timeout is not None:
                    #    if end_read - start_this_read > self._inter_byte_timeout*5.0:
                    #        interbyteTimeout = end_read - start_this_read
                    #        break # timeout
                    if self._timeout is not None:
                        if end_read - start_read > self._timeout:
                            readTimeout = end_read - start_read
                            break # timeout
                    if len(buf) == 0:
                        time.sleep(0.1)
                    else:
                        read.extend(buf)
        if len(read) < size:
            if not self.breakout:
                print(f'not enough bytes unit:{self.unit_id} interbyte:{interbyteTimeout} readTimeout::{readTimeout} {len(read)} {size} ')
        return bytes(read)





serial_ports = {}



def make_client(tty, rate, method):

    if tty in serial_ports:
        client = serial_ports[tty]
        if client.baudrate != rate:
            raise Exception('rate mismatch on %s' % tty)
        return client.get()

    dev = '/dev/%s' % tty
    log.info(f'Creating serial client on {dev} rate {rate}')
    client = SerialClient(method, port=dev, baudrate=rate)
    if not client.connect():
        client.put()
        return None

    serial_ports[tty] = client

    # send some harmless messages to the broadcast address to
    # let rate detection in devices adapt
    packet = bytes([0x00, 0x08, 0x00, 0x00, 0x55, 0x55])
    packet += struct.pack('>H', computeCRC(packet))

    for i in range(12):
        client.socket.write(packet)
        time.sleep(0.1)

    return client
