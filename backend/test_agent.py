#!/usr/bin/env python3
"""Test script for the enhanced SSH agent."""

import requests
import json

def test_enhanced_agent():
    """Test the enhanced agent with a sample query."""
    
    # Test data
    test_queries = [
        "test connection",
        "what OS is host 'PVE Test' running?",
        "check service status on web-prod"
    ]
    
    for query in test_queries:
        print(f"\n🔍 Testing query: {query}")
        print("=" * 50)
        
        try:
            response = requests.post(
                "http://localhost:8000/troubleshoot",
                json={"query": query},
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Success: {result['success']}")
                print(f"📝 Response: {result['response'][:200]}...")
                if 'metadata' in result:
                    print(f"🔧 Metadata: {result['metadata']}")
            else:
                print(f"❌ Error: {response.status_code}")
                print(f"📄 Response: {response.text}")
                
        except Exception as e:
            print(f"💥 Exception: {e}")

if __name__ == "__main__":
    test_enhanced_agent()
