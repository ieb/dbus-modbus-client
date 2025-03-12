# VenusOS module for support of Eastron SDM230-Modbus v2
# might work also with other Eastron devices > Product code on 0xfc02 (type u16b) to be added into models overview
# 
# Community contribution by Thomas Weichenberger
# Version 1.2 - 2021-09-16
#
# Thanks to Victron for their open platform and especially for the support of Matthijs Vader
# For any usage a donation to seashepherd.org with an amount of 5 USD/EUR/GBP or equivalent is expected
#
# From https://github.com/M-o-a-T/victron-meter-library with some modifications.
#
# Fixed the probing and added more than one unit to probe.
# Fixed the baud rate, 
# Fixed Reg_f32b which now has a property count
# Added correct device and vendor names.

import logging
import eastron_device as device
import probe
from register import *

log = logging.getLogger(__name__)



#
# Eastron use 32 bit floats in IEE 754 format.
class Reg_f32b(Reg_num):
    count = 2
    coding = ('>f', '>2H')
    rtype = float
        


class Eastron_SDM230v2(device.EnergyMeter,device.CustomName):
    productid = 0xB023 # id assigned by Victron Support... not sure how this works, cant find any documentation.
    productname = 'Eastron SDM230-Modbus v2'
    device_type = 'EnergyMeter'
    vendor_name = 'Eastron'
    min_timeout = 0.5
    phaseconfig = '1P'
    default_access = 'input'

    def __init__(self, *args):
        super(Eastron_SDM230v2, self).__init__(*args)
        # see page 23 in https://www.eastroneurope.com/images/uploads/products/manuals/SDM630MCT-ML_User_manual_V1.2.pdf
        # seems to be correct for a SDM203 also.
        self.info_regs = [
            Reg_u16( 0xfc02,  '/HardwareVersion', access='holding'),   # using the model number here, since it appears to work
            Reg_u16( 0xfc03, '/FirmwareVersion', access='holding'),   # 630 and 120 use this location.
            Reg_u32b( 0xfc00, '/Serial', access='holding'),
        ]

    def phase_regs(self, n):
        s = 0x0002 * (n - 1)
        return [
            Reg_f32b(0x0000 + s, '/Ac/L%d/Voltage' % n,        1, '%.1f V'),
            Reg_f32b(0x0006 + s, '/Ac/L%d/Current' % n,        1, '%.1f A'),
            Reg_f32b(0x000c + s, '/Ac/L%d/Power' % n,          1, '%.1f W'),
            Reg_f32b(0x0048 + s, '/Ac/L%d/Energy/Forward' % n, 1, '%.1f kWh'),
            Reg_f32b(0x004a + s, '/Ac/L%d/Energy/Reverse' % n, 1, '%.1f kWh'),
        ]

    def device_init(self):

        self.read_info()

        phases = 1

        regs = [
            Reg_f32b(0x000c, '/Ac/Power',          1, '%.1f W'),
            Reg_f32b(0x0006, '/Ac/Current',        1, '%.1f A'),
            Reg_f32b(0x0046, '/Ac/Frequency',      1, '%.1f Hz'),
            Reg_f32b(0x0048, '/Ac/Energy/Forward', 1, '%.1f kWh'),
            Reg_f32b(0x004a, '/Ac/Energy/Reverse', 1, '%.1f kWh'),
        ]



        for n in range(1, phases + 1):
            regs += self.phase_regs(n)

        self.data_regs = regs

    def get_ident(self):
        return 'cg_%s' % self.info['/Serial']


# identifier to be checked, if register identical on all SDM630 (only first 16 bytes in u16b of 32 bit register 0xfc02)
models = {
    16384:  {                                                                                                             
        'model':    'SDM230Modbusv2',                                                                                  
        'handler':  Eastron_SDM230v2,                                                                                  
    },      
}
# on a 630MCT the model code is holding register 64511 == 0xFC02 see https://www.eastroneurope.com/images/uploads/products/manuals/SDM630MCT-ML_User_manual_V1.2.pdf 
# this seems to be the same location on a SDM230, but is undocumented... no idea how 2 be detected but the 630 is 3 phase and the 230 is 1 phase.
# Best to also define which registers are being accessed, that confused me for a while.
# may need Reg_u16(0xfc02)
probe.add_handler(probe.ModelRegister(Reg_u16(0x001c, access='holding'), models,
                                      methods=['rtu'],
                                      units=[2],
                                      rates=[9600]))