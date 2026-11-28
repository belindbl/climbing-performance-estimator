# Modeling Pipeline TODOs and Roadmap

This document tracks modeling issues and feature decisions identified in a review of the current pipeline. Items are recommendations, not claims that the modeling assumptions have already been validated.

## Issues to address

- [ ] **Clarify the meaning and limits of modeled power.** Estimates depend on GPX timing, elevation, and assumed rider/bike parameters; they are not power-meter readings. Keep this qualification next to outputs and explain which assumptions apply to each mode.
- [x] **Apply reference wind to the headwind calculation.** The segment GUI now projects manually supplied wind speed and direction onto each route segment when an API sample is unavailable.

## Planned modeling work

- [ ] **Review weather as a default dependency.** Weather is fetched externally and route context currently uses a midpoint sample nearest the route start time. Make weather opt-in unless the sampling method and its impact are validated; handle fetch failures without obscuring the base estimate.
- [ ] **Validate weather sampling before expanding it.** If weather adjustment remains a first-class feature, evaluate route- and time-varying samples against representative rides. Avoid presenting midpoint-derived adjustments as precise route-wide conditions.
- [x] **Accept manually supplied weather for historical performances.** GPX estimates accept reference temperature, surface pressure, and humidity when API weather is unavailable; comparison estimates accept per-track API samples or an explicitly entered shared reference sample. Wind remains a separate adjustment.
- [ ] **Define a defensible wind exposure model.** `wind_exposure_factor` is a user-set proxy, and crosswind is reported but not used by the power calculation. Either document and validate these semantics or simplify to a direct headwind scenario input.
- [x] **Fit and bound the distance-to-drag curve.** The pipeline uses separate wind-tunnel and CFD-RANS fits, reports their modeled-power span, and documents fit residuals and the RANS far-wake limitation. The range is a model comparison, not a confidence interval.
- [ ] **Validate segmented estimation against reference data.** Segment-level speeds and environmental adjustments provide more detail than the average-speed estimate, but are not necessarily more accurate. Compare both methods with representative power-meter data before treating segmented results as superior.

## Features to simplify, defer, or remove

- [x] **Align the root README with current GUI and model behavior.** Documented wheel-position factors, continuous motorcycle-gap inputs, estimated aSLP ranges, and the assumptions behind the GPX workflow.
- [x] **Remove numeric input steppers from the GUIs.** Keep number fields keyboard-editable and navigable with Tab and Shift+Tab.
- [ ] **Keep altitude-adjusted sea-level power (aSLP) secondary.** It is another inferred quantity layered on modeled power. Label it exploratory and avoid making it a headline result without validation.
- [ ] **Reduce detailed segment controls to validated scenarios.** Consider a small set of understandable presets instead of arbitrary per-segment aero multipliers and rolling-resistance overrides, unless users have a validated need for those controls.
- [ ] **Reassess GUI scope against the CLI-first workflow.** If 3D rendering, synchronized views, and live advanced metrics are primarily demonstration features, prioritize route viewing and basic segment selection and defer the rest.

## Cleanup

- [x] **Use weather inputs for air density.** Density is calculated from temperature, surface pressure, and relative humidity. Active estimate paths prefer API samples and require a reference sample when API weather is unavailable.

## Suggested order

1. ~~Add direct manual weather sample input for historical performances.~~
2. ~~Fit and validate lower and upper bounds for the drafting curve; retain interval inputs and the mean-distance fallback.~~
3. Decide whether weather adjustment and aSLP have enough validation to remain prominent features; prune disconnected helpers and defer UI/model features without a validated use case.
