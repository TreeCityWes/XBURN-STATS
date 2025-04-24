import os
import json
import requests
from web3 import Web3
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import time

# Contract addresses
XBURNMINTER_ADDRESS = "0xe89AFDeFeBDba033f6e750615f0A0f1A37C78c4A"
XEN_ADDRESS = "0x2AB0e9e4eE70FFf1fB9D67031E44F6410170d00e"  # XEN on Base
XBURN_ADDRESS = "0x4c5d8A75F3762c1561889743964A7279A1667995"  # XBURN token
CBXEN_ADDRESS = "0x1Bf35dEe781F776c33e2c8A3Db0EbA8b2EB538d5"  # Adding CBXEN token address

# Base chain ID for APIs
BASE_CHAIN_ID = "base"

# Known LP pairs
KNOWN_LP_PAIRS = [
    "0x93e39bd6854D960a0C4F5b592381bB8356a2D725",  # Main pair
    "0x305C60D2fEf49FADfEe67EC530DE98f67bac861D",  # Additional pairs
    # Add more known pairs here
]

def fetch_all_pairs(token_address: str) -> List[Dict[str, Any]]:
    """Fetch all liquidity pairs for a token using DexScreener API"""
    try:
        print(f"Fetching all pairs for token {token_address}")
        # Add delay to respect rate limits
        time.sleep(1)
        
        # Use the token-pairs endpoint with the correct chain ID format
        url = f"https://api.dexscreener.com/latest/dex/tokens/base/{token_address}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if not data or 'pairs' not in data:
                print("No pairs data returned from DexScreener")
                return []
                
            pairs = data.get('pairs', [])
            if not pairs:
                print("No pairs found for token")
                return []
                
            # Filter only Base chain pairs (although they should all be Base chain already)
            base_pairs = [pair for pair in pairs if pair.get('chainId') == 'base']
            if base_pairs:
                print(f"Found {len(base_pairs)} pairs on Base chain")
                return base_pairs
            else:
                print("No Base chain pairs found in response")
                return []
        else:
            print(f"Failed to fetch pairs. Status code: {response.status_code}")
            if response.status_code == 429:  # Rate limit
                print("Rate limited, waiting longer...")
                time.sleep(5)
            return []
    except Exception as e:
        print(f"Error in fetch_all_pairs for {token_address}:", e)
        return []

def get_pool_stats(pair_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract comprehensive statistics from a pool's data"""
    if not pair_data:
        return None
    
    return {
        "dex": pair_data.get('dexId'),
        "price_usd": pair_data.get('priceUsd'),
        "price_native": pair_data.get('priceNative'),
        "liquidity": {
            "usd": pair_data.get('liquidity', {}).get('usd'),
            "base": pair_data.get('liquidity', {}).get('base'),
            "quote": pair_data.get('liquidity', {}).get('quote')
        },
        "volume": pair_data.get('volume', {}),
        "price_change": pair_data.get('priceChange', {}),
        "txns": pair_data.get('txns', {}),
        "fdv": pair_data.get('fdv'),
        "market_cap": pair_data.get('marketCap'),
        "pair_created_at": pair_data.get('pairCreatedAt'),
        "base_token": pair_data.get('baseToken', {}),
        "quote_token": pair_data.get('quoteToken', {})
    }

def get_historical_events(w3: Web3, contract: Any, event_name: str, from_block: int, to_block: int) -> List[Dict]:
    """Fetch historical events from the contract with retry logic and block range chunking"""
    max_retries = 3
    chunk_size = 9900  # Slightly under 10k to be safe
    all_events = []
    
    # Calculate number of chunks needed
    start_block = from_block
    while start_block <= to_block:
        end_block = min(start_block + chunk_size, to_block)
        
        for attempt in range(max_retries):
            try:
                # Get the event object
                event = getattr(contract.events, event_name)
                
                # Get event signature
                event_abi = next(abi for abi in contract.abi if abi.get('type') == 'event' and abi.get('name') == event_name)
                event_signature = f"{event_name}({','.join(input['type'] for input in event_abi['inputs'])})"
                event_signature_hash = w3.keccak(text=event_signature).hex()
                
                # Use the getLogs method directly with chunked range
                events = w3.eth.get_logs({
                    'address': contract.address,
                    'fromBlock': start_block,
                    'toBlock': end_block,
                    'topics': [event_signature_hash]
                })
                
                # Process the events
                for evt in events:
                    try:
                        processed = event.process_log(evt)
                        all_events.append(processed)
                    except Exception as e:
                        print(f"Error processing log for {event_name}:", e)
                        continue
                
                break  # Success, exit retry loop
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"Error fetching {event_name} events for blocks {start_block}-{end_block} after {max_retries} attempts:", e)
                time.sleep(1)  # Wait before retry
        
        start_block = end_block + 1
    
    return all_events

