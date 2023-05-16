from datetime import datetime, timedelta
import enum
import hashlib
import json
from typing import Dict, List
import uuid
from framework.serialization import Serializable


def to_fahrenheit(
    celsius: float
) -> float:
    if celsius is None or celsius == 0:
        return 0
    return round((celsius * 9/5) + 32, 1)


class NestConfiguration:
    def __init_(
        self,
        data: Dict
    ):
        self.expiration_minutes = data.get('expiration_minutes')
        self.notification_recipients = data.get('notification_recipients')
        self.contacts = data.get('contacts')
        self.created_date = data.get('created_date')


class NestThermostatMode:
    Heat = 'HEAT'
    Cool = 'COOL'
    HeatCool = 'HEATCOOL'
    Off = 'OFF'


class NestHvacStatus:
    Cooling = 'COOLING'
    Heating = 'HEATING'
    Off = 'OFF'


class NestThermostatStatus:
    Online = 'ONLINE'


class NestTemperatureUnit:
    Fahrenheit = 'FAHRENHEIT'
    Celsius = 'CELSIUS'


class NestAuthCredential(Serializable):
    def __init__(
        self,
        client_id,
        client_secret,
        refresh_token,
        created_date,
        modified_date=None
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.created_date = created_date
        self.modified_date = modified_date

    @staticmethod
    def from_entity(data):
        return NestAuthCredential(
            client_id=data.get('client_id'),
            client_secret=data.get('client_secret'),
            refresh_token=data.get('refresh_token'),
            created_date=data.get('created_date'),
            modified_date=data.get('modified_date'))


class ThermostatTrait:
    Info = 'sdm.devices.traits.Info'
    Humidity = 'sdm.devices.traits.Humidity'
    Connectivity = 'sdm.devices.traits.Connectivity'
    Fan = 'sdm.devices.traits.Fan'
    ThermostatMode = 'sdm.devices.traits.ThermostatMode'
    ThermostatEco = 'sdm.devices.traits.ThermostatEco'
    ThermostatHvac = 'sdm.devices.traits.ThermostatHvac'
    Settings = 'sdm.devices.traits.Settings'
    TemperatureSetPoint = 'sdm.devices.traits.ThermostatTemperatureSetpoint'
    Temperature = 'sdm.devices.traits.Temperature'


class NestThermostat(Serializable):
    @property
    def ambient_temperature_fahrenheit(
        self
    ):
        return to_fahrenheit(
            celsius=self.ambient_temperature_celsius)

    @property
    def heat_fahrenheit(
        self
    ):
        return to_fahrenheit(
            celsius=self.heat_celsius)

    @property
    def cool_fahrenheit(
        self
    ):
        return to_fahrenheit(
            celsius=self.cool_celsius)

    @property
    def thermostat_eco_heat_fahrenheit(
        self
    ):
        return to_fahrenheit(
            celsius=self.thermostat_eco_heat_celsius)

    @property
    def thermostat_eco_cool_fahrenheit(
        self
    ):
        return to_fahrenheit(
            celsius=self.thermostat_eco_cool_celsius)

    def __init__(
        self,
        thermostat_id: str,
        thermostat_name: str,
        humidity_percent: int,
        thermostat_status: str,
        fan_timer_mode: str,
        thermostat_mode: str,
        availabe_thermostat_modes: List[str],
        thermostat_eco_mode: str,
        available_thermostat_eco_mode: List[str],
        thermostat_eco_heat_celsius: float,
        thermostat_eco_cool_celsius: float,
        hvac_status: str,
        temperature_unit: str,
        heat_celsius: float,
        cool_celsius: float,
        ambient_temperature_celsius: float
    ):
        self.thermostat_id = thermostat_id
        self.thermostat_name = thermostat_name
        self.humidity_percent = humidity_percent
        self.thermostat_status = thermostat_status
        self.fan_timer_mode = fan_timer_mode
        self.thermostat_mode = thermostat_mode
        self.availabe_thermostat_modes = availabe_thermostat_modes
        self.thermostat_eco_mode = thermostat_eco_mode
        self.available_thermostat_eco_mode = available_thermostat_eco_mode
        self.thermostat_eco_heat_celsius = thermostat_eco_heat_celsius
        self.thermostat_eco_cool_celsius = thermostat_eco_cool_celsius
        self.hvac_status = hvac_status
        self.temperature_unit = temperature_unit
        self.heat_celsius = heat_celsius
        self.cool_celsius = cool_celsius
        self.ambient_temperature_celsius = ambient_temperature_celsius

    def __to_fahrenheit(
        self,
        celsius: float
    ) -> float:
        return (celsius * 9/5) + 32

    def to_dict(self) -> Dict:
        return super().to_dict() | {
            'thermostat_eco_cool_fahrenheit': self.thermostat_eco_cool_fahrenheit,
            'thermostat_eco_heat_fahrenheit': self.thermostat_eco_heat_fahrenheit,
            'cool_fahrenheit': self.cool_fahrenheit,
            'heat_fahrenheit': self.heat_fahrenheit,
            'ambient_temperature_fahrenheit': self.ambient_temperature_fahrenheit
        }

    @classmethod
    def get_trait(
        cls,
        data: Dict,
        trait: str,
        key: str,
        default=None
    ):
        traits = data.get('traits')

        result = traits.get(
            trait, dict()).get(
                key)

        if default is not None and result is None:
            return default

        return result

    @classmethod
    def from_json_object(
        cls,
        data: Dict,
        thermostat_id: str
    ):
        thermostat_name = cls.get_trait(
            data=data,
            trait=ThermostatTrait.Info,
            key='customName')

        humidity_percent = cls.get_trait(
            data=data,
            trait=ThermostatTrait.Humidity,
            key='ambientHumidityPercent',
            default=0)

        thermostat_status = cls.get_trait(
            data=data,
            trait=ThermostatTrait.Connectivity,
            key='status')

        fan_timer_mode = cls.get_trait(
            data=data,
            trait=ThermostatTrait.Fan,
            key='timerMode')

        thermostat_mode = cls.get_trait(
            data=data,
            trait=ThermostatTrait.ThermostatMode,
            key='mode')

        availabe_thermostat_modes = cls.get_trait(
            data=data,
            trait=ThermostatTrait.ThermostatMode,
            key='availableModes')

        thermostat_eco_mode = cls.get_trait(
            data=data,
            trait=ThermostatTrait.ThermostatEco,
            key='mode')

        available_thermostat_eco_mode = cls.get_trait(
            data=data,
            trait=ThermostatTrait.ThermostatEco,
            key='availableModes')

        thermostat_eco_heat_celsius = round(
            cls.get_trait(
                data=data,
                trait=ThermostatTrait.ThermostatEco,
                key='heatCelsius',
                default=0), 1)

        thermostat_eco_cool_celsius = round(
            cls.get_trait(
                data=data,
                trait=ThermostatTrait.ThermostatEco,
                key='coolCelsius',
                default=0), 1)

        hvac_status = cls.get_trait(
            data=data,
            trait=ThermostatTrait.ThermostatHvac,
            key='status')

        temperature_unit = cls.get_trait(
            data=data,
            trait=ThermostatTrait.Settings,
            key='temperatureScale')

        heat_celsius = round(cls.get_trait(
            data=data,
            trait=ThermostatTrait.TemperatureSetPoint,
            key='heatCelsius',
            default=0), 1)

        cool_celsius = round(cls.get_trait(
            data=data,
            trait=ThermostatTrait.TemperatureSetPoint,
            key='coolCelsius',
            default=0), 1)

        ambient_temperature_celsius = round(cls.get_trait(
            data=data,
            trait=ThermostatTrait.Temperature,
            key='ambientTemperatureCelsius',
            default=0), 2)

        return NestThermostat(
            thermostat_id=thermostat_id,
            thermostat_name=thermostat_name,
            humidity_percent=humidity_percent,
            thermostat_status=thermostat_status,
            fan_timer_mode=fan_timer_mode,
            thermostat_mode=thermostat_mode,
            availabe_thermostat_modes=availabe_thermostat_modes,
            thermostat_eco_mode=thermostat_eco_mode,
            available_thermostat_eco_mode=available_thermostat_eco_mode,
            thermostat_eco_heat_celsius=thermostat_eco_heat_celsius,
            thermostat_eco_cool_celsius=thermostat_eco_cool_celsius,
            hvac_status=hvac_status,
            temperature_unit=temperature_unit,
            heat_celsius=heat_celsius,
            cool_celsius=cool_celsius,
            ambient_temperature_celsius=ambient_temperature_celsius)


class NestSensorData(Serializable):
    def __init__(
        self,
        record_id: str,
        sensor_id: str,
        degrees_celsius: float,
        humidity_percent: float,
        timestamp: int
    ):
        self.record_id = record_id
        self.sensor_id = sensor_id
        self.degrees_celsius = round(degrees_celsius, 3)
        self.humidity_percent = round(humidity_percent, 3)
        self.timestamp = timestamp

        self.degrees_fahrenheit = to_fahrenheit(
            celsius=degrees_celsius)

        self.key = self.__generate_key()

    def __generate_key(
        self
    ):
        data = json.dumps([
            self.degrees_celsius,
            self.humidity_percent
        ])

        hashed = hashlib.md5(data.encode())
        key = uuid.UUID(hashed.hexdigest())
        return str(key)

    def get_timestamp_datetime(
        self
    ) -> datetime:

        parsed = datetime.fromtimestamp(
            self.timestamp)
        return parsed - timedelta(hours=7)

    @staticmethod
    def from_entity(data):
        return NestSensorData(
            record_id=data.get('record_id'),
            sensor_id=data.get('sensor_id'),
            degrees_celsius=data.get('degrees_celsius'),
            humidity_percent=data.get('humidity_percent'),
            timestamp=data.get('timestamp'))


class NestSensorDevice(Serializable):
    def __init__(
        self,
        device_id: str,
        device_name: str,
        created_date: int
    ):
        self.device_id = device_id
        self.device_name = device_name
        self.created_date = created_date

    @staticmethod
    def from_entity(data):
        return NestSensorDevice(
            device_id=data.get('device_id'),
            device_name=data.get('device_name'),
            created_date=data.get('created_date'))


class NestSensorDataQueryResult(Serializable):
    def __init__(
        self,
        device_id: str,
        data: List[NestSensorData]
    ):
        self.device_id = device_id
        self.data = data


class SensorDataPurgeResult(Serializable):
    def __init__(
        self,
        deleted
    ):
        self.deleted = deleted


class HealthStatus(enum.StrEnum):
    Healthy = 'healthy'
    Unhealthy = 'unhealthy'


class ThermostatMode(enum.StrEnum):
    Heat = 'HEAT'
    Cool = 'COOL'
    Range = 'HEATCOOL'
    Off = 'OFF'


class NestCommandType:
    SetRange = 'SetRange'
    SetHeat = 'SetHeat'
    SetCool = 'SetCool'
    SetPowerOff = 'SetPowerOff'
