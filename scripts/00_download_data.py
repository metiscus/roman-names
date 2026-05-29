import requests
import os
import sys
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import EDCS_PATH, LIRE_PATH

def download_file(url, dest_path):
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    block_size = 1024 # 1 Kibibyte
    
    t = tqdm(total=total_size, unit='iB', unit_scale=True, desc=os.path.basename(dest_path))
    with open(dest_path, 'wb') as f:
        for data in response.iter_content(block_size):
            t.update(len(data))
            f.write(data)
    t.close()

def get_zenodo_files(record_id):
    api_url = f"https://zenodo.org/api/records/{record_id}"
    response = requests.get(api_url)
    data = response.json()
    return data['files']

def main():
    os.makedirs('data', exist_ok=True)
    
    # Record 1: EDCS 2022 (DOI 10.5281/zenodo.7072337)
    print("Fetching EDCS file metadata...")
    edcs_files = get_zenodo_files('7072337')
    # Usually we want the large JSON file
    for f in edcs_files:
        if f['key'].endswith('.json') or f['key'].endswith('.zip'):
            url = f['links']['self']
            dest = os.path.join('data', f['key'])
            if not os.path.exists(dest):
                print(f"Downloading {f['key']}...")
                download_file(url, dest)
            else:
                print(f"{f['key']} already exists.")

    # Record 3: EDH (Heidelberg) Prosopography
    print("\nFetching EDH prosopography...")
    edh_url = "https://edh.ub.uni-heidelberg.de/data/download/edh_data_pers.csv"
    edh_dest = "data/edh_data_pers.csv"
    if not os.path.exists(edh_dest):
        print("Downloading EDH prosopography...")
        download_file(edh_url, edh_dest)
    else:
        print("EDH prosopography already exists.")

    # Build GT files
    print("\nBuilding ground truth files...")
    os.system("python3 scripts/build_edh_gt.py")


if __name__ == "__main__":
    main()
