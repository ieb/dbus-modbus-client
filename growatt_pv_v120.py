#
# VenusOS module for support Growatt
# Growatt appears to use a standard Modbus RTU set of registers across all models
# Registers are organised into sets, this code might work with any device, but 
# was written for a Growatt MID 4200 TL using the v1.20 specification as a guide.
# 
# Thanks to Victron for their open platform 
# If you want a license for this code, then MIT or Apache, however 
# it probably needs to adopt whatever Victron has chosen.
#
# 
# From the spec, 
# TL-X(MIN Type):03 register range:0~124,3000~3124;04 register range:3000~3124,3125~3249
#
# DBus location
# A PV Inverter is closest to the com.victronenergy.multi area since it will have 1..n Strings and AC out.
# https://github.com/victronenergy/venus/wiki/dbus#multi-rs-and-other-future-new-inverterchargers
# Could use https://github.com/victronenergy/venus/wiki/dbus#pv-inverters but then it would only have the AC part
# Also could use https://github.com/victronenergy/venus/wiki/dbus#solar-chargers but its not connected to a battery.
#
# using multi-rs as a model.

import logging
import device
import probe
from register import *

log = logging.getLogger()

class Reg_equalsu16(Reg_u16):
    count = 1

    def __init__(self, base, name, matchValue, trueValue=1, falseValue=0, **kwargs):
        super().__init__(base, name, **kwargs)
        self.trueValue = trueValue
        self.falseValue = falseValue
        self.matchValue = matchValue

    def decode(self, values):
        return self.update(self.trueValue if values[0] == self.matchValue else self.falseValue)

class GrowattPVInverter(device.ModbusDevice):
    device_type = 'Energy meter'
    role_names = ['grid', 'pvinverter', 'genset', 'acload', 'evcharger',
                  'heatpump', 'multi']
    allowed_roles = role_names
    default_role = 'multi'
    default_instance = 40
    productid = 0xB088 # made it up, not sure how much it matters
    productname = 'GrowattPV MID4200'
    device_type = 'PV Inverter'
    vendor_name = 'Growatt'
    min_timeout = 0.5
    phaseconfig = '1P'
    nr_phases = 1
    nr_trackers = 2
    default_access = 'input'


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # manufacturer information ascii in reg 34 count 8
        # Firmware acii reg 9 count 3
        # Control firmware reg 12 count 3
        # Serial original text at 23 to 27 holding (count=5)
        # Serial new reg at 209 count 15 ascii
        # Serial new reg TL-X and TL-XH serial at 3000 count 15 ascii
        # reg 44 encodes Input tracker numbers and output phase numbers
        # 0x0203 == 


        self.info_regs = [
            Reg_text( 12, 2, '/HardwareVersion', access='holding'),
            Reg_text( 9, 3, '/FirmwareVersion',  access='holding'),
            Reg_text( 209, 15, '/Serial',        access='holding'), 
        ]

    def device_init_late(self):
        super().device_init_late()

            
        if self.role == 'pvinverter' and self.position is None:
            self.add_settings({'position': ['/Position', 0, 0, 2]})
            self.add_dbus_setting('position', '/Position')

  
        self.dbus.add_path('/CustomName','BackRoof')
        self.dbus.add_path('/NrOfPhases', self.nr_phases)
        self.dbus.add_path('/Ac/NumberOfAcInputs', 0)
        self.dbus.add_path('/MppOperationMode', 2) # mppt
        self.dbus.add_path('/Mode', 3) # inverter only
        self.dbus.add_path('/NrOfTrackers', self.nr_trackers)
        for n in range(0, self.nr_trackers):
            self.dbus.add_path('/Pv/%d/MppOperationMode' % n, 2) # mppt
            self.dbus.add_path('/Pv/%d/Name' % n, 'String %d' % (n+1)) 


    def tracker_regs(self, n):
        s = 4 * n


