# SCR Circular Map
Developing a circle-style transport map for the Stepford County Railway (SCR) game.

## Licence
This project is licensed under the MIT License.
You’re free to use, modify, and share it. Attribution is appreciated.

## Overview
Generates a circular-style transport map for the SCR network.
The layout prioritises connections between stations over geographical accuracy, using concentric rings to keep the structure compact.

## Why
Stepford County Railway is a Roblox game where players drive, guard, and dispatch trains in a fictional network.
After seeing circular transport visualisations (e.g. Samsung’s 2024 campaign), a family member asked whether something similar could be created for SCR.
I couldn’t find an existing Python package that handled this type of layout, so this became a small project to experiment with generating one.

## What it does
The project has two stages:

1. Extracts ordered station pairs and operator colours
2. Uses this data to generate a PNG map of the network

## What it doesn’t do
- The current version simplifies service patterns (e.g. fast vs stopping services on the same line)
- The static map is non-interactive 

## Current status
At the moment, the extraction stage works. There's a certain amount of data cleaning (e.g. deduplicating station pairs on routes) to aid the later visualisation process.

Kudos to namu.wiki for the detailed list of routes and operators. 

### Data file details
Stage 1) 1) operators: operator name, livery colour (hex value)
2) route_segments: operator, route ID, from, to, sequence ID (station pairings within route) 
3) routes_ordered: operator, route ID, station names in calling (sequence ID) order
4) station_pairs: operator, from, to 

The visualisation stage is still under development. 

## Running
Assumes project structure includes `data/` and `out/` folders.

From project root:
### Stage 1

"Python Data_Gather.py" will generate 4 JSON files in the 'data' folder

### Stage 2
Generate out/map_pill_circles5.png: 
"python main.py   --pairs ./data/station_pairs.json   --operators ./data/operators.json   --out ./out/map_pill_circles5.png   --shape circle   --edge-style arc   --lane-count 16   --lane-phase 15   --lane-window 3   --lane-capacity 1.0   --lane-span-capacity 0.9   --show-rings true"

## Notes
Small experimental project to explore layout approaches for non-geographic transport maps.
