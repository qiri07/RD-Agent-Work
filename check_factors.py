import pandas as pd
import os

workspace = '/run/media/onai/MyDisk/Work/RD-Agent-Work/git_ignore_folder/RD-Agent_workspace'
sessions = sorted(os.listdir(workspace))

# Problematic sessions from summary
problematic = [
    '0e589b24e03e472b8e42b10aa0f49f0e',
    '2cb4b5273aa9433489e45414bef08f67',
    '3ef33683c244464c990cdbc62603fe40',
    '5315a043edb24782a88423bda5f67946',
    'a9358be3286b43ea84ff83c315f54547',
    'f700dcc15e24475c805a37a5266a012a',
    '1274f8dfd7b94c8c89c87cc450826cbf',
    'b4d4062434eb448bb99309452e419ad9',
    'e4a5995b1d3c48f8a34eae87de928ff1',
    'edf5da7804e54f7fa7200aea263b937f',
    '61d516c548964e01a58211c84a8a9aee',
]

# Also check for the duplicate one
dup_sessions = [
    'd789d95d712e4e64b5f9190f234b0bd1',
]

print("=== Problematic Sessions (11) ===")
for s in problematic:
    h5 = os.path.join(workspace, s, 'result.h5')
    if os.path.exists(h5):
        df = pd.read_hdf(h5, key='data')
        rows = len(df)
        stocks = df.index.get_level_values('instrument').nunique()
        cols = list(df.columns)
        print(f"{s}: {rows:,} rows, {stocks} stocks, cols={cols}")
    else:
        print(f"{s}: NO result.h5")

print("\n=== Duplicate Check Session ===")
for s in dup_sessions:
    h5 = os.path.join(workspace, s, 'result.h5')
    if os.path.exists(h5):
        df = pd.read_hdf(h5, key='data')
        rows = len(df)
        stocks = df.index.get_level_values('instrument').nunique()
        print(f"{s}: {rows:,} rows, {stocks} stocks")
    else:
        print(f"{s}: NO result.h5")

print("\n=== Full Scan: Sessions not at 8,392,254 rows ===")
target = 8392254
for s in sessions:
    h5 = os.path.join(workspace, s, 'result.h5')
    if not os.path.exists(h5):
        print(f"{s}: NO result.h5")
        continue
    try:
        df = pd.read_hdf(h5, key='data')
        rows = len(df)
        stocks = df.index.get_level_values('instrument').nunique()
        if rows != target:
            print(f"{s}: {rows:,} rows, {stocks} stocks")
    except Exception as e:
        print(f"{s}: ERROR - {e}")
