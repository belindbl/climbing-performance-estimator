from dataclasses import dataclass


@dataclass
class Rider:
    mass_kg: float = 60.0

    @staticmethod
    def default():
        return Rider()


@dataclass
class Bike:
    mass_kg: float = 8.0
    drag_coefficient: float = 1.0
    frontal_area_m2: float = 0.37
    rolling_resistance_coefficient: float = 0.004

    @staticmethod
    def default():
        return Bike()


@dataclass
class Climb:
    distance_m: float = 10000.0
    elevation_gain_m: float = 700.0
    time_s: float = 2400.0
    avg_altitude_m: float = 0.0

    @staticmethod
    def default():
        return Climb()
    
@dataclass
class Weather:
    temperature_c: float = 20.0
    pressure_hpa: float = 1013.25
    humidity_percent: float = 50.0
    wind_speed_mps: float = 0.0
    wind_direction_deg: float = 0.0

    @staticmethod
    def default():
        return Weather()
