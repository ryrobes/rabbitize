#!/usr/bin/env python3
"""
Test script to verify the different feedback operators are working correctly.
This will send test payloads to the /feedback endpoint with different operators.
"""

import requests
import json
import time

def test_feedback_endpoint(base_url="http://localhost:3037"):
    """Test the feedback endpoint with different operators"""
    
    test_data = {
        "client_id": "test_client",
        "test_id": "test_run",
        "session_id": "test_session_" + str(int(time.time()))
    }
    
    # Test different operators
    operators = ["actor", "validator", "corrector", "summarizer", None]
    
    for operator in operators:
        payload = {
            **test_data,
            "payload": {
                "test": f"Testing operator: {operator}",
                "timestamp": time.time(),
                "message": f"This is a test message for the {operator or 'default'} operator"
            }
        }
        
        if operator:
            payload["operator"] = operator
        
        try:
            response = requests.post(f"{base_url}/feedback", json=payload)
            response.raise_for_status()
            
            operator_name = operator or "default"
            print(f"✅ Successfully tested operator '{operator_name}': {response.json()}")
            
        except Exception as e:
            print(f"❌ Failed to test operator '{operator or 'default'}': {e}")
    
    print("\nCheck the following files in your rabbitize-runs directory:")
    print(f"  - rabbitize-runs/{test_data['client_id']}/{test_data['test_id']}/{test_data['session_id']}/feedback_loop.json (default)")
    print(f"  - rabbitize-runs/{test_data['client_id']}/{test_data['test_id']}/{test_data['session_id']}/feedback_actor.json")
    print(f"  - rabbitize-runs/{test_data['client_id']}/{test_data['test_id']}/{test_data['session_id']}/feedback_validator.json")
    print(f"  - rabbitize-runs/{test_data['client_id']}/{test_data['test_id']}/{test_data['session_id']}/feedback_corrector.json")
    print(f"  - rabbitize-runs/{test_data['client_id']}/{test_data['test_id']}/{test_data['session_id']}/feedback_summarizer.json")

if __name__ == "__main__":
    test_feedback_endpoint()