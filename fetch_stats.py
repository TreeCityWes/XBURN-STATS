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
        url = f"https://api.dexscreener.com/latest/dex/tokens/{BASE_CHAIN_ID}/{token_address}"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return data.get('pairs', [])
        else:
            print(f"Failed to fetch pairs. Status code: {response.status_code}")
    except Exception as e:
        print(f"Error fetching pairs for {token_address}:", e)
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
    """Fetch historical events from the contract with retry logic"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            events = contract.events[event_name].get_logs(fromBlock=from_block, toBlock=to_block)
            return events
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"Error fetching {event_name} events after {max_retries} attempts:", e)
                return []
            time.sleep(1)  # Wait before retry

def calculate_burn_metrics(w3: Web3, minter_contract: Any) -> Dict[str, Any]:
    """Calculate detailed burn metrics and trends with time-based analysis"""
    try:
        current_block = w3.eth.block_number
        day_ago_block = current_block - 28800  # Approx blocks in 24h on Base
        week_ago_block = current_block - 201600  # Approx blocks in 7 days

        # Get burn events for different timeframes
        burns_24h = get_historical_events(w3, minter_contract, 'XENBurned', day_ago_block, current_block)
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

    try:
        # Load contract ABIs
        with open("XBurnMinter_abi.json", "r") as f:
            xburnminter_abi = json.load(f)
        with open("XBurnNFT_abi.json", "r") as f:
            nft_abi = json.load(f)
    except Exception as e:
        print(f"Error loading ABIs: {e}")
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

    # Build enhanced stats object
    stats = {
        "timestamp": datetime.now().isoformat(),
        "globalStats": global_stats_data,
        "burnMetrics": burn_metrics,
        "swapAnalytics": swap_analytics,
        "liquidityPools": liquidity_pools,
        "nftAnalytics": nft_analytics,
        "lastUpdated": w3.eth.get_block('latest').timestamp
    }

    # Save stats to file
    try:
        with open("stats.json", "w") as outfile:
            json.dump(stats, outfile, indent=4)
        print("\nEnhanced stats successfully saved to stats.json")
    except Exception as e:
        print("Error saving stats:", e)

if __name__ == "__main__":
    main() 
