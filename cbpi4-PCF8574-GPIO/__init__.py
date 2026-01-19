

import asyncio
import logging

from cbpi.api import *
from cbpi.api.config import *
from cbpi.api.actor import CBPiActor

from pcf8574 import PCF8574

logger = logging.getLogger(__name__)

# =====================================================
# PCF8574 GLOBAL STATE (PCF8574 + ULN2803)
# LOW  = relé ligado
# HIGH = relé desligado
# =====================================================

PCF8574_STATE = 0xFF  # todos desligados ao iniciar

def pcf8574_write_bit(pin_name, level):
    global PCF8574_STATE

    pin = int(pin_name[1:])
    mask = 1 << pin

    if level == "LOW":
        PCF8574_STATE &= ~mask   # liga relé
    else:
        PCF8574_STATE |= mask    # desliga relé

    # PCF8574 exige escrita de todos os pinos
    for i in range(8):
        bit = (PCF8574_STATE >> i) & 0x01
        p1.write(f"p{i}", bit)

# =====================================================
# PCF8574 CONFIG
# =====================================================

@parameters([
    Property.Number(label="I2C Address", configurable=True, default_value=0x20),
    Property.Number(label="I2C Bus", configurable=True, default_value=1)
])
class PCF8574_Config(CBPiExtension):

    async def on_start(self):
        global p1
        try:
            address = int(self.props.get("I2C Address", 0x20))
            bus = int(self.props.get("I2C Bus", 1))
            p1 = PCF8574(address, bus)
            logger.info("PCF8574 iniciado no endereço I2C %s (bus %s)", hex(address), bus)
        except Exception as e:
            logger.warning(e)
        pass

# =====================================================
# PCF8574 ACTOR
# =====================================================

@parameters([
    Property.Select(label="GPIO", options=["p0","p1","p2","p3","p4","p5","p6","p7"]),
    Property.Select(label="Inverted", options=["Yes", "No"],
                    description="No: Active on high; Yes: Active on low"),
    Property.Select(label="SamplingTime", options=[2,5],
                    description="Time in seconds for power base interval (Default:5)")
])
class PCF8574Actor(CBPiActor):

    @action("Set Power", parameters=[
        Property.Number(label="Power", configurable=True,
                        description="Power Setting [0-100]")
    ])
    async def setpower(self, Power=100, **kwargs):
        self.power = max(0, min(100, int(Power)))
        await self.set_power(self.power)

    async def on_start(self):
        self.power = None
        self.inverted = True if self.props.get("Inverted", "No") == "Yes" else False

        # ULN2803 + PCF8574
        self.p1off = "LOW" if not self.inverted else "HIGH"
        self.p1on  = "HIGH" if not self.inverted else "LOW"

        self.gpio = self.props.get("GPIO", "p0")
        self.sampleTime = int(self.props.get("SamplingTime", 5))

        # garante estado inicial desligado
        pcf8574_write_bit(self.gpio, self.p1off)
        self.state = False

    async def on(self, power=None):
        self.power = power if power is not None else 100
        await self.set_power(self.power)

        logger.info("ACTOR %s ON - GPIO %s", self.id, self.gpio)
        pcf8574_write_bit(self.gpio, self.p1on)
        self.state = True

    async def off(self):
        logger.info("ACTOR %s OFF - GPIO %s", self.id, self.gpio)
        pcf8574_write_bit(self.gpio, self.p1off)
        self.state = False

    def get_state(self):
        return self.state

    async def run(self):
        while self.running:
            if self.state:
                heating_time = self.sampleTime * (self.power / 100)
                wait_time = self.sampleTime - heating_time

                if heating_time > 0:
                    pcf8574_write_bit(self.gpio, self.p1on)
                    await asyncio.sleep(heating_time)

                if wait_time > 0:
                    pcf8574_write_bit(self.gpio, self.p1off)
                    await asyncio.sleep(wait_time)
            else:
                await asyncio.sleep(1)

    async def set_power(self, power):
        self.power = power
        await self.cbpi.actor.actor_update(self.id, power)
        pass

# =====================================================
# SETUP
# =====================================================

def setup(cbpi):
    cbpi.plugin.register("PCF8574Actor", PCF8574Actor)
    cbpi.plugin.register("PCF8574_Config", PCF8574_Config)
