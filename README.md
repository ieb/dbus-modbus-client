# dbus-modbus-client

Reads data from Modbus devices and publishes on D-Bus.  Service names and
paths are per the [Victron D-Bus specification](https://github.com/victronenergy/venus/wiki/dbus).

Modbus devices using the RTU, TCP, and UDP transports are supported.

# Developing and installation

In case you have not yet found it, read this, it will save you a lot of time.

https://github.com/victronenergy/venus/wiki/howto-add-a-driver-to-Venus

Important parts are if you are installing for a RTU device first stop the serial starter

    /opt/victronenergy/serial-starter/stop-tty.sh ttyUSB0

Then you can run on the command line locally.

To install properly follow the instructions in the wiki document.

Installed as a seperate service in /data not using serial-starter, since in general I want more control over when and how it starts.

# Setup

On the GX device

    mkdir /data/dbus-mymodbus-client

Here check that the service/run file has the right command line, currently It will scan ttyUSB0 at 9600 for units 1 and 2

    exec /data/dbus-mymodbus-client/dbus-modbus-client.py -x -s /dev/ttyUSB0 -F rtu:ttyUSB0:9600:1,rtu:ttyUSB0:9600:2

Then copy everything here into that location

    scp -r . root@192.168.1.104:/data/dbus-mymodbus-client

Run the install script

    ./install.sh

This should setup permissions and install /data/rc.local to disable scanning of usb serial ports. Other methods proved not to work

    #!/bin/bash
    
    ln -s /data/dbus-mymodbus-client/service /service/dbus-mymodbus-client
    ls -l /service/
    
    /opt/victronenergy/serial-starter/stop-tty.sh ttyUSB0
    /opt/victronenergy/serial-starter/stop-tty.sh ttyUSB1
    /opt/victronenergy/serial-starter/stop-tty.sh ttyUSB2
    echo "Disabled serial starter on ttyUSB0,1,2"


Start the service

    svc -u /service/dbus-mymodbus-client

## debugging

Stop the service

    svc -d /service/dbus-mymodbus-client

Run on the command line

    /data/dbus-mymodbus-client/dbus-modbus-client.py -x -s /dev/ttyUSB0 -F rtu:ttyUSB0:9600:1,rtu:ttyUSB0:9600:2

When done, start the service

    svc -u /service/dbus-mymodbus-client

# How does the driver work ?

Quick notes....

The driver is the Victron dbus-modbus-client driver with modification. It took me a while to work 
out how it worked as the code has minimal documentation other than the code, fair enough, but
harder to grasp without intent. The process starts as either a serial or network connected 
process. It will only connect to a single serial port at a time. It looks like the code is now 
favors TCP connections over serial, but serial does work. They behave differently. By default 
the serial code probes modbus on serial with the units as configured in each driver and the baud 
rate configured. As it detects modbus servers, it adds the device to a list of active devices. It 
also adds the failed devices to a list of failed devices. Once that is done it starts all the 
active devices and throws away the failed one, recording the state in dbus settings. The server 
then runs with each device monitoring its target server updating the dbus as per the api.  If a 
device should fail, it will be added to a list of failed devices and re-probing is attempted 
every 10m for the failed devices. This works provided all the devices are present when the GX 
starts, otherwise the device will never be added. This code base is modified not to throw away 
failed devices on the intial startup, and only those devices that are known to be on the bus are 
imported into the client. Hopefully, this will mean when the sun goes down, the inverters show as 
zero energy but are still marked as present. More fixes needed probably.

The devices themselves create a list of info registers that are queried on startup, and a list of 
data registers. The data registers are packed to minimize rtu traffic and then called on each 
update loop from the update call in the main driver. Not all register sets are queried every loop.

# Dynamic Generation limit setup

The aim when active is to not export or import energy using both the battery and the inverter.
It should be possible to use a CT clamp on the pvinvereter and tell it not to export, however
they stop working over 20m of wire resulting in a CT Open warnng message. It is also possible 
to use a SDM230 on the pvinvertre, but not if its being used already. I could create a fake SDM230
inside the MultiPlus, but that would require another serial device. The solution I have settled on
is to directly control the output of the pvinveter based on the grid meter, pvpower and battery power, setting the maximum output to the sum. However its not quite so simple as the battery wont charge unless there is spare power. So if the battery charge is < 90%, the pvinvreter is allowed to output full power. If > 90%, then the batterpower is added when charging and added when discharging at over 100W. This allows the MultiPlus to take control over the grid no export for the last 100W.

Using this approach the pvinverter tracks demand with about a 1s latency, provided there is sun. Demands over the pvoutput get served by the battery which typically starts to charge from the pvinverter when the demand goes.

Paths

pvinverter:/dynamicGenerationStatus text status
pvinverter:/dynamicGenerationPower calculated instantaneous power demand
pvinverter:/dynamicGenerationPowerMax pvinveerter max power setting (holding register 3)
/Settings/DynamicGeneration/energyDifference minimum allowable difference between import and export, below this active tracking is activated, in kwh see the grid meter /Ac/Energy/Consumption value for the current value.
/Settings/DynamicGeneration/derateGeneraton 1=enable, 0=disable


# Discoveries

There is an assumption by Victron that a PV String charges a battery, which is wrong where the 
pv inverter is grid tied. Hence a multi doesnt work to represent a Growatt, but the standard model
has no fields for PV strings.  Will try to convert the Growatt pv model into a pv inverter model,
with PV strings added as custom fields.

Converting from multi to pvinverter works, but the PV string information is lost. This is currently being added under an /internal path so that its not picked up by the gui. As far as I can tell this is not sent to the VRM and is only visible on the detail of the dbus under debug in teh gui.

The modbus client driver was written with the assumption that all devices on a single RTU serial port would be responding. On startup it scans the last known configured set of units, only activates those found and saves them. By default the RTU client does not run a re-scan on failed devices, fixed by setting rescan to true on the SerialClient. This seems to cause the update loop in the service to restart the scanner every 600s. Also failed devices must be kept for this to happen.

    @@ -345,7 +377,11 @@ class SerialClient(Client):
             self.rate = rate
             self.mode = mode
             self.auto_scan = True
    -        self.keep_failed = False
    +        # set to true to rescan the bus periodically so that when 
    +        # a device sleeps it can be reactivated when it wakes up.
    +        # same behavior as with the net client.
    +        # may need to add more overrides here.
    +        self.keep_failed = True 

Some files from the GX device had to be added to make the code work when relocated. settingsdevice.py, vedbus.py, and ve_utils.py. Hopefully thats ok. 


# Importing or watching other devices

First thing to remember is that dbus is a rpc and event system. Reading a property is an rpc call which may block unless done async. Best to watch for updates. The updates only appear to fire on '/' and will only fire for a property when it changes on dbus. It was easiest to use patterns in the official python dbus support libs as they are less complicated to understand than Vebus wrappers https://gitlab.freedesktop.org/dbus/dbus-python/-/blob/master/examples/example-async-client.py

VeDbusImport didnt work well. It blocked waiting for a event loop the constructor and didnt get anything in most cases. Watching for signals using a dbus proxy does work, and looking up available services by name also works. Remember that the dbus values must be converted to native values (eg float(dbusvalue)) to be usable in calculations.  It seems to be better to scan for the original device (eg the can dbus service connected to the battery, and the vebus service) rather than using the system service which has more latency.

# Memory leak

The code has a memory leak that appears when one or more of the modbus units are offline. Quick fix is to restart every 24h. It takes about 14d to get a VSZ od 128mb so its not bad, but needs to be fixed. Other processes are stable. VenusOS has no support for pip. Python is 3.8 so adding the normal tooling to find a memory problem is hard. However `_tracemalloc` c code is compiled in to the tracemalloc.py from the current cpython source code can be adpated (see gc_debug.py) and hopefully after 24h there will be some pointers (lol) to the source of the leak.

No memory leak found in Python objects or variables. Verified with gc, tracemalloc and gippy3. Moving to lower leved with https://github.com/rogerhu/gdb-heap, hopefully VenusOS has the dependencies availalbe.

    sudo apt-get install libc6-dev libc6-dbg python-gi libglib2.0-0-dbg python-ply
    becomes
    opkg install libc6-dev libc6-dbg libglib-2.0-dbg python3-ply
    there is no python-gi  but it looks like that is already installed as GLib is under gi.

Although the dbg packages are listed, they have been removed from the Victron repository. 

Update 2025-06-06

No dbg packages are available. So have stripped out the unecessary scanning and probing code which was causing problem.
There may be more simplifications also as there is no need for ModbusTCP support and that seems to have overcomplicated
the original code base.

Update 2025-06-07

Removing the scanner did not eliminate the leak but it did isolate it to the period when the Growatt is down and not responding. When the Growatt is up, RSS stays static to the kb. This gives the opertunity to add a second growatt on a different unit to see if the leak is reproducable, and then to isolate. Units are now static in the code base so there is less randomness and threading present.

Failed coms message is

    2025-06-07 03:14:51.792831500 2025-06-07 03:14:51,791 INFO rtu:ttyUSB0:9600:1 [rtu:ttyUSB0:9600:1] Device failed: Error reading registers 0x00-0x0a: Modbus Error: [Input/Output] No Response received from the remote unit/Unable to decode response

    2025-06-07 05:53:47,054 ERROR rtu:ttyUSB0:9600:5 [rtu:ttyUSB0:9600:5] Error reading register 0x0c: Modbus Error: [Input/Output] No Response received from the remote unit/Unable to decode response
    Traceback (most recent call last):
      File "/data/dbus-mymodbus-client/device.py", line 551, in init
        self.device_init()
      File "/data/dbus-mymodbus-client/growatt_pv_v120.py", line 554, in device_init
        self.read_info()
      File "/data/dbus-mymodbus-client/device.py", line 204, in read_info
        self.read_info_regs(self.info)
      File "/data/dbus-mymodbus-client/device.py", line 170, in read_info_regs
        self.read_register(reg)
      File "/data/dbus-mymodbus-client/device.py", line 153, in read_register
        raise Exception(rr)
    Exception: Modbus Error: [Input/Output] No Response received from the remote unit/Unable to decode response


pymodbus debug 

    2025-06-07 05:57:58,305 DEBUG pymodbus.transaction SEND: 0x5 0x3 0x0 0xc 0x0 0x2 0x5 0x8c
    2025-06-07 05:57:58,307 DEBUG pymodbus.framer.rtu_framer Changing state to IDLE - Last Frame End - 1749275878.284546, Current Time stamp - 1749275878.307299
    2025-06-07 05:57:58,308 DEBUG pymodbus.client.sync New Transaction state 'SENDING'
    2025-06-07 05:57:58,310 DEBUG pymodbus.transaction Changing transaction state from 'SENDING' to 'WAITING FOR REPLY'
    2025-06-07 05:57:58,812 DEBUG pymodbus.transaction Incomplete message received, Expected 9 bytes Recieved 0 bytes !!!!
    2025-06-07 05:57:58,813 DEBUG pymodbus.transaction Changing transaction state from 'WAITING FOR REPLY' to 'PROCESSING REPLY'
    2025-06-07 05:57:58,813 DEBUG pymodbus.transaction RECV: 
    2025-06-07 05:57:58,814 DEBUG pymodbus.framer.rtu_framer Frame - [b''] not ready
    2025-06-07 05:57:58,815 DEBUG pymodbus.transaction Getting transaction 5
    2025-06-07 05:57:58,816 DEBUG pymodbus.transaction Changing transaction state from 'PROCESSING REPLY' to 'TRANSACTION_COMPLETE'
    2025-06-07 05:57:58,816 ERROR rtu:ttyUSB0:9600:5 [rtu:ttyUSB0:9600:5] Error reading register 0x0c: Modbus Error: [Input/Output] No Response received from the remote unit/Unable to decode response
    Traceback (most recent call last):
      File "/data/dbus-mymodbus-client/device.py", line 551, in init
        self.device_init()
      File "/data/dbus-mymodbus-client/growatt_pv_v120.py", line 554, in device_init
        self.read_info()
      File "/data/dbus-mymodbus-client/device.py", line 204, in read_info
        self.read_info_regs(self.info)
      File "/data/dbus-mymodbus-client/device.py", line 170, in read_info_regs
        self.read_register(reg)
      File "/data/dbus-mymodbus-client/device.py", line 153, in read_register
        raise Exception(rr)
    Exception: Modbus Error: [Input/Output] No Response received from the remote unit/Unable to decode response
    2025-06-07 05:57:58,825 DEBUG pymodbus.transaction Current transaction state - TRANSACTION_COMPLETE

Normal trannsaction

    2025-06-07 05:57:58,242 DEBUG pymodbus.transaction Running transaction 64
    2025-06-07 05:57:58,243 DEBUG pymodbus.transaction SEND: 0x1 0x4 0x0 0x23 0x0 0x5 0xc1 0xc3
    2025-06-07 05:57:58,244 DEBUG pymodbus.framer.rtu_framer Changing state to IDLE - Last Frame End - 1749275878.227894, Current Time stamp - 1749275878.243919
    2025-06-07 05:57:58,244 DEBUG pymodbus.client.sync New Transaction state 'SENDING'
    2025-06-07 05:57:58,245 DEBUG pymodbus.transaction Changing transaction state from 'SENDING' to 'WAITING FOR REPLY'
    2025-06-07 05:57:58,284 DEBUG pymodbus.transaction Changing transaction state from 'WAITING FOR REPLY' to 'PROCESSING REPLY'
    2025-06-07 05:57:58,286 DEBUG pymodbus.transaction RECV: 0x1 0x4 0xa 0x0 0x0 0x8 0x9 0x13 0x91 0x9 0x52 0x0 0x9 0xd4 0xee
    2025-06-07 05:57:58,289 DEBUG pymodbus.framer.rtu_framer Getting Frame - 0x4 0xa 0x0 0x0 0x8 0x9 0x13 0x91 0x9 0x52 0x0 0x9
    2025-06-07 05:57:58,291 DEBUG pymodbus.factory Factory Response[ReadInputRegistersResponse: 4]
    2025-06-07 05:57:58,292 DEBUG pymodbus.framer.rtu_framer Frame advanced, resetting header!!
    2025-06-07 05:57:58,294 DEBUG pymodbus.transaction Adding transaction 1
    2025-06-07 05:57:58,295 DEBUG pymodbus.transaction Getting transaction 1
    2025-06-07 05:57:58,297 DEBUG pymodbus.transaction Changing transaction state from 'PROCESSING REPLY' to 'TRANSACTION_COMPLETE'
    2025-06-07 05:57:58,301 DEBUG pymodbus.transaction Current transaction state - TRANSACTION_COMPLETE


Aftere adding a second fake Growatt, which does not respond there is no memory leak apparent due to Modbus failed responss as above. This implies the leak is only when an existing Growatt goes offline after it has stated up. That indicates that the leak is in th Growatt driver and parent classes itself when the device is offline. Need new stack trace for that.

Trace after init when coms is broken

    Exception: Error reading registers 0x00-0x0a: Modbus Error: [Input/Output] No Response received from the remote unit/Unable to decode response
    Traceback (most recent call last):
      File "./dbus-modbus-client.py", line 123, in update_device
        dev.update()
      File "/data/dbus-mymodbus-client/device.py", line 590, in update
        self.device_update()
      File "/data/dbus-mymodbus-client/device.py", line 594, in device_update
        latency = self.update_data_regs()
      File "/data/dbus-mymodbus-client/device.py", line 424, in update_data_regs
        t = self.read_data_regs(r, self.dbus)
      File "/data/dbus-mymodbus-client/device.py", line 187, in read_data_regs
        raise Exception('Error reading registers %#04x-%#04x: %s' %

Stack trace upto the point of entering pymodbus is clean. Leak must still be there, adding back unit 5 

Looks like it is the pymodbus causing the leak when there is a bad response.

Only difference is that the framer rtu does not call setTransaction and so the pop goes back to the default of non.

The transactions in pymodbus appear to be all clean. 
serial read with timeout is simple, it uses select on the serial port and times out between chars as expected. No sign of a possible leak there. The code is all single threaded, so although the pathway while reading is not quite the same
I cannot see anything done differently when reading 0 bytes due to a timeout or reading n bytes with no timeout. There could be a leak in the C code lower down. Pyserial has no c code by uses termios and fcntl. There are 2 modes for lunux a standard select method and a polling implemented in PosixPollSerial which handles device unplug better. Switching to PosixPollSerial to see if it eliminates the leak.

Does not eliminate the leak. With no missing Units RSS is stable at ru_maxrss=18044 for 6m, with missing units RSS rises.
This implies the problem is not in pyserial since the behaviour is the same regardless of which version is used. 

That implies the problem is after the the exception is thrown, either in pymodbus or higher.

try returning an exception every time from execute to see if that causes a leak. From inside the the transaction manager entry. This will mean none work.

Returning a Exception early results in no leak.

Calls to this cause a leak when the min size is not met.

    read_min = self.client.framer.recvPacket(min_size)  #IEB HERE. IF this recieves no bytes there is a memory leak

Tracked the leak down to os.read which indicates the leak is in the user side of the device driver.  Would have been a lot easier to find with debug symbols from Victron, but that was not going to happen.

Since its in the device driver I wont be able to fix, so the code will backoff retrying to once every 60s if units are timing out and will monitor rss levels and exit if they get greatre than a suitable level. Supervise will restart on exit. 

Backing off when there are timeouts to a retry every 60s if the timeouts continue for 30s seems to have drasticly reduced or eliminated the memory leak.

## packages installed so far for the record

Not all of these are necesary but they will be wiped out when a upgrade comes and this is a record of those added to the standard build searching for the leak. Only resource has a dependny

      142  opkg install python3-pip
      144  opkg install python3-venv
      153  opkg install python3-dev
      178  opkg install gdb  <-- failed attempt to use dgb
      198  opkg install libc6-dev python3-ply <-- needed for gdb
      343  opkg install python3-setuptools <-- failed attempt to build pymodbus
      480  opkg install python3-resource <--- needed to quiclly get process stats

in addition

      pip3 install guppy3  <-- to analyse python heap

# TODO

[x] Add Estron SDM230 support
[ ] Find out the relevance of ProductID and why Victron Support need to allocate one, if they do.
[x] Write a drive for Growatt MIN inverters using the MultiRS dbus area.
[x] Try and add missing data from the SDM230 to the dbus
[-] Connect a p8s exporter to the dbus for more detailed monitoring via Grafana Cloud. seperate exporter.
[ ] Allow control of the PV inverter via VRM.
[x] Find a way of the driver continuing to work when the Growatt goes to sleep at night - made SerialClient run a rescan operation and keep failed devices in the list to be retried
[x] Fix memory leak. Appears to happen when the Growatt goes to sleep. Simple fix is to restart once every 24h.


## VregLink

With some devices, the [VregLink](https://github.com/victronenergy/venus/wiki/dbus-api#the-vreglink-interface)
interface is supported.

The VregLink interface uses a block of up to 125 Modbus holding registers
accessed with the Modbus Read/Write Multiple Registers function (code 23).
Byte data is packed into 16-bit register values MSB first. All accesses
start from offset zero in the VregLink block. The base address is device
specific.

### Write

| Offset | Field   |
| ------ | ------- |
| 0      | VREG ID |
| 1      | Size    |
| 2..N   | Data    |

A write operation contains the VREG to access and, optionally, data for
setting the value. The size field indicates the length in bytes of the
data and must be 2x the number of registers or 1 less. To select a VREG
for a subsequent read, only the first field (VREG ID) should be present.

### Read

| Offset | Field   |
| ------ | ------- |
| 0      | VREG ID |
| 1      | Status  |
| 2      | Size    |
| 3..N   | Data    |

A read operation returns the value of the selected VREG or an error code if
the access failed. The size field indicates the length of the data in bytes.
The actual size of the VREG value is returned even if the requested number
of registers is too small to contain it.

### Status

The following status codes are possible.

| Value  | Meaning                      |
| ------ | ---------------------------- |
| 0      | Success                      |
| 0x8000 | Read: unknown error          |
| 0x8001 | Read: VREG does not exist    |
| 0x8002 | Read: VREG is write-only     |
| 0x8100 | Write: unknown error         |
| 0x8101 | Write: VREG does not exist   |
| 0x8102 | Write: VREG is read-only     |
| 0x8104 | Write: data invalid for VREG |

### Examples

If the VregLink register block begins at address 0x4000, then to read
VREG 0x100 (product ID), the following Modbus transaction would be used.

| Field Name                | Hex | Comment                       |
| ------------------------- | --- | ----------------------------- |
| _Request_                 |     |                               |
| Function                  | 17  | Read/Write Multiple Registers |
| Read Starting Address Hi  | 40  | VregLink base address         |
| Read Starting Address Lo  | 00  |                               |
| Quantity to Read Hi       | 00  |                               |
| Quantity to Read Lo       | 05  |                               |
| Write Starting Address Hi | 40  | VregLink base address         |
| Write Starting address Lo | 00  |                               |
| Quantity to Write Hi      | 00  |                               |
| Quantity to Write Lo      | 01  |                               |
| Write Byte Count          | 02  |                               |
| Write Register Hi         | 01  | PRODUCT_ID                    |
| Write Register Lo         | 00  |                               |
| _Response_                |     |                               |
| Function                  | 17  | Read/Write Multiple Registers |
| Byte Count                | 0A  |                               |
| Read Register Hi          | 01  | PRODUCT_ID                    |
| Read Register Lo          | 00  |                               |
| Read Register Hi          | 00  | Status: success               |
| Read Register Lo          | 00  |                               |
| Read Register Hi          | 00  | Size: 4                       |
| Read Register Lo          | 04  |                               |
| Read Register Hi          | 00  | Product ID                    |
| Read Register Lo          | 12  |                               |
| Read Register Hi          | 34  |                               |
| Read Register Lo          | FE  |                               |

To set VREG 0x10C (description), the Modbus transaction might look as
follows.

| Field Name                | Hex | Comment                       |
| ------------------------- | --- | ----------------------------- |
| _Request_                 |     |                               |
| Function                  | 17  | Read/Write Multiple Registers |
| Read Starting Address Hi  | 40  | VregLink base address         |
| Read Starting Address Lo  | 00  |                               |
| Quantity to Read Hi       | 00  |                               |
| Quantity to Read Lo       | 02  |                               |
| Write Starting Address Hi | 40  | VregLink base address         |
| Write Starting address Lo | 00  |                               |
| Quantity to Write Hi      | 00  |                               |
| Quantity to Write Lo      | 08  |                               |
| Write Byte Count          | 10  |                               |
| Write Register Hi         | 01  | DESCRIPTION1                  |
| Write Register Lo         | 0C  |                               |
| Write Register Hi         | 00  | Size: 11                      |
| Write Register Lo         | 0B  |                               |
| Write Register Hi         | 4D  | 'M'                           |
| Write Register Lo         | 79  | 'y'                           |
| Write Register Hi         | 20  | ' '                           |
| Write Register Lo         | 50  | 'P'                           |
| Write Register Hi         | 72  | 'r'                           |
| Write Register Lo         | 65  | 'e'                           |
| Write Register Hi         | 63  | 'c'                           |
| Write Register Lo         | 69  | 'i'                           |
| Write Register Hi         | 6f  | 'o'                           |
| Write Register Lo         | 75  | 'u'                           |
| Write Register Hi         | 73  | 's'                           |
| Write Register Lo         | 00  | Padding                       |
| _Response_                |     |                               |
| Function                  | 17  | Read/Write Multiple Registers |
| Byte Count                | 04  |                               |
| Read Register Hi          | 01  | DESCRIPTION1                  |
| Read Register Lo          | 0C  |                               |
| Read Register Hi          | 00  | Status: success               |
| Read Register Lo          | 00  |                               |
