[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/greydi92/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/greydi92/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

# GTA VI launch-day Twitch viewers, hour by hour

Built for the [make.fun "Forecast GTA VI's launch-day Twitch viewers hour by hour" bounty](https://make.fun/bounty/gta6-twitch-ccu-forecast-01).

One hour into GTA VI's release day (2026-11-19 UTC), this program forecasts how many people will be watching the game live on Twitch in each of the other 23 hours, as five quantiles (5%, 25%, 50%, 75%, 95%) per hour. It reads one case file (`/input/<id>.in`) and writes `/output/<id>.out`. Python 3.13, standard library only, deterministic, no network.

## How it works

The unlock rolls at local midnight — New Zealand first, then Europe, then the US — so the day ramps: an overnight dip after hour 1, then a climb to an evening-UTC peak as the US unlocks. The forecast models the log-ratio of each hour to hour 1's print, using the 42 past big launches shipped in the case as comparables:

- For each hour, a kernel-weighted mean of the comparables' own log-ratios, weighted by similarity to the case on three things: the size of hour 1's print (big launches stay near it, small ones ramp many-fold), and the pre-midnight hype excess at 23:00 and 22:00 the day before (a category whose countdown audience dwarfs its hour-1 print is still waiting for its real audience, so it grows much more). A small flat prior over all launches keeps the forecast honest when the case sits far from every comparable.
- Quantiles come from a normal in log space around that mean, with the spread set by how much similar launches disagree at that hour — wide where launches disagree, narrow where they agree.

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

## Local practice results

Scored locally on the four practice launches (Wolverine, Red Dead Redemption 2, God of War Ragnarök, Spider-Man 2) against SullyGnome's published hourly averages — the same source the kit's cases come from:

| case | loss | typical miss | 90% coverage |
|---|---|---|---|
| p00 Marvel's Wolverine | 0.185 | 34.0% | 0.913 |
| p01 Red Dead Redemption 2 | 0.142 | 24.9% | 0.957 |
| p02 God of War Ragnarök | 0.120 | 19.0% | 1.000 |
| p03 Marvel's Spider-Man 2 | 0.187 | 31.0% | 0.783 |
| **mean** | **0.159** | **27.1%** | **0.913** |

House baseline on the same practice: loss 0.387, typical miss 82.7%, 90% coverage 0.783. Runtime is about 0.06 s per case; two runs on the same case write byte-identical output.
