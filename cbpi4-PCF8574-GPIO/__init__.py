
# -*- coding: utf-8 -*-
import os
from aiohttp import web
import logging
from unittest.mock import MagicMock, patch
import asyncio
import random
import pcf8574_io 
from cbpi.api import *
from cbpi.api.config import ConfigType
from cbpi.api.dataclasses import Props
from cbpi.api.base import CBPiBase

# ================= PCF8574 STATE FIX =================

# estado global das 8 saídas (1 = desligado, padrão PCF8574)
PCF8574_STATE = 0xFF  # tudo desligado

def set_pcf8574_pin(pcf, pin_name, turn_on):
    """
    pcf       -> instância p1
    pin_name  -> 'p0' .. 'p7'
    turn_on   -> True = LIGAR, False = DESLIGAR
    """
    global PCF8574_STATE

    pin = int(pin_name[1:])
    mask = 1 << pin

    if turn_on:
        # LOW = ON
        PCF8574_STATE &= ~mask
    else:
        # HIGH = OFF
        PCF8574_STATE |= mask

    # escreve bit a bit para preservar compatibilidade
    for i in range(8):
        level = (PCF8574_STATE >> i) & 0x01
        pcf.write(f"p{i}", level)

# =====================================================

logger = logging.getLogger(__name__)

# creates the PCF_IO object only during startup. All sensors are using the same object
def PCFActor(address):
    global p1
    pins=["p0","p1","p2","p3","p4","p5","p6","p7"]
    logger.info("***************** Start PCF Actor on I2C address {} ************************".format(hex(address)))
    try:
        # create to object with the defined address
        p1 = pcf8574_io.PCF(address)
        # All pins are set to input at start -> set them to output and low
        for pin in pins:
            p1.pin_mode(pin,"OUTPUT")
            p1.write(pin, "LOW")

        pass
    except:
        p1 = None
        logging.info("Error. Could not activate PCF8574 on I2C address {}".format(address))
        pass


# check if PCF address parameter is included in settings. Add it to settings if it not already included.
# call PCFActor function once at startup to create the PCF Actor object
class PCF8574(CBPiExtension):

    def __init__(self,cbpi):
        self.cbpi = cbpi
        self._task = asyncio.create_task(self.init_actor())

    async def init_actor(self):
        await self.PCF8574_Address()
        logger.info("Checked PCF Address")
        PCF8574_Address = self.cbpi.config.get("PCF8574_Address", "0x20")
        address=int(PCF8574_Address,16)
        PCFActor(address)

    async def PCF8574_Address(self): 
        global PCF8574_address
        plugin = await self.cbpi.plugin.load_plugin_list("cbpi4-PCF8574-GPIO")
        self.version=plugin[0].get("Version","0.0.0")
        self.name=plugin[0].get("Name","cbpi4-PCF8574-GPIO")

        self.PCF8574_update = self.cbpi.config.get(self.name+"_update", None)


        PCF8574_Address = self.cbpi.config.get("PCF8574_Address", None)
        if PCF8574_Address is None:
            logger.info("INIT PCF8574_Address")
            try:
                await self.cbpi.config.add('PCF8574_Address', '0x20', type=ConfigType.STRING, 
                                           description='PCF8574 I2C Bus address (e.g. 0x20). Change requires reboot',
                                           source=self.name)
                PCF8574_Address = self.cbpi.config.get("PCF8574_Address", None)
            except Exception as e:
                    logger.warning('Unable to update config')
                    logger.warning(e)
        else:
            if self.PCF8574_update == None or self.PCF8574_update != self.version:
                try:
                    await self.cbpi.config.add('PCF8574_Address', PCF8574_Address, type=ConfigType.STRING, 
                                           description='PCF8574 I2C Bus address (e.g. 0x20). Change requires reboot',
                                           source=self.name)
                except Exception as e:
                    logger.warning('Unable to update config')
                    logger.warning(e)
                    
        if self.PCF8574_update == None or self.PCF8574_update != self.version:
            try:
                await self.cbpi.config.add(self.name+"_update", self.version, type=ConfigType.STRING,
                                           description="PCF8574 Plugin Version",
                                           source='hidden')
            except Exception as e:
                logger.warning('Unable to update config')
                logger.warning(e)
            pass                

@parameters([Property.Select(label="GPIO", options=["p0","p1","p2","p3","p4","p5","p6","p7"]),
             Property.Select(label="Inverted", options=["Yes", "No"],description="No: Active on high; Yes: Active on low"),
             Property.Select(label="SamplingTime", options=[2,5],description="Time in seconds for power base interval (Default:5)")])
class PCF8574Actor(CBPiActor):
    # Custom property which can be configured by the user
    @action("Set Power", parameters=[Property.Number(label="Power", configurable=True,description="Power Setting [0-100]")])
    async def setpower(self,Power = 100 ,**kwargs):
        self.power=int(Power)
        if self.power < 0:
            self.power = 0
        if self.power > 100:
            self.power = 100           
        await self.set_power(self.power)      

    async def on_start(self):
        self.power = None
        self.inverted = True if self.props.get("Inverted", "No") == "Yes" else False
        self.p1off = "LOW" if self.inverted == False else "HIGH"
        self.p1on  = "HIGH" if self.inverted == False else "LOW"
        self.gpio = self.props.get("GPIO", "p0")
        self.sampleTime = int(self.props.get("SamplingTime", 5))
        #p1.pin_mode(self.gpio,"OUTPUT")
        pcf8574_write_bit(self.gpio, self.p1off)
        self.state = False

    async def on(self, power = None):
        if power is not None:
            self.power = power
        else: 
            self.power = 100
        await self.set_power(self.power)

        logger.info("ACTOR %s ON - GPIO %s " %  (self.id, self.gpio))
        pcf8574_write_bit(self.gpio, self.p1on)
        self.state = True

    async def off(self):
        logger.info("ACTOR %s OFF - GPIO %s " % (self.id, self.gpio))
        pcf8574_write_bit(self.gpio, self.p1off)
        self.state = False

    def get_state(self):
        return self.state

    async def run(self):
        while self.running == True:
            if self.state == True:
                heating_time=self.sampleTime * (self.power / 100)
                wait_time=self.sampleTime - heating_time
                if heating_time > 0:
                    #logging.info("Heating Time: {}".format(heating_time))
                    pcf8574_write_bit(self.gpio, self.p1on)
                    await asyncio.sleep(heating_time)
                if wait_time > 0:
                    #logging.info("Wait Time: {}".format(wait_time))
                    pcf8574_write_bit(self.gpio, self.p1off)
                    await asyncio.sleep(wait_time)
            else:
                await asyncio.sleep(1)


    async def set_power(self, power):
        self.power = power
        await self.cbpi.actor.actor_update(self.id,power)
        pass

def setup(cbpi):
    cbpi.plugin.register("PCF8574Actor", PCF8574Actor)
    cbpi.plugin.register("PCF8574_Config",PCF8574)
    pass
