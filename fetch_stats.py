import os
import json
import requests
from web3 import Web3
from typing import Dict, Any, List, Optional
from datetime import datetime

# Contract addresses
XBURNMINTER_ADDRESS = "0xe89AFDeFeBDba033f6e750615f0A0f1A37C78c4A"
XEN_ADDRESS = "0x2AB0e9e4eE70FFf1fB9D67031E44F6410170d00e"  # XEN on Base

def fetch_pair_data(pair_address: str) -> Optional[Dict[str, Any]]:
    """Fetch detailed data for a specific liquidity pair"""
    try:
        print(f"Fetching DEX data for pair {pair_address}")
        dex_url = f"https://api.dexscreener.com/latest/dex/pairs/base/{pair_address}"
        response = requests.get(dex_url)
        if response.status_code == 200:
            data = response.json()
            print(f"Successfully fetched DEX data: {json.dumps(data, indent=2)}")
            return data.get('pairs', [{}])[0]
        else:
            print(f"Failed to fetch DEX data. Status code: {response.status_code}")
    except Exception as e:
        print(f"Error fetching pair data for {pair_address}:", e)
    return None

def get_pool_stats(pair_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract relevant statistics from a pool's data"""
    if not pair_data:
        return None
    
    return {
        "price_usd": pair_data.get('priceUsd'),
        "liquidity_usd": pair_data.get('liquidity', {}).get('usd'),
        "volume_24h": pair_data.get('volume', {}).get('h24'),
        "price_change_24h": pair_data.get('priceChange', {}).get('h24'),
        "txns_24h": {
            "buys": pair_data.get('txns', {}).get('h24', {}).get('buys'),
            "sells": pair_data.get('txns', {}).get('h24', {}).get('sells')
        }
    }

def main():
    print("Starting stats collection...")
    
    # Load environment variables
    rpc_url = os.environ.get("RPC_URL")
    etherscan_api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not rpc_url or not etherscan_api_key:
        print("Missing RPC_URL or ETHERSCAN_API_KEY in environment")
        return

    print("Loading ABIs...")
    # Load ABIs
    try:
        with open("XBurnMinter_abi.json", "r") as f:
            xburnminter_abi = json.load(f)
        with open("XBurnNFT_abi.json", "r") as f:
            nft_abi = json.load(f)
        print("Successfully loaded ABIs")
    except Exception as e:
        print(f"Error loading ABIs: {e}")
        return

    print("Connecting to blockchain...")
    # Connect to blockchain
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print("Error: Could not connect to RPC")
        return
    print("Successfully connected to blockchain")

    # Initialize contracts
    minter_contract = w3.eth.contract(address=Web3.to_checksum_address(XBURNMINTER_ADDRESS), abi=xburnminter_abi)
    
    print("Fetching global contract stats...")
    # Fetch global contract stats
    try:
        global_stats = minter_contract.functions.getGlobalStats().call()
        global_stats_data = {
            "currentAMP": str(global_stats[0]),
            "daysSinceLaunch": str(global_stats[1]),
            "totalBurnedXEN": str(global_stats[2]),
            "totalMintedXBURN": str(global_stats[3]),
            "ampDecayDaysLeft": str(global_stats[4])
        }
        print(f"Global stats: {json.dumps(global_stats_data, indent=2)}")
    except Exception as e:
        print("Error fetching global stats:", e)
        global_stats_data = {}

    print("Fetching accumulation progress...")
    # Fetch accumulation progress
    try:
        acc_stats = minter_contract.functions.getAccumulationProgress().call()
        accumulation_data = {
            "pendingXenForSwap": str(acc_stats[0]),
            "swapThreshold": str(acc_stats[1]),
            "progressPercentage": str(acc_stats[2])
        }
        print(f"Accumulation stats: {json.dumps(accumulation_data, indent=2)}")
    except Exception as e:
        print("Error fetching accumulation stats:", e)
        accumulation_data = {}

    print("Fetching liquidity pair info...")
    # Get liquidity pair address and validate
    try:
        liquidity_pair = minter_contract.functions.liquidityPair().call()
        pair_valid = minter_contract.functions.validatePairTokens().call()
        print(f"Liquidity pair: {liquidity_pair}, Valid: {pair_valid}")
    except Exception as e:
        print("Error fetching liquidity pair:", e)
        liquidity_pair = "0x0"
        pair_valid = False

    # Fetch DEX data for the main pair
    dex_data = None
    if liquidity_pair and liquidity_pair != "0x0000000000000000000000000000000000000000":
        print("Fetching DEX data...")
        dex_data = fetch_pair_data(liquidity_pair)

    print("Fetching NFT contract info...")
    # Get NFT contract address and stats
    try:
        nft_address = minter_contract.functions.nftContract().call()
        nft_contract = w3.eth.contract(address=Web3.to_checksum_address(nft_address), abi=nft_abi)
        total_nfts = nft_contract.functions.totalSupply().call()
        print(f"NFT contract: {nft_address}, Total NFTs: {total_nfts}")
    except Exception as e:
        print("Error fetching NFT stats:", e)
        total_nfts = 0

    print("Fetching supply stats...")
    # Fetch token supply stats from Etherscan
    supply_stats = {}
    try:
        supply_url = f"https://api.etherscan.io/api?module=stats&action=tokensupply&contractaddress={XBURNMINTER_ADDRESS}&apikey={etherscan_api_key}"
        response = requests.get(supply_url)
        if response.status_code == 200:
            supply_data = response.json()
            if supply_data.get("status") == "1":
                supply_stats["totalSupply"] = supply_data.get("result")
                
                # Get circulating supply (total - burned)
                burned = minter_contract.functions.totalXburnBurned().call()
                supply_stats["burnedSupply"] = str(burned)
                supply_stats["circulatingSupply"] = str(int(supply_data.get("result", 0)) - burned)
                print(f"Supply stats: {json.dumps(supply_stats, indent=2)}")
    except Exception as e:
        print("Error fetching supply stats:", e)

    print("Fetching holder stats...")
    # Get holder statistics
    holder_stats = {}
    try:
        holder_url = f"https://api.etherscan.io/api?module=token&action=tokenholderlist&contractaddress={XBURNMINTER_ADDRESS}&apikey={etherscan_api_key}"
        response = requests.get(holder_url)
        if response.status_code == 200:
            holder_data = response.json()
            if holder_data.get("status") == "1":
                holder_stats["uniqueHolders"] = len(holder_data.get("result", []))
                print(f"Holder stats: {json.dumps(holder_stats, indent=2)}")
    except Exception as e:
        print("Error fetching holder stats:", e)

    # Build comprehensive stats object
    stats = {
        "timestamp": datetime.now().isoformat(),
        "globalStats": global_stats_data,
        "accumulationProgress": accumulation_data,
        "liquidityPair": {
            "address": liquidity_pair,
            "isValid": pair_valid,
            "poolStats": get_pool_stats(dex_data) if dex_data else None
        },
        "nftStats": {
            "totalMinted": str(total_nfts),
            "contractAddress": nft_address if 'nft_address' in locals() else None
        },
        "supplyStats": supply_stats,
        "holderStats": holder_stats,
        "lastUpdated": w3.eth.get_block('latest').timestamp
    }

    print("\nFinal stats object:")
    print(json.dumps(stats, indent=2))

    # Save stats to file
    try:
        with open("stats.json", "w") as outfile:
            json.dump(stats, outfile, indent=4)
        print("\nStats successfully saved to stats.json")
    except Exception as e:
        print("Error saving stats:", e)

if __name__ == "__main__":
    main() 
