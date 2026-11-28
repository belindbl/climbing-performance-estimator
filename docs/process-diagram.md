# Climbing Performance Process Diagram

```mermaid
flowchart TD
    User[User] --> Main[main.py]
    User --> Notebooks[notebooks/*.ipynb]

    Main --> Models[models.py<br/>Rider, Bike, Climb]
    Main --> RouteEstimate[workflow.summarise_gpx_performance]
    RouteEstimate --> SegmentWork[workflow.summarise_segmented_route_performance]
    SegmentWork --> BasicMetrics[Gradient, VAM,<br/>road speed, vertical speed]
    SegmentWork --> Gravity[Gravity work]
    SegmentWork --> Rolling[Rolling work]
    SegmentWork --> Aero[Aerodynamic work<br/>with headwind per segment]
    SegmentWork --> Total[Total modeled power]
    SegmentWork --> Wkg[Watts per kg]

    SegmentWork --> ASLP[aslp.summarise_aslp]
    ASLP --> CPFraction[CP remaining fraction<br/>at altitude]
    CPFraction --> AltLoss[Estimated altitude power loss]
    CPFraction --> SeaLevel[Sea-level equivalent estimated power<br/>with approximate range]
    SeaLevel --> ASLPWkg[aSLP W/kg<br/>with approximate range]

    BasicMetrics --> Summary[Performance summary dict]
    Gravity --> Summary
    Rolling --> Summary
    Aero --> Summary
    Total --> Summary
    Wkg --> Summary
    CPFraction --> Summary
    AltLoss --> Summary
    AltLoss --> Summary
    SeaLevel --> Summary
    ASLPWkg --> Summary

    Summary --> Print[print_performance_summary]

    Notebooks --> GPXParse[gpx.parse_gpx]
    GPXParse --> TrackPoints[TrackPoint list]
    TrackPoints --> Segments[RouteSegment list]
    Segments --> GPXRoute[GPXRoute]
    GPXRoute --> Climbs[gpx.extract_climbs]
    GPXRoute --> TimeEstimate[gpx.assign_estimated_times]
    GPXRoute --> WeatherWindow[WeatherQueryWindow]

    WeatherWindow --> WeatherFetch[weather.fetch_hourly_weather]
    WeatherFetch --> SourceSelect{Forecast or archive?}
    SourceSelect --> OpenMeteo[Open-Meteo API]
    OpenMeteo --> Samples[WeatherSample list]
    Samples --> Nearest[nearest_weather_sample]
    Nearest --> Wind[wind_to_components]

    Tests[tests] --> ClimbSummary
    Tests --> FullSummary
    Tests --> ASLP
```

## Current Integration Shape

```mermaid
flowchart LR
    ManualInputs[Manual Rider/Bike/Climb inputs] --> MainPipeline[Main performance pipeline]
    MainPipeline --> Output[Printed performance summary]

    GPXFiles[GPX files] --> RoutePipeline[Route parsing pipeline]
    RoutePipeline --> RouteData[Route/climb/weather-window data]

    WeatherAPI[Weather API pipeline] --> WeatherData[Weather samples and wind components]

    RouteData -. planned integration .-> MainPipeline
    RouteData --> MainPipeline
    WeatherData --> MainPipeline
```
## Weather & Terrain Data

Local weather sampled hourly, 9 km IFS forecasts from ECMWF WF API via openmeteo.
