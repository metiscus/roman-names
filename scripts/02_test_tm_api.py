import requests
import json
import time

def test_tm_api():
    # Load the sample IDs
    try:
        with open('temp/egypt_test_ids.json', 'r') as f:
            test_ids = json.load(f)
    except Exception as e:
        print(f"Error loading IDs: {e}")
        return

    print(f"Testing TM TexRelations API for {len(test_ids)} IDs...")
    
    results = []
    
    # The TM TexRelations API typically expects a source and an ID
    # Based on documentation, we try to find the TM ID for an EDCS ID
    # URL pattern from plan: https://www.trismegistos.org/dataservices/texrelations/
    
    for edcs_id in test_ids[:20]: # Test first 20
        # Strip 'EDCS-' prefix
        clean_id = edcs_id.replace('EDCS-', '')
        api_url = f"https://www.trismegistos.org/dataservices/texrelations/{clean_id}?source=edcs"
        
        print(f"Querying {edcs_id} ({clean_id})...")
        try:
            response = requests.get(api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Find TM_ID in the list of dicts
                tm_id = None
                if isinstance(data, list):
                    for item in data:
                        if "TM_ID" in item and item["TM_ID"]:
                            tm_id = item["TM_ID"][0]
                            break
                
                if tm_id:
                    print(f"  Success: Found TM ID {tm_id}")
                    results.append({"edcs_id": edcs_id, "tm_id": tm_id})
                else:
                    print("  No TM ID found.")
            else:
                print(f"  Failed (HTTP {response.status_code})")
        except Exception as e:
            print(f"  Error: {e}")
        
        time.sleep(1)

    if results:
        print(f"\nFound {len(results)} matches. Testing PerResponder API for the first one...")
        first_tm_id = results[0]['tm_id']
        # The PerResponder API usually lists PEOPLE. 
        # We need to see if we can get PEOPLE from a TEXT ID.
        # Actually, let's just see what the PerResponder output looks like for a TM ID.
        # Per plan: https://www.trismegistos.org/dataservices/rdf/per/?id={PER_ID}&format=json
        print(f"TM ID {first_tm_id} found. Next step is to find PER_IDs associated with this text.")
    else:
        print("\nNo matches found. This might be due to the quarry mark heavy sample.")

if __name__ == "__main__":
    test_tm_api()
