#!/usr/bin/env python3
"""Script to analyze the HAR file and extract API information."""
import json
import argparse
from pprint import pprint


def analyze_har_file(har_file_path):
    """Analyze the HAR file and extract API information."""
    print(f"Analyzing HAR file: {har_file_path}")
    
    with open(har_file_path, 'r', encoding='utf-8') as f:
        har_data = json.load(f)
    
    entries = har_data.get('log', {}).get('entries', [])
    print(f"Found {len(entries)} entries in the HAR file.")
    
    api_calls = []
    waste_api_calls = []
    
    # Find all API calls
    for entry in entries:
        request = entry.get('request', {})
        url = request.get('url', '')
        
        # Check for API URLs
        if 'api' in url.lower() and 'http' in url.lower():
            method = request.get('method', '')
            
            # Get request data if it's a POST request
            post_data = None
            if method == 'POST':
                post_data = request.get('postData', {}).get('text', None)
                if post_data:
                    try:
                        post_data = json.loads(post_data)
                    except json.JSONDecodeError:
                        post_data = None
            
            # Get response data
            response = entry.get('response', {})
            response_content = response.get('content', {}).get('text', None)
            if response_content:
                try:
                    response_content = json.loads(response_content)
                except (json.JSONDecodeError, TypeError):
                    response_content = None
            
            api_call = {
                'url': url,
                'method': method,
                'post_data': post_data,
                'response': response_content,
                'status': response.get('status', 0)
            }
            
            api_calls.append(api_call)
            
            # Check for waste collection API calls
            if ('waste' in url.lower() or 
                'afval' in url.lower() or 
                (post_data and isinstance(post_data, dict) and 
                 ('companyCode' in post_data or 'postCode' in post_data))):
                waste_api_calls.append(api_call)
    
    print(f"Found {len(api_calls)} API calls.")
    print(f"Found {len(waste_api_calls)} potential waste collection API calls.")
    
    # Print details of waste collection API calls
    print("\n=== Waste Collection API Calls ===")
    for i, call in enumerate(waste_api_calls):
        print(f"\n--- Call {i+1} ---")
        print(f"URL: {call['url']}")
        print(f"Method: {call['method']}")
        
        if call['post_data']:
            print("Post Data:")
            pprint(call['post_data'])
        
        if call['response']:
            print("Response (truncated):")
            response_str = str(call['response'])
            if len(response_str) > 1000:
                print(response_str[:1000] + "...")
            else:
                print(response_str)
        
        print(f"Status: {call['status']}")
    
    return waste_api_calls


def extract_api_info(waste_api_calls):
    """Extract API information from waste collection API calls."""
    api_base_url = None
    company_code = None
    
    for call in waste_api_calls:
        url = call['url']
        
        # Extract base URL
        if not api_base_url and 'api' in url.lower():
            parts = url.split('/')
            if len(parts) >= 3:  # At least "http://domain.com"
                # Find the API base URL ending with "/api/" or similar
                for i in range(len(parts) - 1, 2, -1):
                    if parts[i].lower() in ['api', 'api2', 'wasteapi', 'wasteapi2']:
                        api_base_url = '/'.join(parts[:i+1]) + '/'
                        break
        
        # Extract company code
        post_data = call['post_data']
        if post_data and isinstance(post_data, dict) and 'companyCode' in post_data:
            company_code = post_data['companyCode']
    
    return {
        'api_base_url': api_base_url,
        'company_code': company_code
    }


def main():
    """Run the analysis."""
    parser = argparse.ArgumentParser(description='Analyze HAR file for API information')
    parser.add_argument('har_file', help='Path to the HAR file')
    
    args = parser.parse_args()
    
    waste_api_calls = analyze_har_file(args.har_file)
    api_info = extract_api_info(waste_api_calls)
    
    print("\n=== Extracted API Information ===")
    print(f"API Base URL: {api_info['api_base_url']}")
    print(f"Company Code: {api_info['company_code']}")
    
    if api_info['api_base_url'] and api_info['company_code']:
        print("\nAdd the following to your standalone_test.py script:")
        print(f"API_URL = \"{api_info['api_base_url']}\"")
        print(f"COMPANY_CODE = \"{api_info['company_code']}\"")


if __name__ == "__main__":
    main() 