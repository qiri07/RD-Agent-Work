#!/usr/bin/env python3
"""
Convert all parquet factor results to HDF5 format.
Requires h5py or pytables (tables) to be installed.
"""
import os
import pandas as pd
from pathlib import Path

import config as cfg

BASE = cfg.RDAGENT_WORKSPACE

def convert_parquet_to_hdf5(session_dir: Path):
    """Convert result.parquet to result.h5 in a session directory."""
    pq = session_dir / 'result.parquet'
    h5 = session_dir / 'result.h5'
    
    if not pq.exists():
        return False, "No result.parquet"
    if h5.exists():
        # Already has h5, skip
        return True, "Already exists"
    
    try:
        df = pd.read_parquet(pq)
        df.to_hdf(str(h5), key='data', mode='w')
        return True, f"Converted {len(df):,} rows"
    except ImportError as e:
        return False, f"Import error: {e}"
    except Exception as e:
        return False, f"Error: {e}"

def main():
    print("Converting parquet results to HDF5...")
    success = 0
    fail = 0
    
    for session in sorted(BASE.iterdir()):
        if not session.is_dir():
            continue
        ok, msg = convert_parquet_to_hdf5(session)
        if ok:
            success += 1
        else:
            fail += 1
            print(f"  FAIL {session.name}: {msg}")
    
    print(f"\nConversion complete: {success} OK, {fail} failed")

if __name__ == '__main__':
    main()
