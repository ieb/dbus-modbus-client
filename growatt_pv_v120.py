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
import os
import dbus
import math
from register import *
import time
from vedbus import weak_functor
from utils import private_bus
from ve_utils import unwrap_dbus_value

import logging
log = logging.getLogger(__name__)



# could not get formatting to work, so gave up e16, mapu16 nothing seems to work 
DERATE_MODE = {
    0: 'cNOTDerate', 
    1: 'cPVHighDerate',
    2: 'cPowerConstantDerate', 
    3: 'cGridVHighDerate',
    4: 'cFreqHighDerate', 
    5: 'cDcSoureModeDerate', 
    6: 'cInvTemprDerate', 
    7: 'cActivePowerOrder', 
    8: 'cLoadSpeedProcess',
    9: 'cOverBackbyTime', 
    10: 'cInternalTemprDerate', 
    11: 'cOutTemprDerate', 
    12: 'cLineImpeCalcDerate', 
    13: 'cParallelAntiBackflowDerate', 
    14: 'cLocalAntiBackflowDerate', 
    15: 'cBdcLoadPriDerate', 
    16: 'cChkCTErrDerate',
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


class BusItemTracker(object):
    '''
    Watches the dbus for changes to a single value on a service.
    The value is available at .value, it will be None is no value is present
    @param bus dbus object, session or system
    @param serviceName  eg com.victronenergy.system
    @param path path of the property eg /Ac/L1/Power
    '''
    def __init__(self, bus, serviceName,  path, onchange):
        self._path = path
        self._value = None
        self._onchange = onchange
        self._values = {}
        self._match = bus.get_object(serviceName, path, introspect=False).connect_to_signal(
            "ItemsChanged", self._items_changed_handler)
        log.info(f' added tracker for  {serviceName} {path}')


    def __del__(self):
        self._match.remove()
        self._match = None
    
    @property
    def value(self):
        return self._value
    

    # TODO, handle items being removed
    def _items_changed_handler(self, items):
        if not isinstance(items, dict):
            return
        for path, changes in items.items():
            try:
                self._values[str(path)] = unwrap_dbus_value(changes['Value'])
            except KeyError:
                continue
        self._onchange(self._values)


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




    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.maxPowerPercent = 0
        self.maxPowerMovingAverage = 100
        self.position = None
        self.gridTracker = None
        self.systemTracker = None
        self.vebusTracker = None
        self.batteryTracker = None
        self.g100Enabled = False
        self.timeout = GrowattPVInverter.min_timeout

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


    def destroy(self):
        log.info(f'Destroy device {self}')
        if self.gridTracker:
            self.gridTracker.__del__()
            self.gridTracker = None
        if self.batteryTracker:
            self.batteryTracker.__del__()
            self.batteryTracker = None
        if self.systemTracker != None:
            self.systemTracker.__del__() 
            self.systemTracker = None
        if self.vebusTracker != None:
            self.vebusTracker.__del__() 
            self.vebusTracker = None
        '''
        if self.pvPowerTracker != None:
            self.pvPowerTracker.__del__()
            self.pvPowerTracker = None
        if self.batteryPowerTracker != None:
            self.batteryPowerTracker.__del__()
            self.batteryPowerTracker = None
        if self.batterySocTracker != None:
            self.batterySocTracker.__del__()
            self.batterySocTracker = None
        '''

    '''
    '''



    def device_init_late(self): 
        super().device_init_late()


        if self.role == 'pvinverter' and self.position is None:
            self.add_settings({'position': ['/Position', 0, 0, 2]})
            self.add_dbus_setting('position', '/Position')


        self.dbus.add_path('/DeviceName','GrowattPV MID4200TL')
        self.dbus.add_path('/NrOfPhases',1)
        self.dbus.add_path('/Ac/MaxPower','4200 W')
        self.dbus.add_path('/Ac/Phase',1)
        self.dbus.add_path('/dynamicGenerationStatus','-',writeable=True)
        self.dbus.add_path('/dynamicGenerationPower',0,writeable=True)
        self.dbus.add_path('/dynamicGenerationMaxPower',0,writeable=True)



        log.info('Adding Energy Limit settings')
        self.add_settings({
            'energyDifference':       ['/Settings/DynamicGeneration/energyDifference',0,0,1000000],
            'derateGeneration':      ['/Settings/DynamicGeneration/derateGeneration',0,0,1],
        })
        if self.settings['energyDifference'] == 0:
            self.dbus['/dynamicGenerationStatus'] = 'Not Configured'
        elif self.settings['derateGeneration'] == 0:
            self.dbus['/dynamicGenerationStatus'] = 'Configured, disabled'
        else:
            self.dbus['/dynamicGenerationStatus'] = 'Configured, enabled'



        # paths
        # grid meter /Ac/Energy/Consumption
        # system /Ac/Consumption/L1/Power   power requirement from house
        # system /Ac/Grid/L1/Power  power from the grid
        # system /Ac/PvOnGrid/L1/Power   power from PV
        # system /Dc/Battery/Power power to Battery +ve == charging
        # system /Dc/Battery/Soc state of charge 0-100
        # system /Ac/In/0/ServiceName grid meter service name or scan for the device
        self.state = {
            'pv:/Ac/Power': 0,
            'vebus:/Ac/Out/P': 0,
            'grid:/Ac/Power': 0,
            'vebus:/State': 0,
            'vebus:/Leds/Absorbtion': 0,
            'vebus:/Leds/Bulk': 0,
            'vebus:/Leds/Float': 0,
            'vebus:/Leds/Inverter': 0,
            'vebus:/Ac/ActiveIn/P': 0,
            'grid:/Ac/Energy/Consumption': 1000000000,
            'battery:/Dc/0/Power': 0,
            'battery:/Dc/0/Voltage': 55, # assume fully charged to start with, should update fast.
            'battery:/Soc': 100,
        }

        self.createServiceTrackers()
        self.setG100()

    def createServiceTrackers(self):
        if (self.gridTracker == None 
            or self.batteryTracker == None 
            or self.systemTracker == None
            or self.vebusTracker == None):
            dbusConn = dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus()
            dbusObjects = {}
            dbusNames = dbusConn.list_names()
            gridServiceName = None
            batteryServiceName = None
            vebusServiceName = None
            for x in dbusNames:
                s = str(x)
                if s.startswith('com.victronenergy.grid'):
                    gridServiceName = s
                elif s.startswith('com.victronenergy.battery'):
                    batteryServiceName = s
                elif s.startswith('com.victronenergy.vebus'):
                    vebusServiceName = s
            log.info(f' grid service name {gridServiceName}')
            log.info(f' battery service name {batteryServiceName}')
            log.info(f' vebus service name {vebusServiceName}')

            if (self.gridTracker == None 
                and gridServiceName != None):
                self.gridTracker = BusItemTracker(dbusConn, gridServiceName, '/', self.gridChanged)
            if (self.batteryTracker == None
                and batteryServiceName != None):
                self.batteryTracker = BusItemTracker(dbusConn, batteryServiceName, '/', self.batteryChanged)
            if (self.vebusTracker == None
                and vebusServiceName != None):
                self.vebusTracker = BusItemTracker(dbusConn, vebusServiceName, '/', self.vebusChanged)
            if self.systemTracker == None:
                self.systemTracker = BusItemTracker(dbusConn, 'com.victronenergy.system', '/', self.systemChanged)
            

        '''
        self.pvPowerTracker = BusItemTracker(dbusConn, 'com.victronenergy.system', '/Ac/PvOnGrid/L1/Power', self.pvPowerChanged)
        self.batteryPowerTracker = BusItemTracker(dbusConn, 'com.victronenergy.system', '/Dc/Battery/Power', self.batteryPowerChanged)
        self.batterySocTracker = BusItemTracker(dbusConn, 'com.victronenergy.system', '/Dc/Battery/Soc', self.batterySocChanged)
        log.info(f'Creating power consumption')
        self.consumptionPowerDI = VeDbusItemImport(dbusConn, gridServiceName, '/Ac/Energy/Consumption')
        log.info(f' consumption')
        
        self.gridPowerDI = VeDbusItemImport(dbusConn, 'com.victronenergy.system', '/Ac/Grid/L1/Power')
        self.pvPowerDI = VeDbusItemImport(dbusConn, 'com.victronenergy.system', '/Ac/PvOnGrid/L1/Power')
        self.batteryPowerDI = VeDbusItemImport(dbusConn, 'com.victronenergy.system', '/Dc/Battery/Power')
        self.batterySocDI = VeDbusItemImport(dbusConn, 'com.victronenergy.system', '/Dc/Battery/Soc')
        log.info(f'Done Creating power consumption')
      
        '''


    def setG100(self):
        if not self.g100Enabled:            
            log.info("Forcing G100 limits based on 4200W output and RS485 Meter")
            # set max power to 100, just in case the system is derated.
            self.write_register(Reg_u16(3, access='holding'), 100)
            # enable Grid meter
            self.write_register(Reg_u16(122, access='holding'), 1) # RS4885
            # set power to 1000*3680/4200 = 876.1904761905.04761904762
            self.write_register(Reg_u16(123, access='holding'), 876) # 87.6%
            # g100Failsafe assuming this is the only exporting source
            self.write_register(Reg_u16(3000, access='holding'), 876) # 87.6%
            self.g100Enabled = True


    def updateIfDef(self, cls, key, source ):
        if key in source:
            self.state[f'{cls}:{key}'] = source[key]

    def systemChanged(self, values):
        self.updateIfDef('system', '/Ac/Grid/L1/Power', values)
        self.updateIfDef('system', '/Ac/PvOnGrid/L1/Power', values)
        self.updateIfDef('system', '/Dc/Battery/Power', values)
        self.updateIfDef('system', '/Dc/Battery/Soc', values)
        self.update_export()
        ''' 
                    gridPower = self.setIfDef(values,'/Ac/Grid/L1/Power'),
                    pvPower = self.setIfDef(values,'/Ac/PvOnGrid/L1/Power'),
                    batteryPower = self.setIfDef(values,'/Dc/Battery/Power'),
                    batterySoc = self.setIfDef(values,'/Dc/Battery/Soc'))
        '''

    def gridChanged(self, values):
        self.updateIfDef('grid', '/Ac/Energy/Consumption', values)
        self.updateIfDef('grid', '/Ac/L1/Power', values)
        self.updateIfDef('grid', '/Ac/Power', values)
        self.update_export()

    def batteryChanged(self, values):
        self.updateIfDef('battery', '/Dc/0/Power', values)
        self.updateIfDef('battery', '/Dc/0/Voltage', values)
        self.updateIfDef('battery', '/Soc', values) # SOc changes slowly so not that usefull
        self.update_export()

    def vebusChanged(self, values):
        self.updateIfDef('vebus', '/Ac/ActiveIn/L1/P', values)
        self.updateIfDef('vebus', '/Ac/ActiveIn/P', values)
        self.updateIfDef('vebus', '/Ac/Out/L1/P', values)
        self.updateIfDef('vebus', '/Ac/Out/P', values)
        self.updateIfDef('vebus', '/Dc/0/Power', values)
        self.updateIfDef('vebus', '/Devices/0/Ac/In/P', values)
        self.updateIfDef('vebus', '/Devices/0/Ac/Inverter/P', values)
        self.updateIfDef('vebus', '/Devices/0/Ac/Out/P', values)
        self.updateIfDef('vebus', '/Hub4/DisableCharge', values)
        self.updateIfDef('vebus', '/Leds/Absorbtion', values)  # LEDs: 0 = Off, 1 = On, 2 = Blinking, 3 = Blinking inverted
        self.updateIfDef('vebus', '/Leds/Bulk', values)
        self.updateIfDef('vebus', '/Leds/Float', values)
        self.updateIfDef('vebus', '/Leds/Inverter', values)  
        self.updateIfDef('vebus', '/Mode', values) # 1=Charger Only;2=Inverter Only;3=On;4=Off
        self.updateIfDef('vebus', '/Soc', values)
        self.updateIfDef('vebus', '/State', values) # 0=Off;1=Low Power Mode;2=Fault;3=Bulk;4=Absorption;5=Float;6=Storage;7=Equalize;8=Passthru;9=Inverting;10=Power assist;
        self.updateIfDef('vebus', '/VeBusChargeState', values) #  1. Bulk 2. Absorption 3. Float 4. Storage 5. Repeat absorption 6. Forced absorption 7. Equalise 8. Bulk stopped
        self.updateIfDef('vebus', '/VeBusMainState', values)
        self.update_export()


    def update_export(self ):
        '''
        After a few minutes of running this is the state that has been accumulated due to updates
        state:{'grid:/Ac/Energy/Consumption': 3643.080078125, 
        'grid:/Ac/L1/Power': 0.0, 
        'grid:/Ac/Power': 0.0, 
        'pv:/Ac/Power': 198.7, 
        'pv:/Internal/ExportLimitPowerRate': 100.0, 
        'vebus:/Ac/ActiveIn/L1/P': 67, 
        'vebus:/Ac/Out/L1/P': 14, 
        'vebus:/Ac/Out/P': 14, 
        'vebus:/Dc/0/Power': 51, 
        'vebus:/Devices/0/Ac/In/P': 67, 
        'vebus:/Devices/0/Ac/Out/P': 14, 
        'system:/Ac/Grid/L1/Power': 0.0,  << dup grid
        'system:/Ac/PvOnGrid/L1/Power': 198.7, << dup pv
        'vebus:/Devices/0/Ac/Inverter/P': 53, 
        'vebus:/State': 3,   

        0=Off;1=Low Power Mode;2=Fault;3=Bulk;4=Absorption;5=Float;
                                           6=Storage;7=Equalize;8=Passthru;9=Inverting;10=Power assist;
                                           11=Power supply mode;244=Sustain(Prefer Renewable Energy);252=External control

        'vebus:/Leds/Bulk': 1, 
        'system:/Dc/Battery/Power': 0  << static
        }         } 

        '''
        # add local values to state
        if '/Ac/Power' in self.dbus and self.dbus['/Ac/Power'] != None:
            self.state['pv:/Ac/Power'] = float(self.dbus['/Ac/Power'])
        if '/Internal/ExportLimitPowerRate' in self.dbus and self.dbus['/Internal/ExportLimitPowerRate'] != None:
            self.state['pv:/Internal/ExportLimitPowerRate'] = float(self.dbus['/Internal/ExportLimitPowerRate'])
        log.debug(f' state:{self.state} ')

        # strategy
        # there are 3 AC sources, grid, pv and home. Home always consumes, grid and pv supply.
        # on the grid meter +power is importing from the grid.
        # on the pv power +ve power is generating
        # 
        # power consumption is calculated  grid + pv + vebus active in 
        # the inverter will vary to keep the grid at 0.
        # if in a state where we need to limit output to the grid, then the pv power should be adjusted
        # to provide as much power as required 
        # pvlimit = pv + abs(vebus) + grid + 100
        #
        # 100 to ensure the pv output rises as the inverter takes more power
        # power being consumed by house 
        pvpower = self.state["pv:/Ac/Power"]  # poutput of the pv array +ve == generating
        gridpower = self.state['grid:/Ac/Power'] # grid power +ve == supply from the grid
        inverterpower = self.state['vebus:/Ac/ActiveIn/P'] # input to the MP +ve == input
        # power consumed by the house is grid + pv + inverter (which is sign inverted)
        housepower = gridpower+pvpower-inverterpower

        batteryPower = self.state['battery:/Dc/0/Power']
        batteryVoltage = self.state['battery:/Dc/0/Voltage']
        batterySoc = self.state['battery:/Soc']

        # pv limit needs to power the house as if the inverter was switched off.
        pvlimit = gridpower+pvpower




        # now take into account the inverter and bms
        veBusState = self.state["vebus:/State"]

        # have seen states of 0,3,4, 0 when not set and when idle.
        
        # Not convinced this helps during charging.
        # 
        adjust = 0
        if veBusState == 3 or self.state["vebus:/Leds/Absorbtion"] == 1:
            # bulk, let power ramp up slowly, only appears on a change in state
            adjust = 1
            pvlimit = pvlimit + 20
        elif veBusState == 4  or self.state["vebus:/Leds/Bulk"] == 1:
            # bulk, let power ramp up slowly, only appears on a change in state
            adjust = 2
            pvlimit = pvlimit + 40
        elif batteryPower > 0 and batteryPower < 3200:
            adjust = 3
            # the batery is charging, but it will only take availablw 
            # energy so we must increase the pv limit to allow charging to ramp up
            # one way is to increse the pv limit by 500W
            # the BMS current limit is set to about 60A so above 3200W
            # do not add additional power to the limit.
            if batterySoc < 90 or batteryVoltage < 54.5:
                adjust = 4
                pvlimit = pvlimit + 500
        
        if batteryPower < -100:
            # The battery is discharging at more than 100W
            # PV should try and replace this power, so add the power
            # that the invereter is producing to th epv limit
            pvlimit = pvlimit - inverterpower


        log.debug(f'batteryPower:{batteryPower} batterySoc:{batterySoc}')
        log.debug(f'pvlimit:{pvlimit} pv:{pvpower} g:{gridpower} i:{inverterpower} h:{housepower} s:{self.state["vebus:/State"]} a:{adjust}' )


        if self.settings['energyDifference'] == 0:
            self.dbus['/dynamicGenerationStatus'] = 'Not Configured'
            self.dbus['/dynamicGenerationMaxPower'] = 4200
        elif self.settings['derateGeneration'] == 0:
            self.dbus['/dynamicGenerationStatus'] = 'Configured, G100'
            self.dbus['/dynamicGenerationMaxPower'] = 4200
        elif pvpower <  50:
            self.dbus['/dynamicGenerationStatus'] = 'PV offline'
            self.maxPowerPercent = 0  # forces reset when PV comes back online.
            self.maxPowerMovingAverage = 100
        elif batteryPower > 0 and ( batterySoc < 90 or batteryVoltage < 54):
            # note state of charge will not update till it changes as it is a int.
            # but the battery voltage below about 54v is 90% charge also.
            if self.set_max_power(4200,f'charging state:{veBusState}:{adjust} batV:{batteryVoltage} batP:{batteryPower}'):
                self.dbus['/dynamicGenerationStatus'] = 'Configured, charging'
        else:
            energyDifferenceSetting = float(self.settings['energyDifference'])
            consumption = self.state['grid:/Ac/Energy/Consumption']
            energyDifferenceOffset = consumption - (float)(energyDifferenceSetting)
            log.debug(f'energy difference {energyDifferenceOffset} {pvlimit} {batterySoc} {batteryPower}')
            if energyDifferenceOffset < -2 and energyDifferenceOffset > -200:
                self.dbus['/dynamicGenerationPower'] = pvlimit
                if self.set_max_power(pvlimit,f'limiting state:{veBusState}:{adjust} batV:{batteryVoltage} batP:{batteryPower}'):
                    self.dbus['/dynamicGenerationStatus'] = 'Configured, limiting'
            else:
                if self.set_max_power(4200,'non limiting'):
                    self.dbus['/dynamicGenerationMaxPower'] = 4200
                if abs(energyDifferenceOffset) > 200: 
                    self.dbus['/dynamicGenerationStatus'] = 'Configured, out of range'
                else:
                    self.dbus['/dynamicGenerationStatus'] = 'Configured, not limiting'


    def set_max_power(self, pvlimit, cause):
        powerPercent = 100*pvlimit/4200
        if powerPercent < 2:
            powerPercent = 2
        if powerPercent > 100:
            powerPercent = 100
        self.maxPowerMovingAverage = powerPercent*0.2 + self.maxPowerMovingAverage*0.8 
        if abs(self.maxPowerPercent - self.maxPowerMovingAverage) > 1:
            self.maxPowerPercent = self.maxPowerMovingAverage
            maxPowerPercentInt = math.ceil(self.maxPowerPercent)
            self.dbus['/dynamicGenerationMaxPower'] = maxPowerPercentInt*4200/100
            log.info(f'setting limit to  {maxPowerPercentInt} % for {pvlimit} W due to {cause}')
            self.write_register(Reg_u16(3, access='holding'), maxPowerPercentInt)
            return True
        return False




        

    def tracker_regs(self, n):
        s = 4 * n
        return [
            Reg_u16(3 + s, '/Internal/Pv/%d/V' % n,      10, '%.1f V',max_age=5),
            Reg_u16(4 + s, '/Internal/Pv/%d/I' % n,      10, '%.1f A',max_age=5),
            Reg_u32b(5 + s, '/Internal/Pv/%d/P' % n,      10, '%.1f W',max_age=5),
            Reg_u32b(59 + s, '/Internal/Pv/%d/Energy/Today' % n,  10, '%.1f W',max_age=10),
            Reg_u32b(61 + s, '/Internal/Pv/%d/Energy/Total' % n,  10, '%.1f W',max_age=10),
        ]

    def device_init(self):

        self.read_info()


        # standard pviverter model
        # see "Growatt PV Inverter Modbus RS485 RTU Protocol v120.pdf"
        regs = [
            Reg_u32b(35, '/Ac/Power',                 10, '%.1f W',max_age=5),
            Reg_u32b(35, '/Ac/L1/Power',              10, '%.1f W',max_age=5),
            Reg_u16(39,  '/Ac/Current',               10, '%.1f A',max_age=5),
            Reg_u16(39,  '/Ac/L1/Current',            10, '%.1f A',max_age=5),
            Reg_u16(38,  '/Ac/Voltage',               10, '%.1f V',max_age=5),
            Reg_u16(38,  '/Ac/L1/Voltage',            10, '%.1f V',max_age=5),
            Reg_u32b(55, '/Ac/Energy/Forward',        10, '%.1f kWh',max_age=5),
            Reg_u32b(53, '/Ac/L1/Energy/Forward',     10, '%.1f kWh',max_age=5),
            Reg_u16(105, '/ErrorCode',max_age=5),
            Reg_u16(93, '/Internal/InverterTemp',      10, '%.1f C',max_age=10),
            Reg_u16(94, '/Internal/IPMTemp',      10, '%.1f C',max_age=10),
            Reg_u16(95, '/Internal/BoostTemp',      10, '%.1f C',max_age=10),
            Reg_u16(104, '/Internal/DerateMode',   1, '%.1f',max_age=10),
            Reg_u16(3, '/Internal/activePowerRate',           1, '%.1f', access='holding',max_age=10),
            Reg_u16(122, '/Internal/exportLimitType',           1, '%.1f', access='holding',max_age=10),
            Reg_u16(123, '/Internal/ExportLimitPowerRate',      10, '%.1f %%', access='holding',max_age=10),
            Reg_u16(42, '/Internal/g100FailSafe', 1, '%.1f', access='holding',max_age=10),
            Reg_u16(3000, '/Internal/g100FailSafePowerRate',      10, '%.1f W', access='holding',max_age=10),

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