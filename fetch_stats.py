import os
import json
import requests
from web3 import Web3
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import time

# Contract addresses
# User confirmed XBURNMINTER_ADDRESS and XBURN_ADDRESS are the same
# Minter functionality + XBURN ERC20 functionality expected at this address
XBURNMINTER_ADDRESS = "0xe89AFDeFeBDba033f6e750615f0A0f1A37C78c4A"
XBURN_ADDRESS = "0xe89AFDeFeBDba033f6e750615f0A0f1A37C78c4A" # Same as Minter
XEN_ADDRESS = "0x2AB0e9e4eE70FFf1fB9D67031E44F6410170d00e"  # XEN on Base
CBXEN_ADDRESS = "0xffcbF84650cE02DaFE96926B37a0ac5E34932fa5" # CBXEN token - Updated address

# Base chain ID for APIs
BASE_CHAIN_ID = "base"

# Fallback RPC URLs (Updated List)
FALLBACK_RPC_URLS = [
    "https://base.llamarpc.com",
    "https://base.meowrpc.com",
    "https://rpc.owlracle.info/base/70d38ce1826c4a60bb2a8e05a6c8b20f",
    "https://endpoints.omniatech.io/v1/base/mainnet/public",
    "https://base-pokt.nodies.app",
    "https://mainnet.base.org",
    "https://developer-access-mainnet.base.org",
    "https://base-rpc.publicnode.com" # HTTP version
]

