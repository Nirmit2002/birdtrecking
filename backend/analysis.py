"""
Spatial and statistical analysis for White Stork GPS trajectories.
Provides per-bird metrics and stop-over detection.
"""

import math
import pandas as pd
import numpy as np
from datetime import timedelta


# ── Haversine distance ──────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2):
    """Return great-circle distance in kilometres between two WGS-84 points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi  = math.radians(lat2 - lat1)
    dlam  = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def total_distance_km(df):
    """Sum of consecutive haversine distances for a single-bird dataframe."""
    if len(df) < 2:
        return 0.0
    lats = df['lat'].values
    lons = df['lon'].values
    total = 0.0
    for i in range(1, len(lats)):
        total += haversine_km(lats[i-1], lons[i-1], lats[i], lons[i])
    return round(total, 2)


# ── Heading helpers ─────────────────────────────────────────────────────────

COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']

def degrees_to_compass(deg):
    """Convert a bearing in degrees to an 8-point compass label."""
    idx = int((deg + 22.5) / 45) % 8
    return COMPASS[idx]


def dominant_heading(headings):
    """Return the most frequent compass direction from a Series of degree values."""
    if headings.dropna().empty:
        return 'N/A'
    labels = headings.dropna().apply(degrees_to_compass)
    return labels.mode().iloc[0]


# ── Stop-over detection ─────────────────────────────────────────────────────

def detect_stopovers(df, min_duration_min=30, speed_threshold_ms=0.5):
    """
    Detect stationary periods (stop-overs) in a single-bird dataframe.

    A stop-over is a consecutive sequence of GPS fixes where ground-speed
    stays below *speed_threshold_ms* (m/s) for at least *min_duration_min*
    minutes.  Returns a list of dicts with centroid lat/lon and duration.
    """
    stopovers = []
    if len(df) < 2:
        return stopovers

    # ground-speed column is already in m/s (Movebank default)
    df = df.copy().reset_index(drop=True)
    df['is_slow'] = df['speed_ms'] <= speed_threshold_ms

    i = 0
    while i < len(df):
        if df.at[i, 'is_slow']:
            j = i
            while j < len(df) and df.at[j, 'is_slow']:
                j += 1
            segment = df.iloc[i:j]
            duration = segment['timestamp'].iloc[-1] - segment['timestamp'].iloc[0]
            if duration >= timedelta(minutes=min_duration_min):
                stopovers.append({
                    'lat':        float(segment['lat'].mean()),
                    'lon':        float(segment['lon'].mean()),
                    'duration_h': round(duration.total_seconds() / 3600, 2),
                    'start_time': segment['timestamp'].iloc[0].isoformat(),
                    'end_time':   segment['timestamp'].iloc[-1].isoformat(),
                    'n_fixes':    len(segment),
                })
            i = j
        else:
            i += 1

    return stopovers


# ── Per-bird statistics ─────────────────────────────────────────────────────

def calculate_bird_stats(df, bird_id):
    """
    Compute a comprehensive statistics dict for one bird's dataframe.
    df must be sorted by timestamp and contain columns:
        timestamp, lat, lon, speed_ms, altitude_m, heading, battery, satellites, temperature
    """
    bdf = df[df['bird_id'] == bird_id].sort_values('timestamp').reset_index(drop=True)

    if bdf.empty:
        return {}

    dist     = total_distance_km(bdf)
    duration = bdf['timestamp'].iloc[-1] - bdf['timestamp'].iloc[0]
    hours    = max(duration.total_seconds() / 3600, 0.001)
    days     = max(duration.days, 1)

    stops = detect_stopovers(bdf)

    # Speed: convert m/s → km/h for display
    speeds_kmh = bdf['speed_ms'].dropna() * 3.6

    return {
        'bird_id':          bird_id,
        'data_points':      int(len(bdf)),
        'total_distance_km': dist,
        'avg_speed_kmh':    round(float(speeds_kmh.mean()), 2) if not speeds_kmh.empty else 0.0,
        'max_speed_kmh':    round(float(speeds_kmh.max()), 2) if not speeds_kmh.empty else 0.0,
        'max_altitude_m':   int(bdf['altitude_m'].max()) if not bdf['altitude_m'].dropna().empty else 0,
        'min_altitude_m':   int(bdf['altitude_m'].min()) if not bdf['altitude_m'].dropna().empty else 0,
        'avg_altitude_m':   round(float(bdf['altitude_m'].mean()), 1) if not bdf['altitude_m'].dropna().empty else 0.0,
        'stopovers_count':  len(stops),
        'stopovers':        stops,
        'migration_days':   days,
        'migration_hours':  round(hours, 1),
        'dominant_heading': dominant_heading(bdf['heading']),
        'start_date':       bdf['timestamp'].iloc[0].strftime('%Y-%m-%d %H:%M UTC'),
        'end_date':         bdf['timestamp'].iloc[-1].strftime('%Y-%m-%d %H:%M UTC'),
        'avg_battery':      round(float(bdf['battery'].mean()), 1) if not bdf['battery'].dropna().empty else 0.0,
        'avg_satellites':   round(float(bdf['satellites'].mean()), 1) if not bdf['satellites'].dropna().empty else 0.0,
    }
