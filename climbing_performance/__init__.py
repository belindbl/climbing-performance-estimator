# climbing_performance/__init__.py

from .models import Rider, Bike, Climb
from .metrics import (
    compute_gradient,
    compute_vam,
    compute_road_speed,
    compute_vertical_speed,
    air_density_at_altitude,
    estimate_power_components,
    estimate_watts_per_kg,
    summarise_climb_performance,
)
from .aslp import (
    cp_remaining_fraction_at_altitude,
    sea_level_equivalent_power,
    altitude_power_loss_percent,
    estimate_aslp_wkg,
    summarise_aslp,
)

__all__ = [
    "Rider",
    "Bike",
    "Climb",
    "compute_gradient",
    "compute_vam",
    "compute_road_speed",
    "compute_vertical_speed",
    "air_density_at_altitude",
    "estimate_power_components",
    "estimate_watts_per_kg",
    "summarise_climb_performance",
]