import glob
import pandas as pd

f = glob.glob('data/raw/*GIS*')[0]

for s in ['Project Details - Large Gen', 'Project Details - Small Gen']:
    print('=' * 70)
    print(s)
    print('=' * 70)
    df = pd.read_excel(f, sheet_name=s, header=None, nrows=35)
    for i in range(len(df)):
        vals = [str(v) for v in df.iloc[i, :12] if str(v) != 'nan']
        if vals:
            print(i, '|', ' | '.join(vals)[:200])
    print()
