#!/usr/bin/env python3
"""Test script to generate sample logs."""

import requests
import json

def generate_sample_logs():
    """Generate sample SSH command logs."""
    
    sample_logs = [
        {
            "host": "PVE Test",
            "command": "cat /etc/os-release",
            "status": "success",
            "output": 'PRETTY_NAME="Ubuntu"\nNAME="Ubuntu"\nVERSION_ID="22.04"\nVERSION="22.04.3 LTS (Jammy Jellyfish)"\nVERSION_CODENAME=jammy',
            "duration": 245
        },
        {
            "host": "PVE Test", 
            "command": "systemctl status nginx",
            "status": "warning",
            "output": '● nginx.service - A high performance web server and a reverse proxy server\n   Loaded: loaded (/lib/systemd/system/nginx.service; enabled; vendor preset: enabled)\n   Active: inactive (dead) since Tue 2026-05-05 14:30:15 UTC; 31s ago',
            "duration": 189
        },
        {
            "host": "web-prod",
            "command": "df -h /",
            "status": "error",
            "output": "",
            "error": "Permission denied",
            "duration": 567
        },
        {
            "host": "PVE Test",
            "command": "ping -c 4 8.8.8.8",
            "status": "success", 
            "output": 'PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.\n64 bytes from 8.8.8.8: icmp_seq=1 ttl=64 time=12.3 ms\n64 bytes from 8.8.8.8: icmp_seq=2 ttl=64 time=11.8 ms\n64 bytes from 8.8.8.8: icmp_seq=3 ttl=64 time=12.1 ms\n64 bytes from 8.8.8.8: icmp_seq=4 ttl=64 time=11.9 ms',
            "duration": 4234
        },
        {
            "host": "db-server",
            "command": "free -h",
            "status": "success",
            "output": '               total        used        free      shared  buff/cache   available\nMem:        7.8G       2.1G       5.7G       123M       1.2G       5.4G\nSwap:       2.0G          0B       2.0G',
            "duration": 156
        }
    ]
    
    print("📝 Generating sample logs...")
    
    for log in sample_logs:
        try:
            response = requests.post(
                "http://localhost:8000/api/logs",
                json=log,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                print(f"✅ Added log: {log['host']} - {log['command'][:30]}...")
            else:
                print(f"❌ Failed to add log: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"💥 Exception: {e}")
    
    # Test getting logs
    print("\n📋 Retrieving logs...")
    try:
        response = requests.get("http://localhost:8000/api/logs")
        if response.status_code == 200:
            logs = response.json()
            print(f"✅ Retrieved {len(logs)} logs")
            
            # Test stats
            stats_response = requests.get("http://localhost:8000/api/logs/stats")
            if stats_response.status_code == 200:
                stats = stats_response.json()
                print(f"📊 Stats: {stats}")
        else:
            print(f"❌ Failed to retrieve logs: {response.status_code}")
    except Exception as e:
        print(f"💥 Exception: {e}")

if __name__ == "__main__":
    generate_sample_logs()
