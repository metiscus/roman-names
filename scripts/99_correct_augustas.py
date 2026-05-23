import pandas as pd
import os

PARQUET_PATH = 'data/roman_names_africa_proconsularis.parquet'

def correct_dataset():
    if not os.path.exists(PARQUET_PATH):
        print("Dataset not found.")
        return

    print(f"Loading {PARQUET_PATH}...")
    df = pd.read_parquet(PARQUET_PATH)

    # 1. Fix Augusta -> Deity misclassification
    # Target "Augusta" or "Aug(ustae)" or "Aug" in imperial/female context
    augusta_pattern = r'Augusta|Aug\(ustae\)|Aug\.'
    augusta_mask = (df['raw_name'].str.contains(augusta_pattern, na=False, case=False, regex=True)) & (df['is_deity'] == True)
    
    # A safer check: if it has imperial markers or known names
    safe_augusta_mask = augusta_mask & (
        df['raw_name'].str.contains('Iulia|Domna|Faustina|Sabina|Lucilla|Crispina|Plotina|Marciana|Matidia|mater|castrorum', na=False, case=False) |
        df['status'].str.contains('mater|castrorum|Augusta', na=False, case=False)
    )

    print(f"Correcting {safe_augusta_mask.sum()} Augusta misclassifications...")
    df.loc[safe_augusta_mask, 'is_deity'] = False
    df.loc[safe_augusta_mask, 'is_imperial'] = True

    # 2. Cleanup Pertinax/Pius from cognomen field (if they are alone or with Severus)
    # This is a bit more surgical
    severus_mask = df['raw_name'].str.contains('Sever', na=False, case=False)
    for epithet in ['Pius', 'Pio', 'Pertinax', 'Pertinaci']:
        mask = severus_mask & (df['cognomen'].str.contains(epithet, na=False, case=False))
        if mask.any():
            print(f"Removing '{epithet}' from cognomen for {mask.sum()} Severus records...")
            df.loc[mask, 'cognomen'] = df.loc[mask, 'cognomen'].str.replace(epithet, '', case=False).str.strip()

    # Save back
    print(f"Saving corrected dataset to {PARQUET_PATH}...")
    df.to_parquet(PARQUET_PATH)
    print("Done.")

if __name__ == "__main__":
    correct_dataset()
