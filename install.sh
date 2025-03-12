#!/bin/bash

#unpack this diretory into /data/dbus-mymodbus-client
# once only setup
chmod 1755 /data/dbus-mymodbus-client
chmod 755 /data/dbus-mymodbus-client/service/run
chmod 755 /data/dbus-mymodbus-client/service/log/run

cat > /data/rc.local << EOF
#!/bin/bash

/opt/victronenergy/serial-starter/stop-tty.sh ttyUSB0
/opt/victronenergy/serial-starter/stop-tty.sh ttyUSB1
/opt/victronenergy/serial-starter/stop-tty.sh ttyUSB2
echo "Disabled serial starter on ttyUSB0,1,2"

ln -s /data/dbus-mymodbus-client/service /service/dbus-mymodbus-client
echo "Enabled dbus-mymodbus-client"

EOF