def calculate_burn_metrics(w3: Web3, minter_contract: Any) -> Dict[str, Any]:
    """Calculate detailed burn metrics and trends with time-based analysis"""
    try:
        current_block = w3.eth.block_number
        day_ago_block = current_block - 28800  # Approx blocks in 24h on Base
        week_ago_block = current_block - 201600  # Approx blocks in 7 days

        print(f"Fetching burn events from block {day_ago_block} to {current_block} for 24h metrics")
        burns_24h = get_historical_events(w3, minter_contract, 'XENBurned', day_ago_block, current_block)
        
        print(f"Fetching burn events from block {week_ago_block} to {current_block} for 7d metrics")
        burns_7d = get_historical_events(w3, minter_contract, 'XENBurned', week_ago_block, current_block)
        
        # Calculate metrics for different timeframes
        metrics_24h = analyze_burn_period(burns_24h)
        metrics_7d = analyze_burn_period(burns_7d)
        
        return {
            "last_24h": metrics_24h,
            "last_7d": metrics_7d,
            "total_burned": str(minter_contract.functions.totalXenBurned().call()),
            "burn_rank": str(minter_contract.functions.globalBurnRank().call())
        }
    except Exception as e:
        print("Error calculating burn metrics:", e)
        return {}

def analyze_burn_period(burn_events: List[Dict]) -> Dict[str, Any]:
    """Analyze burn events for a specific time period"""
    if not burn_events:
        return {
            "total_burns": 0,
            "total_burned": "0",
            "average_burn_size": "0",
            "unique_burners": 0,
            "largest_burn": "0",
            "smallest_burn": "0"
        }

    burn_amounts = [int(event['args']['amount']) for event in burn_events]
    unique_burners = len(set(event['args']['user'] for event in burn_events))
    
    return {
        "total_burns": len(burn_events),
        "total_burned": str(sum(burn_amounts)),
        "average_burn_size": str(sum(burn_amounts) // len(burn_events)) if burn_events else "0",
        "unique_burners": unique_burners,
        "largest_burn": str(max(burn_amounts)) if burn_amounts else "0",
        "smallest_burn": str(min(burn_amounts)) if burn_amounts else "0"
    }

def get_nft_analytics(w3: Web3, nft_contract: Any) -> Dict[str, Any]:
    """Get comprehensive NFT statistics and analytics"""
    try:
        current_block = w3.eth.block_number
        day_ago_block = current_block - 28800
        
        # Get events
        mint_events = get_historical_events(w3, nft_contract, 'BurnLockCreated', day_ago_block, current_block)
        claim_events = get_historical_events(w3, nft_contract, 'LockClaimed', day_ago_block, current_block)
        
        # Calculate detailed metrics
        total_supply = nft_contract.functions.totalSupply().call()
        
        # Analyze term days distribution
        term_days_dist = {}
        total_locked_xen = 0
        for event in mint_events:
            term_days = event['args'].get('termDays', 0)
            xen_amount = event['args'].get('xenAmount', 0)
            term_days_dist[term_days] = term_days_dist.get(term_days, 0) + 1
            total_locked_xen += int(xen_amount)
        
        return {
            "total_supply": str(total_supply),
            "mints_24h": {
                "count": len(mint_events),
                "total_xen_locked": str(total_locked_xen)
            },
            "claims_24h": len(claim_events),
            "term_days_distribution": term_days_dist,
            "average_term_days": sum(days * count for days, count in term_days_dist.items()) // len(mint_events) if mint_events else 0
        }
    except Exception as e:
        print("Error calculating NFT analytics:", e)
        return {}

def get_swap_analytics(w3: Web3, minter_contract: Any) -> Dict[str, Any]:
    """Get detailed swap analytics and efficiency metrics"""
    try:
        current_block = w3.eth.block_number
        day_ago_block = current_block - 28800
        
        # Get swap events
        swap_failed_events = get_historical_events(w3, minter_contract, 'SwapFailed', day_ago_block, current_block)
        
        # Get accumulation progress
        acc_stats = minter_contract.functions.getAccumulationProgress().call()
        current_pending = acc_stats[0]
        threshold = acc_stats[1]
        
        # Calculate efficiency metrics
        progress_percentage = (current_pending / threshold) * 100 if threshold > 0 else 0
        
        # Analyze failed swaps
        failed_swap_reasons = {}
        total_failed_xen = 0
        for event in swap_failed_events:
            reason = event['args'].get('reason', 'Unknown')
            xen_amount = int(event['args'].get('xenAmount', 0))
            failed_swap_reasons[reason] = failed_swap_reasons.get(reason, 0) + 1
            total_failed_xen += xen_amount
        
        return {
            "accumulation": {
                "current_pending_xen": str(current_pending),
                "threshold": str(threshold),
                "progress_percentage": progress_percentage
            },
            "failed_swaps_24h": {
                "count": len(swap_failed_events),
                "total_xen_failed": str(total_failed_xen),
                "reasons": failed_swap_reasons
            }
        }
    except Exception as e:
        print("Error calculating swap analytics:", e)
        return {}

# NEW FUNCTIONS FOR ENHANCED STATS

def get_token_info(w3: Web3, token_address: str, abi_file: str) -> Dict[str, Any]:
    """Get basic token information using Web3"""
    try:
        # Load token ABI
        try:
            with open(abi_file, "r") as f:
                token_abi = json.load(f)
        except FileNotFoundError:
            # If ABI file is missing, use a basic ERC20 ABI
            token_abi = [
                {"constant":True,"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"payable":False,"stateMutability":"view","type":"function"},
                {"constant":True,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"payable":False,"stateMutability":"view","type":"function"},
                {"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"payable":False,"stateMutability":"view","type":"function"},
                {"constant":True,"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"}
            ]
            print(f"ABI file {abi_file} not found, using basic ERC20 ABI")
        
        token_contract = w3.eth.contract(
            address=Web3.to_checksum_address(token_address), 
            abi=token_abi
        )
        
        # Prepare result dictionary
        result = {
            "address": token_address,
        }
        
        # Get basic token info - handle each function call separately
        # Each of these could fail if the function doesn't exist in the contract
        try:
            result["total_supply"] = str(token_contract.functions.totalSupply().call())
        except Exception as e:
            print(f"Error getting total supply: {e}")
            result["total_supply"] = "0"
            
        # Get decimals with fallback to 18 (standard for most ERC20 tokens)
        try:
            if any(f['name'] == 'decimals' for f in token_abi if f.get('type') == 'function'):
                result["decimals"] = token_contract.functions.decimals().call()
            else:
                result["decimals"] = 18
        except Exception as e:
            print(f"Error getting decimals: {e}")
            result["decimals"] = 18
            
        # Format total supply with decimals
        try:
            result["total_supply_formatted"] = str(int(result["total_supply"]) / (10 ** result["decimals"]))
        except Exception:
            result["total_supply_formatted"] = "0"
        
        # Try to get symbol
        try:
            if any(f['name'] == 'symbol' for f in token_abi if f.get('type') == 'function'):
                result["symbol"] = token_contract.functions.symbol().call()
            else:
                result["symbol"] = "UNKNOWN"
        except Exception as e:
            print(f"Error getting symbol: {e}")
            result["symbol"] = "UNKNOWN"
            
        # Try to get name
        try:
            if any(f['name'] == 'name' for f in token_abi if f.get('type') == 'function'):
                result["name"] = token_contract.functions.name().call()
            else:
                result["name"] = "Unknown Token"
        except Exception as e:
            print(f"Error getting name: {e}")
            result["name"] = "Unknown Token"
        
        # Check for owner function - common in many tokens
        try:
            if any(f['name'] == 'owner' for f in token_abi if f.get('type') == 'function'):
                result["owner"] = token_contract.functions.owner().call()
        except Exception:
            # Owner function is optional, no need to log this error
            pass
        
        return result
    except Exception as e:
        print(f"Error getting token info for {token_address}:", e)
        return {
            "address": token_address,
            "error": str(e),
            "decimals": 18,
            "total_supply": "0",
            "total_supply_formatted": "0",
            "symbol": "UNKNOWN",
            "name": "Error Loading Token"
        }

def get_holders_info(token_address: str, api_key: str) -> Dict[str, Any]:
    """Get token holders information using Basescan API"""
    try:
        print(f"Fetching holders information for token {token_address}")
        
        # If no API key is provided, return default values
        if not api_key:
            print("No Basescan API key provided, skipping holder information")
            return {"total_holders": 0, "note": "API key missing"}
        
        # Basescan API for token holder count
        url = f"https://api.basescan.org/api?module=token&action=tokenholderlist&contractaddress={token_address}&page=1&offset=1&apikey={api_key}"
        
        # Try the request with a timeout
        try:
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == '1':
                    # If we just want the count of holders
                    holder_count = int(data.get('result', [{}])[0].get('count_unique', 0))
                    
                    return {
                        "total_holders": holder_count
                    }
                else:
                    error_msg = data.get('message', 'Unknown API error')
                    print(f"API error: {error_msg}")
                    # Return graceful failure
                    return {"total_holders": 0, "error": error_msg}
            else:
                print(f"Failed to fetch holders. Status code: {response.status_code}")
                return {"total_holders": 0, "error": f"HTTP Status {response.status_code}"}
        except requests.Timeout:
            print("Request to Basescan API timed out")
            return {"total_holders": 0, "error": "API request timeout"}
        except requests.RequestException as e:
            print(f"Request to Basescan API failed: {e}")
            return {"total_holders": 0, "error": str(e)}
            
    except Exception as e:
        print(f"Error in get_holders_info for {token_address}:", e)
        return {"total_holders": 0, "error": str(e)}

def get_circulating_supply(w3: Web3, token_address: str, token_abi_file: str) -> Dict[str, Any]:
    """Calculate circulating supply by excluding known treasury/locked addresses"""
    try:
        # Load token ABI
        with open(token_abi_file, "r") as f:
            token_abi = json.load(f)
        
        token_contract = w3.eth.contract(
            address=Web3.to_checksum_address(token_address), 
            abi=token_abi
        )
        
        # Get total supply
        total_supply = token_contract.functions.totalSupply().call()
        decimals = token_contract.functions.decimals().call()
        
        # Common addresses to exclude (team wallets, treasury, locked tokens)
        # This should be customized based on the specific token
        excluded_addresses = [
            XBURNMINTER_ADDRESS,  # Minter contract often holds tokens
            # Add other known locked addresses here
        ]
        
        # Calculate excluded balance
        excluded_balance = 0
        for address in excluded_addresses:
            try:
                balance = token_contract.functions.balanceOf(Web3.to_checksum_address(address)).call()
                excluded_balance += balance
                print(f"Address {address} holds {balance / (10 ** decimals)} tokens")
            except Exception as e:
                print(f"Error getting balance for {address}:", e)
        
        # Calculate circulating supply
        circulating_supply = total_supply - excluded_balance
        
        return {
            "total_supply": str(total_supply),
            "total_supply_formatted": str(total_supply / (10 ** decimals)),
            "excluded_balance": str(excluded_balance),
            "excluded_balance_formatted": str(excluded_balance / (10 ** decimals)),
            "circulating_supply": str(circulating_supply),
            "circulating_supply_formatted": str(circulating_supply / (10 ** decimals)),
            "circulating_percentage": (circulating_supply / total_supply) * 100 if total_supply > 0 else 0
        }
    except Exception as e:
        print(f"Error calculating circulating supply for {token_address}:", e)
        return {}

def get_transfer_analytics(w3: Web3, token_address: str, token_abi_file: str) -> Dict[str, Any]:
    """Get analytics on token transfers over the past 24h and 7d"""
    try:
        # Load token ABI
        with open(token_abi_file, "r") as f:
            token_abi = json.load(f)
        
        token_contract = w3.eth.contract(
            address=Web3.to_checksum_address(token_address), 
            abi=token_abi
        )
        
        current_block = w3.eth.block_number
        day_ago_block = current_block - 28800  # Approx blocks in 24h on Base
        week_ago_block = current_block - 201600  # Approx blocks in 7 days
        
        # Get Transfer events
        transfers_24h = get_historical_events(w3, token_contract, 'Transfer', day_ago_block, current_block)
        transfers_7d = get_historical_events(w3, token_contract, 'Transfer', week_ago_block, current_block)
        
        # Analyze transfers for 24h
        unique_senders_24h = len(set(event['args']['from'] for event in transfers_24h))
        unique_receivers_24h = len(set(event['args']['to'] for event in transfers_24h))
        total_volume_24h = sum(int(event['args']['value']) for event in transfers_24h)
        
        # Analyze transfers for 7d
        unique_senders_7d = len(set(event['args']['from'] for event in transfers_7d))
        unique_receivers_7d = len(set(event['args']['to'] for event in transfers_7d))
        total_volume_7d = sum(int(event['args']['value']) for event in transfers_7d)
        
        return {
            "transfers_24h": {
                "count": len(transfers_24h),
                "unique_senders": unique_senders_24h,
                "unique_receivers": unique_receivers_24h,
                "total_volume": str(total_volume_24h)
            },
            "transfers_7d": {
                "count": len(transfers_7d),
                "unique_senders": unique_senders_7d,
                "unique_receivers": unique_receivers_7d,
                "total_volume": str(total_volume_7d)
            }
        }
    except Exception as e:
        print(f"Error calculating transfer analytics for {token_address}:", e)
        return {}

def get_cbxen_stats(w3: Web3, cbxen_address: str, cbxen_abi_file: str) -> Dict[str, Any]:
    """Get specific stats for CBXEN token"""
    try:
        # First get basic token info
        cbxen_info = get_token_info(w3, cbxen_address, cbxen_abi_file)
        
        # Load CBXEN ABI
        with open(cbxen_abi_file, "r") as f:
            cbxen_abi = json.load(f)
        
        cbxen_contract = w3.eth.contract(
            address=Web3.to_checksum_address(cbxen_address), 
            abi=cbxen_abi
        )
        
        # Get CBXEN specific metrics
        # These function calls would depend on the specific functions available in the CBXEN contract
        # Below are example function calls that might exist - adjust based on actual contract
        
        # Check if specific CBXEN functions exist before calling
        metrics = {}
        
        # Example: Check if there's a rate function
        if any(f['name'] == 'getExchangeRate' for f in cbxen_abi if f['type'] == 'function'):
            rate = cbxen_contract.functions.getExchangeRate().call()
            metrics["exchange_rate"] = str(rate)
        
        # Get holders and circulating supply
        holders_info = get_holders_info(cbxen_address, os.environ.get("ETHERSCAN_API_KEY"))
        circulating_supply = get_circulating_supply(w3, cbxen_address, cbxen_abi_file)
        transfer_analytics = get_transfer_analytics(w3, cbxen_address, cbxen_abi_file)
        
        # Combine all data
        return {
            "token_info": cbxen_info,
            "metrics": metrics,
            "holders": holders_info,
            "supply": circulating_supply,
            "transfers": transfer_analytics
        }
    except Exception as e:
        print(f"Error getting CBXEN stats: {e}")
        return {}

def main():
    print("Starting enhanced stats collection...")
    
    # Load environment variables
    rpc_url = os.environ.get("RPC_URL")
    etherscan_api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not rpc_url or not etherscan_api_key:
        print("Missing RPC_URL or ETHERSCAN_API_KEY in environment")
        return

    # Initialize web3 and contracts
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print("Error: Could not connect to RPC")
        return

    # Basic ERC20 ABI (create if missing)
    basic_erc20_abi = [
        {"constant":True,"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"payable":False,"stateMutability":"view","type":"function"},
        {"constant":True,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"payable":False,"stateMutability":"view","type":"function"},
        {"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"payable":False,"stateMutability":"view","type":"function"},
        {"constant":True,"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"},
        {"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"},
        {"anonymous":False,"inputs":[{"indexed":True,"name":"from","type":"address"},{"indexed":True,"name":"to","type":"address"},{"indexed":False,"name":"value","type":"uint256"}],"name":"Transfer","type":"event"}
    ]
    
    try:
        # Load mandatory contract ABIs
        try:
            with open("XBurnMinter_abi.json", "r") as f:
                xburnminter_abi = json.load(f)
            with open("XBurnNFT_abi.json", "r") as f:
                nft_abi = json.load(f)
        except Exception as e:
            print(f"Error loading mandatory ABIs: {e}")
            return
        
        # Load or create optional ABIs
        try:
            with open("ERC20_abi.json", "r") as f:
                erc20_abi = json.load(f)
        except FileNotFoundError:
            print("ERC20_abi.json not found, using basic ERC20 ABI")
            erc20_abi = basic_erc20_abi
            # Create the file for future use
            with open("ERC20_abi.json", "w") as f:
                json.dump(erc20_abi, f, indent=4)
        
        # For CBXEN, use ERC20 ABI if file not found
        try:
            with open("CBXEN_abi.json", "r") as f:
                cbxen_abi = json.load(f)
        except FileNotFoundError:
            print("CBXEN_abi.json not found, using ERC20 ABI as fallback")
            cbxen_abi = erc20_abi
    except Exception as e:
        print(f"Error handling ABIs: {e}")
        return

    # Initialize contracts
    minter_contract = w3.eth.contract(address=Web3.to_checksum_address(XBURNMINTER_ADDRESS), abi=xburnminter_abi)
    nft_address = minter_contract.functions.nftContract().call()
    nft_contract = w3.eth.contract(address=Web3.to_checksum_address(nft_address), abi=nft_abi)

    # Get all liquidity pairs data
    all_pairs = fetch_all_pairs(XBURN_ADDRESS)
    liquidity_pools = {pair['pairAddress']: get_pool_stats(pair) for pair in all_pairs}

    # Get enhanced analytics
    burn_metrics = calculate_burn_metrics(w3, minter_contract)
    nft_analytics = get_nft_analytics(w3, nft_contract)
    swap_analytics = get_swap_analytics(w3, minter_contract)

    # Get global stats
    global_stats = minter_contract.functions.getGlobalStats().call()
    global_stats_data = {
        "currentAMP": str(global_stats[0]),
        "daysSinceLaunch": str(global_stats[1]),
        "totalBurnedXEN": str(global_stats[2]),
        "totalMintedXBURN": str(global_stats[3]),
        "ampDecayDaysLeft": str(global_stats[4])
    }

    # NEW STATS COLLECTION
    print("Collecting token holder and supply statistics...")
    
    # Get XBURN token stats
    xburn_info = get_token_info(w3, XBURN_ADDRESS, "ERC20_abi.json")
    xburn_holders = {}
    xburn_supply = {}
    xburn_transfers = {}
    
    # Try to get additional XBURN stats but continue if they fail
    try:
        xburn_holders = get_holders_info(XBURN_ADDRESS, etherscan_api_key)
    except Exception as e:
        print(f"Failed to get XBURN holders info: {e}")
    
    try:
        xburn_supply = get_circulating_supply(w3, XBURN_ADDRESS, "ERC20_abi.json")
    except Exception as e:
        print(f"Failed to get XBURN supply info: {e}")
    
    try:
        xburn_transfers = get_transfer_analytics(w3, XBURN_ADDRESS, "ERC20_abi.json")
    except Exception as e:
        print(f"Failed to get XBURN transfer analytics: {e}")
    
    # Get CBXEN token stats - handle this gracefully if missing
    cbxen_stats = {}
    try:
        cbxen_stats = get_cbxen_stats(w3, CBXEN_ADDRESS, "CBXEN_abi.json")
    except Exception as e:
        print(f"Failed to get CBXEN stats (this is non-critical): {e}")
    
    # Get XEN token stats (for comparison) - handle gracefully
    xen_info = {}
    xen_holders = {}
    xen_supply = {}
    
    try:
        xen_info = get_token_info(w3, XEN_ADDRESS, "ERC20_abi.json")
    except Exception as e:
        print(f"Failed to get XEN token info: {e}")
    
    try:
        xen_holders = get_holders_info(XEN_ADDRESS, etherscan_api_key)
    except Exception as e:
        print(f"Failed to get XEN holders info: {e}")
    
    try:
        xen_supply = get_circulating_supply(w3, XEN_ADDRESS, "ERC20_abi.json")
    except Exception as e:
        print(f"Failed to get XEN supply info: {e}")
    
    # Build enhanced stats object
    stats = {
        "timestamp": datetime.now().isoformat(),
        "globalStats": global_stats_data,
        "burnMetrics": burn_metrics,
        "swapAnalytics": swap_analytics,
        "liquidityPools": liquidity_pools,
        "nftAnalytics": nft_analytics,
        # New stats
        "tokenStats": {
            "xburn": {
                "info": xburn_info,
                "holders": xburn_holders,
                "supply": xburn_supply,
                "transfers": xburn_transfers
            },
            "cbxen": cbxen_stats,
            "xen": {
                "info": xen_info,
                "holders": xen_holders,
                "supply": xen_supply
            }
        },
        "lastUpdated": w3.eth.get_block('latest').timestamp
    }

    # Save stats to file
    try:
        # Check if the file exists and compare with current stats
        current_stats = {}
        if os.path.exists("stats.json"):
            try:
                with open("stats.json", "r") as infile:
                    current_stats = json.load(infile)
            except json.JSONDecodeError:
                print("Existing stats.json is not valid JSON, will overwrite")
                current_stats = {}
            
        # Compare the new stats with the current stats
        # Remove timestamp and lastUpdated from comparison
        compare_stats = stats.copy()
        compare_current = current_stats.copy()
        
        if 'timestamp' in compare_stats:
            del compare_stats['timestamp']
        if 'lastUpdated' in compare_stats:
            del compare_stats['lastUpdated']
            
        if 'timestamp' in compare_current:
            del compare_current['timestamp']
        if 'lastUpdated' in compare_current:
            del compare_current['lastUpdated']
        
        # Compare the stats
        if compare_current and compare_stats == compare_current:
            print("\nNo changes detected in stats. File remains unchanged.")
            return
        
        # If we get here, there are changes, so save the file
        with open("stats.json", "w") as outfile:
            json.dump(stats, outfile, indent=4)
        print("\nEnhanced stats successfully saved to stats.json")
    except Exception as e:
        print("Error saving stats:", e)

if __name__ == "__main__":
    main()
