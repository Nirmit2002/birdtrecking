"""
Data preprocessing pipeline for White Stork GPS data.
Reads the Movebank Excel export and generates:
  - static/geojson/tracks.geojson    (LineString per bird)
  - static/geojson/stopovers.geojson (Point per stop-over)
  - static/geojson/stats.json        (per-bird and overall statistics)
  - static/geojson/timeline.json     (all points sorted by timestamp for animation)
"""

import os
import json
import math
import pandas as pd
import numpy as np
from datetime import datetime

from analysis import (
    calculate_bird_stats,
    detect_stopovers,
    total_distance_km,
)

# ── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE   = os.path.join(BASE_DIR, 'data', 'data.xlsx')
GEOJSON_DIR = os.path.join(BASE_DIR, 'static', 'geojson')

BIRD_COLORS = {
    'Perneta_O285': '#00BCD4',
    'Castro_O284':  '#4CAF50',
    'Mineiro_O283': '#E91E63',
}


# ── Loading & cleaning ───────────────────────────────────────────────────────

def load_and_clean(filepath=DATA_FILE):
    """
    Read the Movebank GPS Excel file, standardise column names, and
    remove rows with invalid coordinates or duplicate event IDs.
    Returns a cleaned DataFrame with consistent column names.
    """
    print(f'[Preprocess] Loading {filepath}')
    raw = pd.read_excel(filepath, engine='openpyxl')

    # Rename Movebank columns → internal names
    rename = {
        'timestamp':                    'timestamp',
        'location-lat':                 'lat',
        'location-long':                'lon',
        'individual-local-identifier':  'bird_id',
        'height-above-msl':             'altitude_m',
        'ground-speed':                 'speed_ms',     # m/s in Movebank format
        'heading':                      'heading',
        'battery-charge-percent':       'battery',
        'gps:satellite-count':          'satellites',
        'external-temperature':         'temperature',
        'event-id':                     'event_id',
    }
    df = raw.rename(columns=rename)

    # Keep only the columns we need
    keep = ['event_id', 'timestamp', 'lat', 'lon', 'bird_id',
            'altitude_m', 'speed_ms', 'heading', 'battery', 'satellites', 'temperature']
    existing = [c for c in keep if c in df.columns]
    df = df[existing].copy()

    # Drop rows without GPS fix
    df = df.dropna(subset=['lat', 'lon'])
    df = df[(df['lat'].between(-90, 90)) & (df['lon'].between(-180, 180))]

    # Parse timestamp
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=False, errors='coerce')
    df = df.dropna(subset=['timestamp'])

    # Remove duplicate event IDs (keep first)
    if 'event_id' in df.columns:
        df = df.drop_duplicates(subset='event_id', keep='first')

    # Sort by bird and time
    df = df.sort_values(['bird_id', 'timestamp']).reset_index(drop=True)

    # Fill numeric NaN with 0 (speed/altitude may have gaps)
    for col in ['altitude_m', 'speed_ms', 'heading', 'battery', 'satellites', 'temperature']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    print(f'[Preprocess] Cleaned rows: {len(df)}  Birds: {df["bird_id"].unique().tolist()}')
    return df


# ── GeoJSON builders ─────────────────────────────────────────────────────────

def build_tracks_geojson(df):
    """One LineString feature per bird."""
    features = []
    for bird_id, bdf in df.groupby('bird_id'):
        bdf = bdf.sort_values('timestamp')
        coords = bdf[['lon', 'lat']].values.tolist()
        if len(coords) < 2:
            continue
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': coords},
            'properties': {
                'bird_id': bird_id,
                'color':   BIRD_COLORS.get(bird_id, '#FFFFFF'),
                'points':  len(bdf),
            },
        })
    return {'type': 'FeatureCollection', 'features': features}


