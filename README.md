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

In settings using dbus-spy set /Settings/DynamicGeneration/energyDifference to the desired difference between import and export. the SDM230 will then monitor the difference and set /Settings/DynamicGeneration/derateGeneration to 1 if the difference falls below the desired value. This should cause all generators to not export energy to the grid. When above, generators should stay withing the g100 setting dependent on installation. Generators should still meet any demand on the local supply.

^^^^ doesnt work well for my Growatt which appears to simply set the power outout to the export limit and not charge batteries when derated. This may be a interaction between the inverter also sensing the grid power comming in which eventually confuses the growatt. So assuming that is the case, it will be better to look at if power is needed on the home AC and directly control the growatt output using events from the vebus service and grid meter service.

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

# TODO

[x] Add Estron SDM230 support
[ ] Find out the relevance of ProductID and why Victron Support need to allocate one, if they do.
[x] Write a drive for Growatt MIN inverters using the MultiRS dbus area.
[x] Try and add missing data from the SDM230 to the dbus
[ ] Connect a p8s exporter to the dbus for more detailed monitoring via Grafana Cloud.
[ ] Allow control of the PV inverter via VRM.
[ ] Find a way of the driver continuing to work when the Growatt goes to sleep at night - made SerialClient run a rescan operation and keep failed devices in the list to be retried


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
