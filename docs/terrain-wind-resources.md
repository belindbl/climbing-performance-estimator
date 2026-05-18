# Terrain and Wind Exposure Resources

These references are useful for thinking about route-level wind exposure, terrain shelter, and whether OSM/DEM data can support per-segment wind protection estimates.

## Cycling and Wind Performance

- Marqués-Bruna & Grimshaw, 2008, *Aerodynamic Effects of Road Topography and Meteorological Conditions on Time-Trialling Cycling Performance*  
  https://journals.sagepub.com/doi/abs/10.1260/174795408785100572  
  Relevant for cycling performance modeling under varying topography and meteorological conditions. Useful background, but it does not solve local terrain or OSM-based wind shelter.

## Topographic Shelter and Wind Exposure

- Ruel, Mitchell & Dornier, 2002, *A GIS Based Approach to Map Wind Exposure for Windthrow Hazard Rating*  
  https://www.researchgate.net/publication/233488395_A_GIS_Based_Approach_to_Map_Wind_Exposure_for_Windthrow_Hazard_Rating  
  Uses GIS and topographic exposure concepts to map wind exposure over terrain. Relevant as a practical precedent for route-segment exposure scoring.

- *A field-based index of topographic shelter and its application to topoclimatic variation*  
  https://www.sciencedirect.com/science/article/pii/0143622895000259  
  Relevant because shelter indices can improve wind-speed prediction in topoclimatic models.

- *Assessment of wind shelter conditions of an open water storage reservoir using wind shelter index*  
  https://www.tandfonline.com/doi/full/10.1080/10402381.2020.1836094  
  Useful for horizon-line style shelter logic: positive upwind horizon angles imply shelter, while lower or negative exposure implies less protection.

- *Topographic Exposure and its Practical Applications*  
  https://sciendo.com/article/10.2478/v10285-012-0022-3  
  Describes creating topographic exposure from DEM data and combining it with climatic wind direction/speed.

## Terrain-Wind Parameterization

- Winstral, Elder & Davis, 2002, *Spatial Snow Modeling of Wind-Redistributed Snow Using Terrain-Based Parameters*  
  https://cir.nii.ac.jp/crid/1362825894524385792  
  Snow hydrology has directly relevant terrain-shelter methods. The core idea is to characterize upwind terrain exposure/shelter directionally.

- *Simulating wind fields and snow redistribution using terrain-based parameters to model snow accumulation and melt over a semi-arid mountain catchment*  
  https://www.periodicos.capes.gov.br/index.php/acervo/buscador.html?id=W2111156909&task=detalhes  
  Relevant for using terrain-derived parameters to spatially vary wind fields.

## OSM and Geospatial Data

- Boeing, 2017, *OSMnx: A Python package to work with graph-theoretic OpenStreetMap street networks*  
  https://joss.theoj.org/papers/10.21105/joss.00215  
  Useful for retrieving and working with OSM road networks and geospatial features.

- OSMnx project page  
  https://pypi.org/project/osmnx/  
  Practical package reference for downloading and analyzing OSM networks and features.

## Urban Wind and CFD

- AIJ guidelines, 2008, *AIJ guidelines for practical applications of CFD to pedestrian wind environment around buildings*  
  https://www.sciencedirect.com/science/article/pii/S0167610508000445  
  Relevant if moving beyond heuristic exposure indices into CFD. This is likely too heavy for a first route-analysis feature, but useful for understanding validation expectations.

- *Pedestrian Wind Factor Estimation in Complex Urban Environments*  
  https://arxiv.org/abs/2110.02443  
  Useful background for urban wind estimation where CFD is expensive.

## Implementation Summary for the Cycling Estimator

The most practical first implementation is a directional exposure score per GPX interval, not CFD.

Suggested approach:

1. Split the GPX route into analysis intervals.
2. For each interval, compute rider heading and upwind direction from the weather wind direction.
3. Query upwind terrain from a DEM and nearby OSM features such as buildings, forests, tree cover, hedges, and walls.
4. Compute a directional shelter score from the upwind sector.
5. Convert the shelter score into a segment-level wind exposure factor from sheltered to exposed.
6. Use that factor to scale how much ambient wind affects each interval.

Recommended stages:

- Level 1: DEM-only directional terrain exposure for rural climbs.
- Level 2: Add OSM buildings, forests, and other mapped obstructions.
- Level 3: CFD or downscaled wind fields only if the project needs urban canyon-level accuracy.

Important caveat: OSM alone is not enough for terrain wind protection. OSM can describe surface features, but hills, valleys, ridgelines, and cuttings need DEM or DSM data.
