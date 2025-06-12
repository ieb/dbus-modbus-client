# Growatt and SDM230 ModbusRTU montitor for Multiplus II

This code was originally from https://github.com/victronenergy/dbus-modbus-client however it has been heavilly modified to implement specific requirements and fix stability issues.

Reads data from Modbus devices and publishes on D-Bus.  Service names and
paths are per the [Victron D-Bus specification](https://github.com/victronenergy/venus/wiki/dbus).


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

    /data/dbus-mymodbus-client/dbus-modbus-client.py -x -s /dev/ttyUSB0 -r 9600

When done, start the service

    svc -u /service/dbus-mymodbus-client

# How does the driver work ?

Quick notes....

The driver is based on the Victron dbus-modbus-client driver with modifications and simplifications.

## Main changes

* The driver only has RTU code, the UDP and TCP code has been removed as its not used.
* Scanning has been removed in place of configuration since the serial connections are hardware and fixed. 
* Only a single phase Eastron SDM230 and a Growatt MID PV inverter are supported, all other devices were removed.
* When a device (eg PV inverter) goes offline, the driver polls it every 60s to detect when it comes back online.
* The PV inverter output limit is dynamically managed on every reading to track demand and meet import export requriements of the installation, in addition to any G100 requirements. This allows the Multiplus to derate the solar array, reducing heat generation and increasing peak power to meet spikes in demand.


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

## Paths

pvinverter:/dynamicGenerationStatus text status
pvinverter:/dynamicGenerationPower calculated instantaneous power demand
pvinverter:/dynamicGenerationPowerMax pvinveerter max power setting (holding register 3)
/Settings/DynamicGeneration/energyDifference minimum allowable difference between import and export, below this active tracking is activated, in kwh see the grid meter /Ac/Energy/Consumption value for the current value.
/Settings/DynamicGeneration/derateGeneraton 1=enable, 0=disable


# Discoveries

see NOTEBOOK.md


# TODO

[x] Add Estron SDM230 support
[ ] Find out the relevance of ProductID and why Victron Support need to allocate one, if they do.
[x] Write a drive for Growatt MIN inverters using the MultiRS dbus area.
[x] Try and add missing data from the SDM230 to the dbus
[-] Connect a p8s exporter to the dbus for more detailed monitoring via Grafana Cloud. seperate exporter.
[ ] Allow control of the PV inverter via VRM.
[x] Find a way of the driver continuing to work when the Growatt goes to sleep at night - made SerialClient run a rescan operation and keep failed devices in the list to be retried
[x] Fix memory leak. Appears to happen when the Growatt goes to sleep. Simple fix is to restart once every 24h.