def build_stopovers_geojson(df):
    """Point features for every detected stop-over across all birds."""
    features = []
    for bird_id, bdf in df.groupby('bird_id'):
        bdf = bdf.sort_values('timestamp').reset_index(drop=True)
        stops = detect_stopovers(bdf)
        for s in stops:
            features.append({
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [s['lon'], s['lat']]},
                'properties': {
                    'bird_id':    bird_id,
                    'color':      BIRD_COLORS.get(bird_id, '#FFFFFF'),
                    'duration_h': s['duration_h'],
                    'start_time': s['start_time'],
                    'end_time':   s['end_time'],
                    'n_fixes':    s['n_fixes'],
                },
            })
    return {'type': 'FeatureCollection', 'features': features}


def build_stats_json(df):
    """Per-bird statistics plus overall summary."""
    birds = {}
    all_distances = []
    for bird_id in df['bird_id'].unique():
        stats = calculate_bird_stats(df, bird_id)
        birds[bird_id] = stats
        all_distances.append(stats.get('total_distance_km', 0))

    overall = {
        'total_points':       int(len(df)),
        'total_birds':        int(df['bird_id'].nunique()),
        'date_range_start':   df['timestamp'].min().strftime('%Y-%m-%d'),
        'date_range_end':     df['timestamp'].max().strftime('%Y-%m-%d'),
        'total_distance_km':  round(sum(all_distances), 2),
        'preprocessed_at':    datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
    }
    return {'birds': birds, 'overall': overall}


def build_timeline_json(df):
    """
    All GPS points sorted by timestamp, with Unix epoch timestamps.
    Used by the front-end animation slider.
    """
    df = df.sort_values('timestamp').reset_index(drop=True)
    points = []
    for _, row in df.iterrows():
        ts = int(row['timestamp'].timestamp())
        points.append({
            'timestamp':  ts,
            'ts_label':   row['timestamp'].strftime('%Y-%m-%d %H:%M'),
            'bird_id':    row['bird_id'],
            'lat':        round(float(row['lat']), 6),
            'lon':        round(float(row['lon']), 6),
            'altitude_m': float(row.get('altitude_m', 0)),
            'speed_kmh':  round(float(row.get('speed_ms', 0)) * 3.6, 2),
            'heading':    float(row.get('heading', 0)),
            'battery':    float(row.get('battery', 0)),
            'satellites': int(row.get('satellites', 0)),
            'temperature':float(row.get('temperature', 0)),
            'color':      BIRD_COLORS.get(row['bird_id'], '#FFFFFF'),
        })
    return points


# ── Entry point ───────────────────────────────────────────────────────────────

def run_preprocessing(force=False):
    """
    Run the full preprocessing pipeline.
    Skips if output files already exist unless *force* is True.
    """
    os.makedirs(GEOJSON_DIR, exist_ok=True)

    tracks_path    = os.path.join(GEOJSON_DIR, 'tracks.geojson')
    stopovers_path = os.path.join(GEOJSON_DIR, 'stopovers.geojson')
    stats_path     = os.path.join(GEOJSON_DIR, 'stats.json')
    timeline_path  = os.path.join(GEOJSON_DIR, 'timeline.json')

    all_exist = all(os.path.exists(p) for p in [tracks_path, stopovers_path, stats_path, timeline_path])
    if all_exist and not force:
        print('[Preprocess] Output files already exist — skipping (pass force=True to rerun).')
        return True

    try:
        df = load_and_clean()

        print('[Preprocess] Building tracks GeoJSON…')
        tracks = build_tracks_geojson(df)
        with open(tracks_path, 'w') as f:
            json.dump(tracks, f, indent=2)

        print('[Preprocess] Building stopovers GeoJSON…')
        stopovers = build_stopovers_geojson(df)
        with open(stopovers_path, 'w') as f:
            json.dump(stopovers, f, indent=2)

        print('[Preprocess] Building statistics JSON…')
        stats = build_stats_json(df)
        with open(stats_path, 'w') as f:
            json.dump(stats, f, indent=2, default=str)

        print('[Preprocess] Building timeline JSON…')
        timeline = build_timeline_json(df)
        with open(timeline_path, 'w') as f:
            json.dump(timeline, f, indent=2)

        print(f'[Preprocess] Done. {len(timeline)} points exported.')
        return True

    except Exception as e:
        print(f'[Preprocess] ERROR: {e}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    run_preprocessing(force=True)
