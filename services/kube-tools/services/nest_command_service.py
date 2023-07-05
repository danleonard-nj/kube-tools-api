from typing import Dict

from framework.configuration import Configuration
from framework.logger import get_logger
from framework.serialization import Serializable

from clients.nest_client import NestClient
from domain.nest import NestCommandType, ThermostatMode
from utilities.utils import to_celsius

logger = get_logger(__name__)


NEST_COMMAND_SET_HEAT = 'sdm.devices.commands.ThermostatTemperatureSetpoint.SetHeat'
NEST_COMMAND_SET_COOL = 'sdm.devices.commands.ThermostatTemperatureSetpoint.SetCool'
NEST_COMMAND_SET_RANGE = 'sdm.devices.commands.ThermostatTemperatureSetpoint.SetRange'
NEST_COMMAND_SET_MODE = 'sdm.devices.commands.ThermostatMode.SetMode'

CommandMap = {
    NestCommandType.SetPowerOff: NEST_COMMAND_SET_MODE,
    NestCommandType.SetCool: NEST_COMMAND_SET_COOL,
    NestCommandType.SetHeat: NEST_COMMAND_SET_HEAT,
    NestCommandType.SetRange: NEST_COMMAND_SET_RANGE,
}


class NestCommandRequest(Serializable):
    def __init__(
        self,
        command: str,
        **kwargs: Dict
    ):
        self.command = command
        self.kwargs = kwargs

    def to_dict(self) -> Dict:
        return {
            'command': self.command,
            'params': self.kwargs
        }


class NestCommandService:
    def __init__(
        self,
        configuration: Configuration,
        nest_client: NestClient
    ):
        self.__thermostat_id = configuration.nest.get(
            'thermostat_id')

        self.__nest_client = nest_client

    async def __delegate_command(
        self,
        command_type,
        params
    ) -> Dict:

        match command_type:
            case NestCommandType.SetPowerOff:
                return await self.set_power_off()
            case NestCommandType.SetCool:
                return await self.set_cool(params)
            case NestCommandType.SetHeat:
                return await self.set_heat(params)
            case NestCommandType.SetRange:
                return await self.set_range(params)
            case NestCommandType.SetPowerOff:
                return await self.set_thermostat_mode(params)
            case _:
                raise Exception(f'Unknown command: {command_type}')

    async def handle_command(
        self,
        command_type: str,
        params: Dict
    ):
        _, status = await self.__delegate_command(
            command_type=command_type,
            params=params)

        return {
            'status': status
        }

    async def set_thermostat_mode(
        self,
        mode: ThermostatMode
    ):
        command = NestCommandRequest(
            command=NEST_COMMAND_SET_MODE,
            mode=mode.value
        )

        logger.info(f'Set mode: {mode}')

        return await self.__nest_client.execute_command(
            command=command.to_dict())

    async def set_heat(
        self,
        params: Dict
    ) -> Dict:

        heat_degrees_fahrenheit = params.get('heat_degrees_fahrenheit')

        if heat_degrees_fahrenheit > 85:
            raise Exception('Too hot!')

        # Set the thermostat mode to heat
        await self.set_thermostat_mode(
            mode=ThermostatMode.Heat)

        command = NestCommandRequest(
            command=CommandMap[NestCommandType.SetHeat],
            heatCelsius=to_celsius(heat_degrees_fahrenheit)
        )

        logger.info(f'Set heat: {command}')
        return await self.__nest_client.execute_command(
            command=command.to_dict())

    async def set_cool(
        self,
        params: Dict
    ) -> Dict:

        cool_degrees_fahrenheit = params.get(
            'cool_degrees_fahrenheit')

        if cool_degrees_fahrenheit < 60:
            raise Exception('Too cold!')

        # Set the thermostat mode to heat
        await self.set_thermostat_mode(
            mode=ThermostatMode.Cool)

        command = NestCommandRequest(
            command=NEST_COMMAND_SET_COOL,
            coolCelsius=to_celsius(cool_degrees_fahrenheit)
        )

        logger.info(f'Set cool: {command}')
        return await self.__nest_client.execute_command(
            command=command.to_dict())

    async def set_range(
        self,
        params: Dict
    ) -> Dict:

        heat_degrees_fahrenheit = params.get('heat_degrees_fahrenheit')
        cool_degrees_fahrenheit = params.get('cool_degrees_fahrenheit')

        if heat_degrees_fahrenheit > 85:
            raise Exception('Too hot!')

        if cool_degrees_fahrenheit < 60:
            raise Exception('Too cold!')

        # Set the thermostat mode to heat
        await self.set_thermostat_mode(
            mode=ThermostatMode.Range)

        command = NestCommandRequest(
            command=CommandMap[NestCommandType.SetRange],
            heatCelsius=to_celsius(heat_degrees_fahrenheit),
            coolCelsius=to_celsius(cool_degrees_fahrenheit)
        )

        logger.info(f'Set range: {command}')
        return await self.__nest_client.execute_command(
            command=command.to_dict())

    async def set_power_off(
        self
    ):
        return await self.set_thermostat_mode(
            mode=ThermostatMode.Off)

    async def list_commands(
        self
    ):
        return [{
            'command': command.name,
            'key': command.value
        } for command in NestCommandType]