#/Pv/x/V                                 <- PV array voltage from tracker x+1; todays max number of trackers in a single Victron product is 4
#/Pv/x/P                                 <- PV array power from tracker no. x+1
#/Pv/x/MppOperationMode                  <- Operating mode of tracker no. x+1 (See /MppOperationMode below, since v3.??)
#/Pv/x/Name                              <- Custom name tracker no. x+1

        return [
            Reg_u16(3 + s, '/Pv/%d/V' % n,      10, '%.1f V'),
            Reg_u16(4 + s, '/Pv/%d/I' % n,      10, '%.1f A'),
            Reg_u32b(5 + s, '/Pv/%d/P' % n,      10, '%.1f W'),
        ]

    def device_init(self):

        self.read_info()




#
#/Ac/NumberOfPhases
#/Ac/NumberOfAcInputs
#/Alarms/LowVoltageAcOut                 <- Low AC Out voltage
#/Alarms/HighVoltageAcOut                <- High AC Out voltage
#/Alarms/HighTemperature                 <- High device temperature
#/Alarms/Overload                        <- Inverter overload
#/Alarms/Ripple                          <- High DC ripple
#
#
#
#/NrOfTrackers
#/Yield/Power                            <- PV array power (Watts)
#/Yield/User                             <- Total kWh produced (user resettable)
#/Yield/System                           <- Total kWh produced (not resettable)
#/MppOperationMode                       <- 0 = Off
#                                           1 = Voltage or Current limited
#                                           2 = MPPT Tracker active
#                                           For products with multiple trackers, this is an aggregate of the separate tracker states. When one or more
#                                           trackers are voltage/current limited, this value also shows voltage/current limited. If there is no tracker
#                                           that is voltage/current limited, but one or more trackers are on (so mpp tracking), then the overall state
#                                           is MPP tracking.

# no reg Reg_u32b(0x0001, '/Ac/Current',        1, '%.1f A'),
#
#/Ac/Out/L1/V                           <- Voltage of AC IN1 on L1
#/Ac/Out/L1/F                           <- Frequency of AC IN1 on L1
#/Ac/Out/L1/I                           <- Current of AC IN1 on L1
#/Ac/Out/L1/P                           <- Real power of AC IN1 on L1
# frequency is the same on all phases in a growatt, would be interesting if not.

# reg 105 u16 is a fault code 
# reg 106 u32 is a fault code bitmap
# 0x20000000 == 
        regs = [
            Reg_equalsu16(105, '/Alarms/LowVoltageAcOut', 30),
            Reg_equalsu16(105, '/Alarms/HighVoltageAcOut', 30),
            Reg_equalsu16(105, '/Alarms/HighTemperature', 32),
            Reg_u32b(1, '/Yield/Power',          10, '%.1f W'),
            Reg_u32b(53, '/Yield/User',          10, '%.1f kWh'),
            Reg_u32b(55, '/Yield/System',        10, '%.1f kWh'),
            Reg_u16(37, '/Ac/Out/L1/F',     100, '%.1f Hz'),
            Reg_u16(38, '/Ac/Out/L1/V',      10, '%.1f V'),
            Reg_u16(39, '/Ac/Out/L1/I',      10, '%.1f A'),
            Reg_u32b(40, '/Ac/Out/L1/P',     10, '%.1f W'),
            Reg_u16(37, '/Ac/Frequency',        100, '%.1f Hz'),
            Reg_u32b(35, '/Ac/Power',            10, '%.1f W'),
        ]

        
        for n in range(0, self.nr_trackers):
            regs += self.tracker_regs(n)

        log.info('Setup all registers %s',regs);

        self.data_regs = regs

    def get_ident(self):
        return 'cg_%s' % self.info['/Serial']


# Mode codes are listed on page 58 (footote &*5) 
models = {
    5100: {
        'model':    'Growatt MIN 4200-TL',
        'handler':  GrowattPVInverter,
    },
}
# 5100 = 0x13EC
# Baud rate is set through holding register 22, however other devices may not be able to run on 
# higher rates.
# communication address is in register 30 defaults to 1
probe.add_handler(probe.ModelRegister(Reg_u16(43, access='holding'), models,
                                      methods=['rtu'],
                                      rates=[9600],
                                      units=[1]))