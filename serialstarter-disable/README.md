# Serial Starter Disable

Serial started can be problematic. It relies on standard USB names, which can change when the hardware detects changes, and if teh udevrules gets damaged in any way it will fail to start the vebus and mk2 services. That will leave a multiplus in an non working state.

This directory contains the critical services that serial starter starts, as static service files. All that serial starter does is monitors /dev/serial-starter for serial ports, and then uses udev and config files to map them to a service, which it creates and starts. These service files are the result of that without the complexity.


# Install

copy the content of services into /data and run the rc.local on each boot to enable the services.