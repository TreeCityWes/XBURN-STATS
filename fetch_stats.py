import os
import json
import requests
from web3 import Web3


def main():
    # Load environment variables for RPC and Etherscan API key
    rpc_url = os.environ.get("RPC_URL")
    etherscan_api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not rpc_url or not etherscan_api_key:
        print("Missing RPC_URL or ETHERSCAN_API_KEY in environment")
        return

    # Load XBURNMINTER ABI from file
    abis_path = os.path.join(os.path.dirname(__file__), "XBurnMinter_abi.json")
    try:
        with open(abis_path, "r") as f:
            xburnminter_abi = json.load(f)
    except Exception as e:
        print(f"Error loading ABI: {e}")
        return

    # Define contract addresses
    XBURNMINTER_ADDRESS = "0xe89AFDeFeBDba033f6e750615f0A0f1A37C78c4A"
    XBURN_TOKEN_ADDRESS = "0xe89AFDeFeBDba033f6e750615f0A0f1A37C78c4A"  # Using same address as XBURNMINTER

    # Connect to the blockchain RPC
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.isConnected():
        print("Error: Could not connect to RPC")
        return

    contract = w3.eth.contract(address=Web3.toChecksumAddress(XBURNMINTER_ADDRESS), abi=xburnminter_abi)

    # Fetch global stats from contract
    try:
        global_stats = contract.functions.getGlobalStats().call()
        # getGlobalStats returns: (currentAMP, daysSinceLaunch, totalBurnedXEN, totalMintedXBURN, ampDecayDaysLeft)
        global_stats_data = {
            "currentAMP": str(global_stats[0]),
            "daysSinceLaunch": str(global_stats[1]),
            "totalBurnedXEN": str(global_stats[2]),
            "totalMintedXBURN": str(global_stats[3]),
            "ampDecayDaysLeft": str(global_stats[4])
        }
    except Exception as e:
        print("Error fetching global stats:", e)
        global_stats_data = {}

    # Fetch liquidityPair from the contract
    try:
        liquidity_pair = contract.functions.liquidityPair().call()
    except Exception as e:
        print("Error fetching liquidityPair:", e)
        liquidity_pair = "0x0"

    # Fetch Dexscreener data if liquidity pair is valid
    dexscreener_data = None
    if liquidity_pair and liquidity_pair != "0x0000000000000000000000000000000000000000":
        try:
            dex_url = f"https://api.dexscreener.com/latest/dex/pairs/base/{liquidity_pair}"
            response = requests.get(dex_url)
            if response.status_code == 200:
                dexscreener_data = response.json()
            else:
                print("Dexscreener API returned HTTP", response.status_code)
        except Exception as e:
            print("Error fetching Dexscreener data:", e)

    # Fetch token supply from Etherscan
    token_supply = None
    try:
        etherscan_url = f"https://api.etherscan.io/api?module=stats&action=tokensupply&contractaddress={XBURN_TOKEN_ADDRESS}&apikey={etherscan_api_key}"
        response = requests.get(etherscan_url)
        if response.status_code == 200:
            etherscan_data = response.json()
            if etherscan_data.get("status") == "1":
                token_supply = etherscan_data.get("result")
        else:
            print("Etherscan API returned HTTP", response.status_code)
    except Exception as e:
        print("Error fetching Etherscan data:", e)

    # Build final stats object
    stats = {
        "globalStats": global_stats_data,
        "liquidityPair": liquidity_pair,
        "dexscreener": dexscreener_data,
        "tokenSupply": token_supply
    }

    # Save the stats to a JSON file
    output_path = os.path.join(os.path.dirname(__file__), "stats.json")
    try:
        with open(output_path, "w") as outfile:
            json.dump(stats, outfile, indent=4)
        print("Stats saved to", output_path)
    except Exception as e:
        print("Error saving stats to file:", e)


if __name__ == "__main__":
    main() 