# Basic ERC20 ABI Snippet (for fallbacks)
BASIC_ERC20_ABI_SNIPPET = [
    {"constant":True,"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"payable":False,"stateMutability":"view","type":"function"},
    {"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"payable":False,"stateMutability":"view","type":"function"}
]

# --- Helper Functions ---

def init_web3_with_fallbacks(primary_rpc_url: str) -> Web3:
    """Initialize Web3 with fallback RPC providers if the primary fails"""
    # Try primary RPC first
    if primary_rpc_url:
        try:
            print(f"Trying primary RPC: {primary_rpc_url}")
            w3 = Web3(Web3.HTTPProvider(primary_rpc_url))
            if w3.is_connected():
                print(f"Successfully connected to primary RPC: {primary_rpc_url}")
                return w3
            else:
                print(f"Primary RPC connection failed, trying fallbacks")
        except Exception as e:
            print(f"Error connecting to primary RPC: {e}, trying fallbacks")
    else:
        print("No primary RPC_URL provided, starting with fallbacks.")

    # Try fallback RPCs
    for i, rpc_url in enumerate(FALLBACK_RPC_URLS):
        try:
            print(f"Trying fallback RPC {i+1}/{len(FALLBACK_RPC_URLS)}: {rpc_url}")
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            if w3.is_connected():
                print(f"Successfully connected to fallback RPC: {rpc_url}")
                return w3
            else:
                print(f"Fallback RPC {rpc_url} failed to connect cleanly.") # Added clarity
        except Exception as e:
            print(f"Fallback RPC {rpc_url} failed with error: {e}")

    # If all RPCs fail, raise an exception
    raise ConnectionError("All primary and fallback RPC connections failed")

def retry_with_fallback_rpcs(func, *args, **kwargs):
    """
    Retry a function with different RPC providers if it fails due to specific errors
    or rate limiting. Handles contract objects passed in args or kwargs.
    """
    # Extract the initial Web3 instance, assuming it's the first argument
    if not args or not isinstance(args[0], Web3):
        raise ValueError("The first argument must be a Web3 instance.")
    original_w3 = args[0]

    # Keep track of contracts to recreate
    contract_indices = {i: arg for i, arg in enumerate(args) if hasattr(arg, 'address') and hasattr(arg, 'abi')}
    contract_kwargs = {k: v for k, v in kwargs.items() if hasattr(v, 'address') and hasattr(v, 'abi')}

    # Try with original Web3 instance first
    try:
        return func(*args, **kwargs)
    except Exception as e:
        # Define conditions for retry (rate limit, connection errors, specific node issues)
        # Convert error to string for simpler checking
        error_str = str(e).lower()
        retry_conditions = [
            '429', 'too many requests', 'connectionerror', 'connection aborted',
            'connection pool', 'request timed out', 'timeout',
            'header not found', 'non-existent block', # Common node sync/data issues
            'could not transact', 'is contract deployed correctly' # Catch potential node errors manifesting as call failures
        ]

        should_retry = any(cond in error_str for cond in retry_conditions)

        if should_retry:
            print(f"Error detected in {func.__name__} (Type: {type(e).__name__}, Msg: {str(e)[:100]}...), trying with fallback RPCs.")

            # Try with fallback RPCs
            for i, rpc_url in enumerate(FALLBACK_RPC_URLS):
                # Skip if this is the same as the original RPC used
                if hasattr(original_w3, 'provider') and hasattr(original_w3.provider, 'endpoint_uri') and original_w3.provider.endpoint_uri == rpc_url:
                    continue

                try:
                    print(f"Trying {func.__name__} with fallback RPC {i+1}: {rpc_url}")
                    new_w3 = Web3(Web3.HTTPProvider(rpc_url))

                    if not new_w3.is_connected():
                        print(f"Could not connect to fallback RPC {rpc_url}")
                        continue

                    # Rebuild args and kwargs with the new w3 instance and recreated contracts
                    new_args = list(args)
                    new_args[0] = new_w3 # Replace Web3 instance

                    # Recreate contracts passed positionally
                    for index, original_contract in contract_indices.items():
                        try:
                            new_args[index] = new_w3.eth.contract(
                                address=original_contract.address,
                                abi=original_contract.abi
                            )
                            print(f"Recreated positional contract {original_contract.address[:10]}... for fallback.")
                        except Exception as contract_recreate_e:
                            print(f"Error recreating positional contract {original_contract.address[:10]}... for fallback {rpc_url}: {contract_recreate_e}")
                            raise # Propagate error if contract cannot be recreated

                    # Recreate contracts passed via kwargs
                    current_kwargs = kwargs.copy()
                    for key, original_contract in contract_kwargs.items():
                         try:
                            current_kwargs[key] = new_w3.eth.contract(
                                address=original_contract.address,
                                abi=original_contract.abi
                            )
                            print(f"Recreated kwarg contract '{key}' ({original_contract.address[:10]}...) for fallback.")
                         except Exception as contract_recreate_e:
                            print(f"Error recreating kwarg contract '{key}' ({original_contract.address[:10]}...) for fallback {rpc_url}: {contract_recreate_e}")
                            raise # Propagate error if contract cannot be recreated


                    # Try the function with the new Web3 instance and recreated contracts
                    result = func(*new_args, **current_kwargs)
                    print(f"Successfully executed {func.__name__} with fallback RPC {rpc_url}")
                    return result
                except Exception as inner_e:
                    print(f"Fallback RPC {rpc_url} attempt for {func.__name__} failed: {inner_e}")
                    time.sleep(1) # Brief pause before trying next RPC

            # If all fallbacks failed, raise the original exception
            print(f"All fallback RPCs failed for {func.__name__}. Raising original error.")
            raise e
        else:
            # Not an error type we retry on, just raise it
            print(f"Non-retryable error in {func.__name__}: {type(e).__name__}. Raising original.")
            raise e

def load_abi_safely(filepath, fallback_abi=None):
    """Loads ABI from file, returns fallback ABI on error."""
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ABI file not found: {filepath}. Using fallback.")
        return fallback_abi
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in ABI file {filepath}: {e}. Using fallback.")
        return fallback_abi
    except Exception as e:
        print(f"ERROR: Unexpected error loading ABI file {filepath}: {e}. Using fallback.")
        return fallback_abi

def get_historical_events(w3: Web3, contract: Any, event_name: str, from_block: int, to_block: int) -> List[Dict]:
    """Fetch historical events from the contract with retry logic and block range chunking"""
    max_retries = 3
    chunk_size = 9900 # Slightly under 10k to be safe
    all_events = []

    if not contract or not hasattr(contract, 'address') or not hasattr(contract, 'abi'):
         print(f"Warning: Invalid contract object passed to get_historical_events for event {event_name}.")
         return all_events # Return empty list if contract is invalid

    print(f"Fetching {event_name} events for {contract.address} from block {from_block} to {to_block}...")

    # --- Define the core logic as a separate function for retry ---
    def fetch_chunk(web3_instance, contract_instance, start, end):
        _events = []
        # Get the event object
        try:
             event_filter = getattr(contract_instance.events, event_name)
        except AttributeError:
             print(f"ERROR: Event '{event_name}' not found in contract ABI for {contract_instance.address}.")
             return [] # Cannot proceed without the event definition

        # Get event signature for get_logs
        try:
            event_abi = next(abi for abi in contract_instance.abi if abi.get('type') == 'event' and abi.get('name') == event_name)
            event_signature_hash = web3_instance.keccak(text=f"{event_name}({','.join(inp['type'] for inp in event_abi['inputs'])})").hex()

            # Use get_logs for potentially better performance/reliability
            raw_logs = web3_instance.eth.get_logs({
                'address': contract_instance.address,
                'fromBlock': start,
                'toBlock': end,
                'topics': [event_signature_hash]
            })
        except StopIteration:
             print(f"ERROR: Could not find ABI definition for event '{event_name}' in contract {contract_instance.address}.")
             return [] # Cannot proceed without ABI definition
        except Exception as sig_e:
             print(f"Error getting event signature/logs for {event_name} ({start}-{end}): {sig_e}. Falling back to create_filter.")
             # Fallback to create_filter if get_logs fails unexpectedly
             try:
                  log_filter = event_filter.create_filter(fromBlock=start, toBlock=end)
                  raw_logs = log_filter.get_all_entries()
             except Exception as filter_e:
                  print(f"Fallback create_filter also failed for {event_name} ({start}-{end}): {filter_e}")
                  raise filter_e # Re-raise if fallback fails

        # Process the events
        processed_count = 0
        skipped_count = 0
        for log in raw_logs:
            try:
                processed = event_filter.process_log(log)
                # Check for unexpected None return which can cause downstream issues
                if processed is None:
                     # print(f"Warning: process_log returned None unexpectedly for {event_name}. Raw log: {log}") # Keep commented unless debugging needed
                     skipped_count += 1
                     continue
                _events.append(processed)
                processed_count += 1
            except Exception: # Catch all processing errors silently
                # print(f"Error processing log for {event_name}: {e}. Log: {log}") # Keep commented unless debugging needed
                skipped_count += 1
                continue
        if skipped_count > 0:
             print(f"Skipped {skipped_count} logs for {event_name} in chunk {start}-{end} due to processing issues.")
        print(f"Processed {processed_count} {event_name} logs for chunk {start}-{end}.")
        return _events
    # --- End of core logic function ---

    current_block_num = from_block
    while current_block_num <= to_block:
        end_block_chunk = min(current_block_num + chunk_size, to_block)
        print(f"Querying chunk: {current_block_num} - {end_block_chunk}")
        try:
            # Wrap the chunk fetch attempt in the retry logic
            chunk_events = retry_with_fallback_rpcs(fetch_chunk, w3, contract, current_block_num, end_block_chunk)
            all_events.extend(chunk_events)
        except Exception as e:
            # If retries fail for a chunk, log it and move to the next
            print(f"FATAL: Failed to fetch {event_name} events for chunk {current_block_num}-{end_block_chunk} after all retries: {e}")
            # Optionally, break or return partial data if chunk failure is critical
            # return all_events # Example: return what we have so far

        current_block_num = end_block_chunk + 1
        time.sleep(0.2) # Small delay between chunks

    print(f"Finished fetching {event_name}. Total events processed: {len(all_events)}")
    return all_events

# --- Analysis Functions (Based on user's provided script) ---

def calculate_burn_metrics(w3: Web3, minter_contract: Any) -> Dict[str, Any]:
    """Calculate burn metrics from current contract state only (no historical events)"""
    metrics = { # Initialize with default/error state
        "total_burned": "Error",
        "burn_rank": "Error"
    }
    
    try:
        # Wrap contract calls in simple retry wrappers 
        def get_total_burned(web3, contract): return str(contract.functions.totalXenBurned().call())
        def get_burn_rank(web3, contract): return str(contract.functions.globalBurnRank().call())

        metrics["total_burned"] = retry_with_fallback_rpcs(get_total_burned, w3, minter_contract)
        metrics["burn_rank"] = retry_with_fallback_rpcs(get_burn_rank, w3, minter_contract)
        
        print("Retrieved current burn metrics from contract state")
    except Exception as e:
        print(f"Error calculating burn metrics: {e}")
        metrics["error"] = str(e) # Add top-level error
    return metrics

def analyze_burn_period(burn_events: List[Dict]) -> Dict[str, Any]:
    """Analyze burn events for a specific time period"""
    # Filter out potential None entries if process_log failed silently
    valid_events = [event for event in burn_events if event and 'args' in event]
    if not valid_events:
        return {
            "total_burns": 0, "total_burned": "0", "average_burn_size": "0",
            "unique_burners": 0, "largest_burn": "0", "smallest_burn": "0",
            "error": "No valid burn events found"
        }

    burn_amounts = []
    burners = set()
    processed_count = 0
    error_count = 0
    for event in valid_events:
        try:
            amount = event['args'].get('amount')
            user = event['args'].get('user')
            if amount is not None: # Check amount is not None before converting
                 burn_amounts.append(int(amount))
            if user:
                 burners.add(user)
            processed_count += 1
        except (KeyError, ValueError, TypeError) as e:
            # print(f"Error processing burn event args: {e}. Event: {event}") # Keep commented
            error_count += 1
            continue

    total_burned_sum = sum(burn_amounts)
    num_burns = len(burn_amounts)

    result = {
        "total_burns": processed_count, # Count successfully processed events
        "total_burned": str(total_burned_sum),
        "average_burn_size": str(total_burned_sum // num_burns) if num_burns > 0 else "0",
        "unique_burners": len(burners),
        "largest_burn": str(max(burn_amounts)) if burn_amounts else "0",
        "smallest_burn": str(min(burn_amounts)) if burn_amounts else "0"
    }
    if error_count > 0:
        result["processing_errors"] = error_count
    return result

def get_nft_analytics(w3: Web3, nft_contract: Any) -> Dict[str, Any]:
    """Get NFT statistics from current contract state only (no historical events)"""
    analytics = { # Default/error state
         "total_supply": "Error"
    }
    
    if not nft_contract:
        analytics["error"] = "NFT contract object is invalid or missing."
        return analytics

    try:
        # Wrap contract call in retry
        def get_nft_supply(web3, contract): return str(contract.functions.totalSupply().call())
        analytics["total_supply"] = retry_with_fallback_rpcs(get_nft_supply, w3, nft_contract)
        
        print("Retrieved NFT total supply from contract state")
    except Exception as e:
        print(f"Error calculating NFT analytics: {e}")
        analytics["error"] = str(e)
    return analytics

def get_swap_analytics(w3: Web3, minter_contract: Any) -> Dict[str, Any]:
    """Get swap analytics from current contract state only (no historical events)"""
    analytics = { # Default/error state
        "accumulation": {"error": "Not calculated"}
    }
    
    try:
        # Wrap contract call in retry
        def get_acc_progress(web3, contract): return contract.functions.getAccumulationProgress().call()
        acc_stats = retry_with_fallback_rpcs(get_acc_progress, w3, minter_contract)

        current_pending = acc_stats[0]
        threshold = acc_stats[1]
        progress_percentage = (current_pending / threshold) * 100 if threshold > 0 else 0
        analytics["accumulation"] = {
            "current_pending_xen": str(current_pending),
            "threshold": str(threshold),
            "progress_percentage": progress_percentage
        }
        
        print("Retrieved swap accumulation data from contract state")
    except Exception as e:
        print(f"Error calculating swap analytics: {e}")
        analytics["error"] = str(e) # Add top-level error
    return analytics

def get_token_total_supply_with_retry(w3: Web3, token_address: str, abi_file_path: str) -> Dict[str, str]:
    """Fetch total supply for a token, using retry logic and ABI fallback."""
    result = {
        "total_supply": "Error",
        "total_supply_formatted": "Error",
        "decimals": "18", # Default
        "error": None
    }

    token_abi = load_abi_safely(abi_file_path, fallback_abi=BASIC_ERC20_ABI_SNIPPET)
    if not token_abi:
         result["error"] = f"Failed to load ABI from {abi_file_path} or fallback."
         return result

    # Ensure the ABI we ended up with has totalSupply and decimals
    # If using fallback, it's guaranteed. If loaded, check.
    has_supply_func = any(f.get('name') == 'totalSupply' for f in token_abi if f.get('type') == 'function')
    has_decimals_func = any(f.get('name') == 'decimals' for f in token_abi if f.get('type') == 'function')

    if not has_supply_func:
         result["error"] = "Loaded ABI or fallback missing 'totalSupply' function."
         # We might still try decimals if it exists
    if not has_decimals_func:
         print(f"Warning: ABI for {token_address} missing 'decimals' function, using default 18.")
         # Keep default 18

    # Define wrapper functions for retry
    def get_supply(web3, contract):
        if not has_supply_func: raise Exception("totalSupply function not in ABI")
        return contract.functions.totalSupply().call()

    def get_decimals(web3, contract):
        if not has_decimals_func: raise Exception("decimals function not in ABI")
        return contract.functions.decimals().call()

    try:
        token_contract = w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=token_abi
        )

        # Get Decimals first (with retry, fallback to 18 on error)
        if has_decimals_func:
            try:
                decimals_val = retry_with_fallback_rpcs(get_decimals, w3, token_contract)
                result["decimals"] = str(decimals_val)
            except Exception as e:
                print(f"Error getting decimals for {token_address} even with retry, using 18: {e}")
                # Keep default 18
        # else: decimals remains 18 (default)

        # Get Total Supply (with retry)
        if has_supply_func:
            try:
                total_supply_raw = retry_with_fallback_rpcs(get_supply, w3, token_contract)
                result["total_supply"] = str(total_supply_raw)
                # Try formatting
                try:
                    result["total_supply_formatted"] = str(total_supply_raw / (10 ** int(result["decimals"])))
                except Exception as format_e:
                    print(f"Error formatting total supply for {token_address}: {format_e}")
                    result["total_supply_formatted"] = "Error"
                    result["error"] = (result["error"] + "; " if result["error"] else "") + "Formatting failed"
            except Exception as e:
                print(f"Error getting total supply for {token_address} even with retry: {e}")
                result["error"] = f"totalSupply call failed: {str(e)}"
                # Supply is already "Error"
        else:
             # Error already set if has_supply_func is False
             pass


    except Exception as e: # Catch contract init errors
        print(f"Major error interacting with token {token_address}: {e}")
        result["error"] = f"Contract interaction failed: {str(e)}"

    return result


# --- Main Execution ---

def main():
    print("Starting enhanced stats collection...")

    # Load environment variables
    rpc_url = os.environ.get("RPC_URL")
    # Removed Etherscan API key check as it's not needed for this version

    # Initialize web3 using fallbacks
    w3 = None
    try:
        w3 = init_web3_with_fallbacks(rpc_url)
    except ConnectionError as e:
        print(f"CRITICAL ERROR: {e}")
        return # Exit if no RPC connection possible
    except Exception as e:
        print(f"CRITICAL ERROR initializing Web3: {e}")
        return

    # Load mandatory contract ABIs
    # Assuming these ABI files exist and are correct
    minter_abi_path = "XBurnMinter_abi.json"
    nft_abi_path = "XBurnNFT_abi.json"
    cbxen_abi_path = "CBXEN_abi.json" # ABI for CBXEN token

    xburnminter_abi = load_abi_safely(minter_abi_path)
    nft_abi = load_abi_safely(nft_abi_path)

    if not xburnminter_abi or not nft_abi:
         print("CRITICAL ERROR: Failed to load mandatory Minter or NFT ABI. Exiting.")
         return

    # Initialize contracts (wrap calls in retry)
    minter_contract = None
    nft_contract = None
    nft_address = "Error" # Default state

    try:
        minter_contract = w3.eth.contract(address=Web3.to_checksum_address(XBURNMINTER_ADDRESS), abi=xburnminter_abi)
        print("Minter contract object created.")

        # Define wrapper for nftContract call
        def get_nft_addr(web3, contract): return contract.functions.nftContract().call()

        print("Attempting to retrieve NFT contract address...")
        nft_address = retry_with_fallback_rpcs(get_nft_addr, w3, minter_contract)
        print(f"Retrieved NFT address: {nft_address}")

        if nft_address and Web3.is_address(nft_address) and nft_address != '0x0000000000000000000000000000000000000000':
            nft_contract = w3.eth.contract(address=Web3.to_checksum_address(nft_address), abi=nft_abi)
            print("NFT contract object created.")
        else:
            print("WARNING: Invalid or zero address returned for NFT contract. NFT stats will be skipped.")
            nft_contract = None # Ensure it's None if address is bad

    except Exception as e:
        print(f"CRITICAL Error initializing core contracts: {e}")
        # Allow script to continue if possible, but core stats might fail
        if not minter_contract: minter_contract = None # Ensure None if init failed
        if not nft_contract: nft_contract = None


    # --- Data Fetching (using retry wrappers where needed) ---

    # Burn Metrics
    burn_metrics = {}
    if minter_contract:
        burn_metrics = calculate_burn_metrics(w3, minter_contract)
    else:
        burn_metrics = {"error": "Minter contract not available"}

    # NFT Analytics
    nft_analytics = {}
    if nft_contract: # Check if nft_contract was successfully initialized
        nft_analytics = get_nft_analytics(w3, nft_contract)
    else:
        nft_analytics = {"error": f"NFT contract not available (Address: {nft_address})"}

    # Swap Analytics
    swap_analytics = {}
    if minter_contract:
        swap_analytics = get_swap_analytics(w3, minter_contract)
    else:
        swap_analytics = {"error": "Minter contract not available"}

    # Global Stats
    global_stats_data = {"error": "Minter contract not available"}
    if minter_contract:
        try:
            # Define wrapper for getGlobalStats call
            def get_global_stats(web3, contract): return contract.functions.getGlobalStats().call()
            print("Attempting to retrieve Global Stats...")
            global_stats = retry_with_fallback_rpcs(get_global_stats, w3, minter_contract)

            # Process if data is valid tuple/list
            if global_stats and isinstance(global_stats, (list, tuple)) and len(global_stats) >= 5:
                 global_stats_data = {
                     "currentAMP": str(global_stats[0]),
                     "daysSinceLaunch": str(global_stats[1]),
                     "totalBurnedXEN": str(global_stats[2]),
                     "totalMintedXBURN": str(global_stats[3]), # Corresponds to Minter data
                     "ampDecayDaysLeft": str(global_stats[4])
                 }
                 print("Successfully retrieved Global Stats.")
            else:
                 print(f"Warning: getGlobalStats call returned unexpected data: {global_stats}")
                 global_stats_data = {"error": "Invalid data structure returned"}
        except Exception as e:
            print(f"Error getting global stats: {e}")
            global_stats_data = {"error": f"Failed to retrieve global stats: {str(e)}"}

    # --- Fetch Token Supplies ---
    print("Fetching token total supplies...")
    # Use Minter ABI for XBURN token supply, per user confirmation
    xburn_supply_data = get_token_total_supply_with_retry(w3, XBURN_ADDRESS, minter_abi_path)
    cbxen_supply_data = get_token_total_supply_with_retry(w3, CBXEN_ADDRESS, cbxen_abi_path) # Assumes CBXEN_abi.json exists or uses fallback
    # --- End Fetch Token Supplies ---

    # Build final stats object
    stats = {
        "timestamp": datetime.now().isoformat(),
        "globalStats": global_stats_data,
        "burnMetrics": burn_metrics,
        "swapAnalytics": swap_analytics,
        # "liquidityPools": {}, # Removed DexScreener data
        "nftAnalytics": nft_analytics,
        "tokenSupply": { # Added section for token supplies
            "xburn": xburn_supply_data,
            "cbxen": cbxen_supply_data
        },
        "lastUpdated": int(time.time()) # Use script execution time
    }

    # Save stats to file
    try:
        with open("stats.json", "w") as outfile:
            json.dump(stats, outfile, indent=4)
        print("Enhanced stats successfully saved to stats.json")
    except Exception as e:
        print(f"Error saving stats: {e}")
        # Optionally create an empty/error file here if save fails

if __name__ == "__main__":
    main() 
