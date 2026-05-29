import ijson
from scripts.config import EDCS_PATH

def find_mauretania():
    provinces = set()
    print(f"Reading {EDCS_PATH}...")
    with open(EDCS_PATH, 'rb') as f:
        parser = ijson.items(f, 'item.province')
        for province in parser:
            if province and 'mauretania' in province.lower():
                provinces.add(province)
    
    for p in sorted(list(provinces)):
        print(p)

if __name__ == "__main__":
    find_mauretania()
