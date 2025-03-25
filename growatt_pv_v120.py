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

import device
import probe
from register import *
import time

import logging
log = logging.getLogger(__name__)

DERATE_MODE = {
    0: 'None',
    1: 'PV',
    2: '*',
    3: 'Vac',
    4: 'Fac',
    5: 'Tboost',
    6: 'Tinv',
    7: 'Control',
    8: '*',
    9: 'Overback'
    }
EXPORT_LIMIT_TYPE = {
    0: 'Disable',
    1: 'RS485',
    2: 'RS232',
    3: 'CT',
    }
G100_FAIL_SAFE = {
    0: 'Disable',
    1: 'Enable',
    }


class Reg_equalsu16(Reg_u16):
    count = 1

    def __init__(self, base, name, matchValue, trueValue=1, falseValue=0, **kwargs):
        super().__init__(base, name, **kwargs)
        self.trueValue = trueValue
        self.falseValue = falseValue
        self.matchValue = matchValue

    def decode(self, values):
        return self.update(self.trueValue if values[0] == self.matchValue else self.falseValue)

class GrowattPVInverter(device.ModbusDevice, device.CustomName):
    device_type = 'PV Inverter'
    role_names = ['pvinverter']
    allowed_roles = role_names
    default_role = 'pvinverter'
    default_instance = 40
    productid = 0xB089 # made it up, not sure how much it matters
    productname = 'GrowattPV MID4200'
    device_type = 'PV Inverter'
    vendor_name = 'Growatt'
    min_timeout = 0.5
    phaseconfig = '1P'
    nr_phases = 1
    nr_trackers = 2
    default_access = 'input'
    position = None



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
            Reg_u16(42, '/Internal/g100FailSafe',  1, '%.1f', access='holding'),
            Reg_u16(104, '/Internal/DerateMode',   1, '%.1f', access='holding'),
            Reg_u16(122, '/Internal/exportLimitType',           1, '%.1f', access='holding'),
            Reg_u16(123, '/Internal/ExportLimitPowerRate',      10, '%.1f %%', access='holding'),
            Reg_u16(3000, '/Internal/g100FailSafePowerRate',      10, '%.1f W', access='holding'),
        ]





    def device_init_late(self): 
        super().device_init_late()


        if self.role == 'pvinverter' and self.position is None:
            self.add_settings({'position': ['/Position', 0, 0, 2]})
            self.add_dbus_setting('position', '/Position')


        self.dbus.add_path('/DeviceName','GrowattPV MID4200TL')
        self.dbus.add_path('/NrOfPhases',1)
        self.dbus.add_path('/Ac/MaxPower','4200 W')
        self.dbus.add_path('/Ac/Phase',1)
        

    def tracker_regs(self, n):
        s = 4 * n
        return [
            Reg_u16(3 + s, '/Internal/Pv/%d/V' % n,      10, '%.1f V'),
            Reg_u16(4 + s, '/Internal/Pv/%d/I' % n,      10, '%.1f A'),
            Reg_u32b(5 + s, '/Internal/Pv/%d/P' % n,      10, '%.1f W'),
            Reg_u32b(59 + s, '/Internal/Pv/%d/Energy/Today' % n,  10, '%.1f W'),
            Reg_u32b(61 + s, '/Internal/Pv/%d/Energy/Total' % n,  10, '%.1f W'),
        ]

    def device_init(self):

        self.read_info()


        # standard pviverter model
        regs = [
            Reg_u32b(35, '/Ac/Power',                 10, '%.1f W'),
            Reg_u16(39,  '/Ac/Current',               10, '%.1f A'),
            Reg_u16(38,  '/Ac/Voltage',               10, '%.1f V'),
            Reg_u32b(55, '/Ac/Energy/Forward',        10, '%.1f kWh'),
            Reg_u16(39,  '/Ac/L1/Current',            10, '%.1f A'),
            Reg_u32b(35, '/Ac/L1/Power',              10, '%.1f W'),
            Reg_u32b(53, '/Ac/L1/Energy/Forward',     10, '%.1f kWh'),
            Reg_u16(38,  '/Ac/L1/Voltage',            10, '%.1f V'),
            Reg_u16(105, '/ErrorCode'),
            Reg_u16(93, '/Internal/InverterTemp',      10, '%.1f C'),
            Reg_u16(94, '/Internal/IPMTemp',      10, '%.1f C'),
            Reg_u16(95, '/Internal/BoostTemp',      10, '%.1f C'),

            # Victron values
            # 0=Startup 0; 
            # 1=Startup 1; 
            # 2=Startup 2; 3=Startup
            # 3; 4=Startup 4; 5=Startup 5; 6=Startup 6; 7=Running;
            # 8=Standby; 9=Boot loading; 10=Error
            Reg_mapu16(0, '/StatusCode', {
                0: 0, # waiting
                1: 7, # normal running
                2: 10, # fault
            })
        ]

        
        for n in range(0, self.nr_trackers):
            regs += self.tracker_regs(n)

        self.data_regs = regs

    def get_ident(self):
        return 'pv_%s' % self.info['/Serial']


# Mode codes are listed on page 58 (footote &*5) 
models = {
    5100: {
        'model':    'Growatt MIN 4200-TL',
        'handler':  GrowattPVInverter,
    },
}


class ForcedModelRegister(probe.ModelRegister):

    
    def probe(self, spec, modbus, timeout=None):
        log.info(f'Force Growatt Device active')
        # assume it is there, and let the code handle failures and retries when its up.
        return GrowattPVInverter(spec, modbus, 'Growatt MIN 4200-TL')

# 5100 = 0x13EC
# Baud rate is set through holding register 22, however other devices may not be able to run on 
# higher rates.
# communication address is in register 30 defaults to 1
probe.add_handler(probe.ModelRegister(Reg_u16(43, access='holding'), models,
                                      methods=['rtu'],
                                      rates=[9600],
                                      units=[1]))