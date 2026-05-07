# Climbing Performance Estimator

A Python project for estimating cycling climbing performance from route, rider,
bike, weather, and segment-context inputs.

The project models a climb as a set of physical contributors: gravity, rolling
resistance, aerodynamic drag, drivetrain losses, wind exposure, and altitude
effects. It can run from a GPX route, expose calculations through a FastAPI
interface, and produce repeatable summary metrics for comparing scenarios.

## Project Goals

- Estimate the power required to complete a cycling climb.
- Break total power into gravity, rolling, aerodynamic, and drivetrain
  components.
- Parse GPX route data and derive distance, ascent, heading, duration, and
  elevation profile information.
- Incorporate weather data, including temperature and wind direction, when
  available.
- Support route segment adjustments such as drafting, protected sections, or
  solo riding.
- Report altitude-adjusted sea-level-equivalent performance metrics.
- Keep the modelling pipeline testable and modular enough to compare different
  assumptions.

## Current Capabilities

- GPX parsing for route profiles and climb-level summaries.
- Physics-based performance estimates for rider and bike inputs.
- Wind decomposition into headwind and crosswind components based on route
  heading.
- Optional weather lookup with local caching.
- Manual weather overrides for scenario testing.
- Segment-level aerodynamic and rolling-resistance adjustments.
- Altitude-adjusted power and W/kg estimates.
- CLI-style execution through `main.py`.
- FastAPI endpoints for route parsing and performance summaries.
- Regression tests for metrics, GPX workflow, weather caching, ASLP, and API
  payloads.

## Example Metrics

The summary output includes:

- gradient percentage
- VAM
- road speed and vertical speed
- gravity power
- rolling-resistance power
- aerodynamic power
- total estimated wheel power
- crank power after drivetrain adjustment
- W/kg and crank W/kg
- sea-level-equivalent power
- altitude power-loss estimate
- weather sample details when weather is enabled
- segment-level aerodynamic contribution when segment adjustments are used

## Repository Structure

```text
climbing_performance/
  api.py              FastAPI app and request/response payload helpers
  aslp.py             altitude-adjusted sea-level power calculations
  gpx.py              GPX route parsing and route geometry utilities
  metrics.py          core climbing and power metrics
  models.py           rider, bike, climb, and weather data models
  weather.py          weather API integration and wind calculations
  weather_cache.py    local weather-response cache
  workflow.py         higher-level GPX-to-performance orchestration

data/
  la_redoute.gpx      sample route used for development and tests

docs/
  process-diagram.md  high-level pipeline diagram

tests/
  test_*.py           unit and integration coverage

tools/
  segment_gui.html    local browser UI for segment experimentation
  open_segment_gui.py helper for opening the UI
```

## Running Locally

Requires Python 3.12 or newer.

Install the package in editable mode:

```bash
python -m pip install -e .
```

Run the test suite:

```bash
python -m pytest
```

Run the default GPX example:

```bash
python main.py
```

Run with explicit route and rider inputs:

```bash
python main.py data/la_redoute.gpx --rider-mass-kg 66 --bike-mass-kg 8
```

Skip weather lookup and use still-air conditions:

```bash
python main.py data/la_redoute.gpx --no-weather
```

Start the FastAPI app:

```bash
uvicorn climbing_performance.api:app --reload
```

The API serves route and performance endpoints under `/api/...`.

## API Overview

The app exposes three main routes:

- `GET /api/routes/la-redoute`
  Returns the bundled sample route profile and metadata.

- `POST /api/routes/parse`
  Accepts GPX text and returns parsed route profile data.

- `POST /api/performance`
  Accepts GPX text plus rider, bike, weather, drivetrain, and segment inputs,
  then returns a route payload, performance summary, and segment breakdown.

Example performance request shape:

```json
{
  "rider": {
    "mass_kg": 66
  },
  "bike": {
    "mass_kg": 8,
    "cda_m2": 0.37,
    "rolling_resistance_coefficient": 0.004
  },
  "include_weather": false,
  "drivetrain_efficiency": 0.975,
  "segments": [
    {
      "name": "protected",
      "type": "drafting",
      "start_distance_m": 0,
      "end_distance_m": 1200
    }
  ]
}
```

## Design Notes

The project is intentionally split into small modules:

- Data models stay lightweight and explicit.
- Core metrics are pure functions where practical.
- GPX parsing is separate from performance modelling.
- Weather lookup is isolated behind cacheable helper functions.
- The workflow layer composes route, weather, segment, and performance logic.
- The API layer translates request payloads into domain inputs and returns
  serializable summaries.

This structure makes it easier to publish selected modules, notebooks, diagrams,
or screenshots while keeping sensitive modelling assumptions or unfinished
research work private.

## Public Presentation Scope

If only part of the project should be shown on GitHub, the safest public slice is:

- this README
- high-level diagrams from `docs/`
- selected tests that demonstrate expected behaviour
- examples of CLI or API usage
- screenshots or exported charts from notebooks
- a small sample GPX file with no private activity history
- interface definitions and payload examples

Consider keeping the following private if they represent the core solution:

- full source implementation of the performance model
- detailed calibration assumptions
- proprietary coefficients or validation datasets
- exploratory notebooks with unreleased analysis
- cached weather data
- private GPX files or activities
- any `.env` file or API credentials

## Status

This is an active pet project. The current codebase is suitable for local
experimentation, tests, and demonstration of the modelling approach. Before a
public release, review the sample data, notebooks, and implementation details to
decide which parts should remain private.
