import asyncio
import logging
import json
import os
from smbus2 import SMBus

from cbpi.api import *
from cbpi.api.actor import CBPiActor
from cbpi.api.config import ConfigType

logger = logging.getLogger(__name__)

I2C_BUS = 1
STATE_FILE = "/tmp/pcf8574_state.json"

bus = SMBus(I2C_BUS)
i2c_lock = asyncio.Lock()

# =========================
# ESTADO GLOBAL
# =========================
PCF_STATE = {}  # { "0x20": 0xFF, "0x21": 0xFF }


def load_state():
    global PCF_STATE
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                PCF_STATE = json.load(f)
                PCF_STATE = {k: int(v) for k, v in PCF_STATE.items()}
        except Exception as e:
            logger.warning(f"Erro ao carregar estado PCF8574: {e}")


def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(PCF_STATE, f)
    except Exception as e:
        logger.warning(f"Erro ao salvar estado PCF8574: {e}")


async def write_pcf(address):
    async with i2c_lock:
        bus.write_byte(address, PCF_STATE[f"0x{address:02X}"])
        save_state()


def ensure_address(address):
    key = f"0x{address:02X}"
    if key not in PCF_STATE:
        PCF_STATE[key] = 0xFF
        bus.write_byte(address, 0xFF)
        save_state()


async def write_bit(address, pin, value):
    key = f"0x{address:02X}"
    bit = int(pin.replace("p", ""))

    ensure_address(address)

    if value == "LOW":
        PCF_STATE[key] &= ~(1 << bit)
    else:
        PCF_STATE[key] |= (1 << bit)

    await write_pcf(address)


# =========================
# SETTINGS CBPI4
# =========================
def setup_settings(cbpi):
    cbpi.config.add(
        "pcf8574_addresses",
        ConfigType.STRING,
        "0x20",
        "Endereços I2C dos PCF8574 (ex: 0x20,0x21)"
    )


# =========================
# ACTOR
# =========================
@parameters([
    Property.Select(label="GPIO", options=[f"p{i}" for i in range(8)]),
    Property.Select(label="PCF Address", options=["0x20","0x21","0x22","0x23","0x24","0x25","0x26","0x27"]),
    Property.Select(label="Inverted", options=["Yes","No"]),
    Property.Select(label="SamplingTime", options=[2,5])
])
class PCF8574Actor(CBPiActor):

    @action("Teste Sequencial", parameters=[])
    async def test_sequence(self, **kwargs):
        for i in range(8):
            await write_bit(self.address, f"p{i}", self.p1on)
            await asyncio.sleep(0.3)
            await write_bit(self.address, f"p{i}", self.p1off)

    async def on_start(self):
        self.state = False
        self.power = 0

        self.address = int(self.props.get("PCF Address"), 16)
        self.gpio = self.props.get("GPIO")
        self.sampleTime = int(self.props.get("SamplingTime", 5))
        self.inverted = self.props.get("Inverted") == "Yes"

        self.p1on = "LOW" if self.inverted else "HIGH"
        self.p1off = "HIGH" if self.inverted else "LOW"

        ensure_address(self.address)
        await write_bit(self.address, self.gpio, self.p1off)

    async def on(self, power=None):
        self.state = True
        self.power = 100 if power is None else int(power)
        await write_bit(self.address, self.gpio, self.p1on)
        await self.set_power(self.power)

    async def off(self):
        self.state = False
        self.power = 0
        await write_bit(self.address, self.gpio, self.p1off)
        await self.set_power(0)

    def get_state(self):
        return self.state

    async def run(self):
        while self.running:
            if self.state and self.power > 0:
                on_time = self.sampleTime * (self.power / 100)
                off_time = self.sampleTime - on_time

                if on_time > 0:
                    await write_bit(self.address, self.gpio, self.p1on)
                    await asyncio.sleep(on_time)

                if off_time > 0:
                    await write_bit(self.address, self.gpio, self.p1off)
                    await asyncio.sleep(off_time)
            else:
                await asyncio.sleep(1)

    async def set_power(self, power):
        await self.cbpi.actor.actor_update(self.id, power)


# =========================
# SETUP
# =========================
def setup(cbpi):
    load_state()
    setup_settings(cbpi)
    cbpi.plugin.register("PCF8574Actor", PCF8574Actor)
