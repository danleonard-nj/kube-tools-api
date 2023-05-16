from typing import Dict, Union

from framework.logger import get_logger

from clients.nest_client import NestClient
from domain.nest import NestCommandType, NestThermostat, ThermostatMode
from framework.configuration import Configuration
from utilities.utils import to_celsius

logger = get_logger(__name__)

NEST_COMMAND_SET_HEAT = 'sdm.devices.commands.ThermostatTemperatureSetpoint.SetHeat'
NEST_COMMAND_SET_COOL = 'sdm.devices.commands.ThermostatTemperatureSetpoint.SetCool'
NEST_COMMAND_SET_RANGE = 'sdm.devices.commands.ThermostatTemperatureSetpoint.SetRange'
NEST_COMMAND_SET_MODE = 'sdm.devices.commands.ThermostatMode.SetMode'


class NestCommandService:
    def __init__(
        self,
        configuration: Configuration,
        nest_client: NestClient
    ):
        self.__thermostat_id = configuration.nest.get(
            'thermostat_id')

        self.__nest_client = nest_client

    async def handle_command(
        self,
        command_type: str,
        params: Dict
    ):
        result = dict()

        if command_type == NestCommandType.SetPowerOff:
            result = await self.set_power_off()

        elif command_type == NestCommandType.SetCool:
            degrees_fahrenheit = params.get('degrees_fahrenheit')
            result = await self.set_cool(degrees_fahrenheit)

        elif command_type == NestCommandType.SetHeat:
            degrees_fahrenheit = params.get('degrees_fahrenheit')
            result = await self.set_heat(degrees_fahrenheit)

        elif command_type == NestCommandType.SetRange:
            heat_degrees_fahrenheit = params.get('heat_degrees_fahrenheit')
            cool_degrees_fahrenheit = params.get('cool_degrees_fahrenheit')
            result = await self.set_range(
                cool_fahrenheit=cool_degrees_fahrenheit,
                heat_fahrenheit=heat_degrees_fahrenheit)

        thermostat_json = await self.__nest_client.get_thermostat()
        thermostat = NestThermostat.from_json_object(
            data=thermostat_json,
            thermostat_id=self.__thermostat_id)

        return {
            'response': result,
            'state': thermostat
        }

    async def set_thermostat_mode(
        self,
        mode: str
    ):
        command = {
            "command": NEST_COMMAND_SET_MODE,
            "params": {
                "mode": mode
            }
        }

        logger.info(f'Set mode: {mode}')

        return await self.__nest_client.execute_command(
            command=command)

    async def set_heat(
        self,
        heat_fahrenheit: Union[int, float]
    ) -> Dict:
        # Set the thermostat mode to heat
        await self.set_thermostat_mode(
            mode=ThermostatMode.Heat)

        command = {
            "command": NEST_COMMAND_SET_HEAT,
            "params": {
                "heatCelsius": to_celsius(heat_fahrenheit)
            }
        }

        logger.info(f'Set heat: {command}')
        return await self.__nest_client.execute_command(
            command=command)

    async def set_cool(
        self,
        cool_fahrenheit: Union[int, float]
    ) -> Dict:
        # Set the thermostat mode to heat
        await self.set_thermostat_mode(
            mode=ThermostatMode.Cool)

        command = {
            "command": NEST_COMMAND_SET_COOL,
            "params": {
                "coolCelsius": to_celsius(cool_fahrenheit)
            }
        }

        logger.info(f'Set cool: {command}')
        return await self.__nest_client.execute_command(
            command=command)

    async def set_range(
        self,
        cool_fahrenheit: Union[int, float],
        heat_fahrenheit: Union[int, float]
    ) -> Dict:
        # Set the thermostat mode to heat
        await self.set_thermostat_mode(
            mode=ThermostatMode.Range)

        command = {
            "command": NEST_COMMAND_SET_RANGE,
            "params": {
                "heatCelsius": to_celsius(cool_fahrenheit),
                "coolCelsius": to_celsius(heat_fahrenheit)
            }
        }

        logger.info(f'Set range: {command}')
        return await self.__nest_client.execute_command(
            command=command)

    async def set_power_off(
        self
    ):
        return await self.set_thermostat_mode(
            mode=ThermostatMode.Off)
