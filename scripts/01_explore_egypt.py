import pandas as pd
import json
import os

def explore_egypt():
    input_file = 'data/EDCS_text_cleaned_2022-09-12.json'
    print(f"Loading {input_file}...")
    
    # Load the full dataset
    df = pd.read_json(input_file)
    
    # Filter for Aegyptus
    egypt_df = df[df['province'] == 'Aegyptus'].copy()
    
    print(f"\nTotal records in EDCS: {len(df)}")
    print(f"Total records in Aegyptus: {len(egypt_df)}")
    
    # Show a few sample inscriptions
    print("\nSample Inscriptions from Egypt:")
    samples = egypt_df.sample(min(10, len(egypt_df)), random_state=42)
    for i, row in samples.iterrows():
        print("-" * 40)
        print(f"EDCS-ID: {row['EDCS-ID']}")
        print(f"Publication: {row.get('publication', 'N/A')}")
        print(f"Text: {row['inscription']}")
        print(f"Interpretive: {row.get('inscription_interpretive_cleaning', 'N/A')}")

    # Export a small sample of IDs for TM API testing
    api_test_samples = egypt_df.sample(min(50, len(egypt_df)), random_state=42)
    api_test_ids = api_test_samples['EDCS-ID'].tolist()
    
    os.makedirs('temp', exist_ok=True)
    with open('temp/egypt_test_ids.json', 'w') as f:
        json.dump(api_test_ids, f)
    
    print(f"\nSaved 50 sample IDs to temp/egypt_test_ids.json for API testing.")

if __name__ == "__main__":
    explore_egypt()
