import requests
import json
import time

# A few IDs from temp/egypt_test_ids.json
TEST_IDS = [
    "EDCS-57700088", "EDCS-5770213", "EDCS-31400493", "EDCS-57700252", 
    "EDCS-57600012", "EDCS-57700281", "EDCS-67200380", "EDCS-30100054"
]

def check_tm_overlap():
    print("Checking EDCS -> TM overlap...")
    
    found_tm_ids = []
    
    for edcs_id in TEST_IDS:
        clean_id = edcs_id.replace('EDCS-', '')
        url = f"https://www.trismegistos.org/dataservices/texrelations/{clean_id}?source=edcs"
        
        try:
            print(f"Querying {edcs_id}...")
            # Use a friendly user agent
            headers = {'User-Agent': 'Gemini-NER-Research-Bot/0.1 (Contact: mbosse@example.com)'}
            r = requests.get(url, headers=headers, timeout=10)
            
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    tm_id = data[0].get('TM_ID', [None])[0]
                    if tm_id:
                        print(f"  -> Found TM ID: {tm_id}")
                        found_tm_ids.append((edcs_id, tm_id))
                    else:
                        print("  -> No TM ID in response.")
                else:
                    print("  -> No records found.")
            else:
                print(f"  -> Failed (HTTP {r.status_code})")
        except Exception as e:
            print(f"  -> Error: {e}")
        
        # Very polite delay
        time.sleep(2)

    if not found_tm_ids:
        print("\nNo TM IDs found for the sample. Egypt epigraphy might be less densely covered than papyri.")
        return

    print("\nChecking People overlap for found TM IDs...")
    # For the first found TM ID, check the people endpoint
    # Note: I need to verify the people API endpoint. 
    # Usually it's https://www.trismegistos.org/dataservices/rdf/text/?id={tm_id}&format=json
    # or similar.
    
    for edcs_id, tm_id in found_tm_ids[:2]:
        people_url = f"https://www.trismegistos.org/dataservices/rdf/text/?id={tm_id}&format=json"
        try:
            print(f"Querying people for TM {tm_id} (EDCS {edcs_id})...")
            r = requests.get(people_url, timeout=10)
            if r.status_code == 200:
                people_data = r.json()
                # Check for person references
                # The RDF JSON format is complex, but we can look for 'per' links
                people_str = json.dumps(people_data)
                per_count = people_str.count('/person/')
                print(f"  -> Found {per_count} person references in RDF.")
                if per_count > 0:
                    print(f"  -> Sample People Data Fragment: {people_str[:200]}...")
            else:
                print(f"  -> People query failed (HTTP {r.status_code})")
        except Exception as e:
            print(f"  -> Error: {e}")
        
        time.sleep(2)

if __name__ == "__main__":
    check_tm_overlap()
