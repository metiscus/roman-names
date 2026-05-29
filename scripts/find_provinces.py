import json
import ijson
from scripts.config import EDCS_PATH

def list_provinces():
    provinces = set()
    with open(EDCS_PATH, 'rb') as f:
        # The file is a list of objects
        parser = ijson.items(f, 'item.province')
        for province in parser:
            provinces.add(province)
    
    for p in sorted(list(provinces)):
        if any(keyword in p.lower() for keyword in ['lusitania', 'tarraconensis', 'hispania', 'baetica']):
            print(p)

if __name__ == "__main__":
    list_provinces()
