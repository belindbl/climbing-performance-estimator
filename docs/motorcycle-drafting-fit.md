# Motorcycle drafting curve fit

The motorcycle gap model uses the wind-tunnel and CFD-RANS series in Figure 9 of Blocken et al. (2020), with the wind-tunnel curve as the point estimate and the RANS curve as a higher-benefit scenario. The paper PDF is [included here](s12283-020-00332-z.pdf); the [published article](https://doi.org/10.1007/s12283-020-00332-z) is open access.

## Source points

The wind-tunnel values below are the drag reductions tabulated in Table 1. The CFD-RANS series was digitized to the nearest percentage point from Figure 9a. Drag reduction is relative to an isolated cyclist.

| Gap (m) | Wind tunnel (%) | CFD-RANS, digitized (%) |
|---:|---:|---:|
| 0.12 | 76 | 76 |
| 0.24 | 75 | 74 |
| 0.48 | 71 | 70 |
| 1.32 | 61 | 60 |
| 2.64 | 48 | 49 |
| 4.8 | 36 | 39 |
| 10 | 23 | 32 |
| 15 | 18 | 27 |
| 20 | 15 | 23 |
| 30 | 12 | 21 |
| 40 | 10 | 19 |
| 50 | 7 | 16 |

## Fit and validation

Each series was fitted independently by least squares in drag-reduction space using

```text
reduction(d) = A / (d + B)^p
aero_multiplier(d) = 1 - reduction(d)
```

The wind-tunnel fit uses `A=2.1745437926`, `B=3.2660664407`, `p=0.8507335111`. Its RMSE over the 12 tabulated distances is 0.81 percentage points; maximum absolute residual is 1.48 points.

The CFD-RANS fit uses `A=0.8800914837`, `B=1.2627075666`, `p=0.4260714646`. Its RMSE over the digitized points is 0.85 percentage points; maximum absolute residual is 1.84 points. Since the graph is digitized and the values are rounded, those RANS diagnostics are approximate.

The returned coefficient range is sorted at each distance so the first value is always the lower aero multiplier. For example, the fitted ranges are 0.507–0.520 at 2.64 m, 0.686–0.759 at 10 m, 0.797–0.890 at 30 m, and 0.836–0.926 at 50 m. The point estimate uses the wind-tunnel curve.

## Limits

This span is a comparison between two fitted data series, not a statistical confidence interval or a validated prediction interval for an individual race. The authors report that RANS agrees with wind-tunnel measurements only through about 4.8 m and overpredicts the far-wake effect at longer distances; they use scale-resolving SAS CFD there, which tracks the wind-tunnel results much more closely. Consequently the lower coefficient curve is deliberately an optimistic scenario, especially beyond 4.8 m. The model assumes the study's in-line geometry and calm, zero-crosswind conditions. The fit is interpolative over the measured 0.12–50 m range; outputs beyond that range are extrapolations.

Per-interval gaps remain supported. If only a mean gap is known, the GUI accepts a mean-gap fallback, and `whole_segment_motorcycle_draft_adjustment` remains available in the Python workflow.
