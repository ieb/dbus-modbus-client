# Serial Starter Disable

Serial started can be problematic. It relies on standard USB names, which can change when the hardware detects changes, and if teh udevrules gets damaged in any way it will fail to start the vebus and mk2 services. That will leave a multiplus in an non working state.

This directory contains the critical services that serial starter starts, as static service files. All that serial starter does is monitors /dev/serial-starter for serial ports, and then uses udev and config files to map them to a service, which it creates and starts. These service files are the result of that without the complexity.


# Install

copy the content of services into /data and run the rc.local on each boot to enable the services.

# Alternative

Sadly the Victron documentaton on disabling and Google including AI generated results do not work, or at least not on the Multiplus OS I have. VE_SERVICE and VE_PRODUCT settings are barely present under /run/udev which may be why they are ineffective. See end of this section for an example, and messing too much with udev is probably a bad idea since it seems to be central to the Venus OS configuration for different hardware.

This is what I have found to work.

Remove the serial devices you are using from the udev rules so that no symlink is created in /dev/serial-starter, so that serial-starter will not consider your serial ports.

Note that reloading udev rules and triggering does not always result in a stable state, a reboot is more reliable to ensure all dependencies trigger in the right order.



Line 1 (pattern came from standard Udev rules)

    KERNEL=="ttyUSB[0-9]*|ttyACM[0-9]*", GOTO="serial_end"
 
Last Line

    LABEL="serial_end"

This will cause all ttys matching the pattern to not conside the rules between the 2 statements

To test

Find the syspath of the device in question

     udevadm info -a -n ttyACM0

run a test

     udevadm test  /devices/platform/soc/1c1d400.usb/usb3/3-1/3-1:1.0/tty/ttyACM0

The a secton of the output will state what will happen when the device is added

	rules contain 24576 bytes tokens (2048 * 12 bytes), 9889 bytes strings
	1493 strings (18128 bytes), 978 de-duplicated (8755 bytes), 516 trie nodes used
	GROUP 20 /lib/udev/rules.d/50-udev-default.rules:25
	IMPORT builtin 'usb_id' /lib/udev/rules.d/60-serial.rules:8
	/sys/devices/platform/soc/1c1d400.usb/usb3/3-1/3-1:1.0: if_class 2 protocol 0
	IMPORT builtin 'hwdb' /lib/udev/rules.d/60-serial.rules:8
	IMPORT builtin 'path_id' /lib/udev/rules.d/60-serial.rules:15
	LINK 'serial/by-path/platform-1c1d400.usb-usb-0:1:1.0' /lib/udev/rules.d/60-serial.rules:16
	IMPORT builtin skip 'usb_id' /lib/udev/rules.d/60-serial.rules:19
	LINK 'serial/by-id/usb-WCH.CN_USB_Quad_Serial_BCD97DABCD-if00' /lib/udev/rules.d/60-serial.rules:23
	handling device node '/dev/ttyACM0', devnum=c166:0, mode=0660, uid=0, gid=20
	preserve permissions /dev/ttyACM0, 020660, uid=0, gid=20
	preserve already existing symlink '/dev/char/166:0' to '../ttyACM0'
	found 'c166:0' claiming '/run/udev/links/\x2fserial\x2fby-id\x2fusb-WCH.CN_USB_Quad_Serial_BCD97DABCD-if00'
	creating link '/dev/serial/by-id/usb-WCH.CN_USB_Quad_Serial_BCD97DABCD-if00' to '/dev/ttyACM0'
	preserve already existing symlink '/dev/serial/by-id/usb-WCH.CN_USB_Quad_Serial_BCD97DABCD-if00' to '../../ttyACM0'
	found 'c166:0' claiming '/run/udev/links/\x2fserial\x2fby-path\x2fplatform-1c1d400.usb-usb-0:1:1.0'
	creating link '/dev/serial/by-path/platform-1c1d400.usb-usb-0:1:1.0' to '/dev/ttyACM0'
	preserve already existing symlink '/dev/serial/by-path/platform-1c1d400.usb-usb-0:1:1.0' to '../../ttyACM0'
	created db file '/run/udev/data/c166:0' for '/devices/platform/soc/1c1d400.usb/usb3/3-1/3-1:1.0/tty/ttyACM0' 



An example for ttyS3 which is controlled by serial starter


		rules contain 24576 bytes tokens (2048 * 12 bytes), 9889 bytes strings
		1493 strings (18128 bytes), 978 de-duplicated (8755 bytes), 516 trie nodes used
		GROUP 20 /lib/udev/rules.d/50-udev-default.rules:25
		LINK 'serial-starter/ttyS3' /etc/udev/rules.d/serial-starter.rules:2
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
		handling device node '/dev/ttyS3', devnum=c4:67, mode=0660, uid=0, gid=20
		preserve permissions /dev/ttyS3, 020660, uid=0, gid=20
		preserve already existing symlink '/dev/char/4:67' to '../ttyS3'
		found 'c4:67' claiming '/run/udev/links/\x2fserial-starter\x2fttyS3'
		creating link '/dev/serial-starter/ttyS3' to '/dev/ttyS3'
		creating symlink '/dev/serial-starter/ttyS3' to '../ttyS3'
		created db file '/run/udev/data/c4:67' for '/devices/platform/soc/1c28c00.serial/tty/ttyS3'


/run/udev contains the runtime state and can be grepped for VE settings

		root@nanopi:~# grep -r VE_ /run/udev/
		grep: /run/udev/watch/11: No such file or directory
		grep: /run/udev/watch/10: No such file or directory
		grep: /run/udev/watch/9: No such file or directory
		grep: /run/udev/watch/8: No such file or directory
		grep: /run/udev/watch/7: No such file or directory
		grep: /run/udev/watch/6: No such file or directory
		grep: /run/udev/watch/5: No such file or directory
		grep: /run/udev/watch/4: No such file or directory
		/run/udev/data/n2:E:VE_NAME=VE.Can port
		/run/udev/data/c4:66:E:VE_PRODUCT=builtin-vedirect
		/run/udev/data/c4:66:E:VE_SERVICE=vedirect
		/run/udev/data/c4:65:E:VE_PRODUCT=builtin-vedirect
		/run/udev/data/c4:65:E:VE_SERVICE=vedirect
		grep: /run/udev/control: No such device or address
		root@nanopi:~# 



To reload the rules

     udevadm control --reload-rules
     udevadm trigger