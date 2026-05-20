#!/usr/bin/env python3
"""Test enhanced agent with intelligent host matching."""

import requests
import json

def test_intelligent_matching():
    """Test intelligent host matching capabilities."""
    
    test_cases = [
        "check pve",  # Should match PVE Test
        "web status",  # Should match web-prod
        "db server",  # Should match db-server if exists
        "what OS is server PVE Test running?",  # Exact match
        "check nginx",  # Should ask for clarification if multiple matches
    ]
    
    for query in test_cases:
        print(f"\n🧠 Testing: '{query}'")
        print("=" * 60)
        
        try:
            response = requests.post(
                "http://localhost:8000/troubleshoot",
                json={"query": query},
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Success: {result['success']}")
                print(f"📝 Response preview: {result['response'][:150]}...")
                
                if 'metadata' in result:
                    metadata = result['metadata']
                    print(f"🎯 Target Host: {metadata.get('target_host', 'None')}")
                    print(f"🔍 Host Match: {metadata.get('host_match', 'none')}")
                    print(f"🔧 Iterations: {metadata.get('iterations', 'N/A')}")
                    
                    # Show tool calls for debugging
                    if 'tool_calls' in metadata:
                        print(f"🛠️  Tools used: {len(metadata['tool_calls'])}")
                        for tool_call in metadata['tool_calls'][:3]:  # Show first 3
                            print(f"   • {tool_call}")
                        if len(metadata['tool_calls']) > 3:
                            print(f"   • ... and {len(metadata['tool_calls']) - 3} more")
            else:
                print(f"❌ Error: {response.status_code}")
                print(f"📄 Response: {response.text}")
                
        except Exception as e:
            print(f"💥 Exception: {e}")

if __name__ == "__main__":
    test_intelligent_matching()
