import asyncio
import logging
from smbus2 import SMBus

from cbpi.api import *
from cbpi.api.base import CBPiActor

logger = logging.getLogger(__name__)

# =========================
# CONFIGURAÇÃO PCF8574
# =========================
PCF8574_ADDRESS = 0x20   # ajuste se necessário (0x20–0x27)
I2C_BUS = 1              # Raspberry Pi geralmente é 1

bus = SMBus(I2C_BUS)

# Estado GLOBAL do PCF8574 (8 bits)
# Relés via ULN2803 normalmente são ATIVOS EM LOW
PCF_STATE = 0xFF  # todos desligados


# =========================
# FUNÇÕES DE BAIXO NÍVEL
# =========================
def pcf8574_write_state():
    global PCF_STATE
    bus.write_byte(PCF8574_ADDRESS, PCF_STATE)


def pcf8574_write_bit(pin, value):
    """
    pin: 'p0' até 'p7'
    value: 'HIGH' ou 'LOW'
    """
    global PCF_STATE

    bit = int(pin.replace("p", ""))

    if value == "LOW":
        PCF_STATE &= ~(1 << bit)   # liga relé
    else:
        PCF_STATE |= (1 << bit)    # desliga relé

    pcf8574_write_state()


# =========================
# ACTOR CBPI4
# =========================
@parameters([
    Property.Select(label="GPIO", options=["p0","p1","p2","p3","p4","p5","p6","p7"]),
    Property.Select(
        label="Inverted",
        options=["Yes", "No"],
        description="Yes = relé ativo em LOW (ULN2803)"
    ),
    Property.Select(
        label="SamplingTime",
        options=[2,5],
        description="Tempo base em segundos (PWM)"
    )
])
class PCF8574Actor(CBPiActor):

    @action(
        "Set Power",
        parameters=[Property.Number(label="Power", configurable=True, description="0–100 %")]
    )
    async def setpower(self, Power=100, **kwargs):
        self.power = max(0, min(100, int(Power)))
        await self.set_power(self.power)

    async def on_start(self):
        self.power = 0
        self.state = False

        self.inverted = True if self.props.get("Inverted", "Yes") == "Yes" else False
        self.p1off = "HIGH" if self.inverted else "LOW"
        self.p1on  = "LOW"  if self.inverted else "HIGH"

        self.gpio = self.props.get("GPIO", "p0")
        self.sampleTime = int(self.props.get("SamplingTime", 5))

        # garante desligado sem afetar os outros
        pcf8574_write_bit(self.gpio, self.p1off)

        logger.info(f"PCF8574Actor {self.id} iniciado em {self.gpio}")

    async def on(self, power=None):
        self.power = 100 if power is None else max(0, min(100, int(power)))
        self.state = True

        logger.info(f"ACTOR {self.id} ON - {self.gpio}")
        pcf8574_write_bit(self.gpio, self.p1on)

        await self.set_power(self.power)

    async def off(self):
        self.state = False
        self.power = 0

        logger.info(f"ACTOR {self.id} OFF - {self.gpio}")
        pcf8574_write_bit(self.gpio, self.p1off)

        await self.set_power(0)

    def get_state(self):
        return self.state

    async def run(self):
        while self.running:
            if self.state and self.power > 0:
                on_time = self.sampleTime * (self.power / 100)
                off_time = self.sampleTime - on_time

                if on_time > 0:
                    pcf8574_write_bit(self.gpio, self.p1on)
                    await asyncio.sleep(on_time)

                if off_time > 0:
                    pcf8574_write_bit(self.gpio, self.p1off)
                    await asyncio.sleep(off_time)
            else:
                await asyncio.sleep(1)

    async def set_power(self, power):
        await self.cbpi.actor.actor_update(self.id, power)


# =========================
# SETUP PLUGIN
# =========================
def setup(cbpi):
    cbpi.plugin.register("PCF8574Actor", PCF8574Actor)
