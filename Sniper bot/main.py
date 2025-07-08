import asyncio
import os
import json
import time
import re
import base64
import random
import struct
import logging
from datetime import datetime

import aiohttp
import requests
import websockets

from dotenv import load_dotenv

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import Transaction

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
from solana.rpc.core import RPCException
from solana.exceptions import SolanaRpcException

# === Logging Configuration ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)  #Initialize logging for disc (dont work)

# === Load environment ===
load_dotenv()
WS_API_KEY = os.getenv("WS_API_KEY")
if not WS_API_KEY:  #Check if WS_API_KEY is set
    raise Exception("WS_API_KEY environment variable not set")
HTTP_API_KEY = os.getenv("HTTP_API_KEY")
if not HTTP_API_KEY:  #Check if HTTP_API_KEY is set
    raise Exception("HTTP_API_KEY environment variable not set")
# === Config ===
HELIUS_WS = "wss://mainnet.helius-rpc.com/?api-key=replce_with_your_ws_api_key"  #Replace with your WS API key
HELIUS_HTTP = "https://mainnet.helius-rpc.com/?api-key=replace_with_your_http_api_key"  #Replace

TARGET_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
WRAPPED_SOL_MINT = "So11111111111111111111111111111111111111112"  # Wrapped SOL
RAY_AMM_V4 = "RVKd61ztZW9DQ8cA6xgUjydEYDNo6DCrU1bWW1X2VJh"

CONFIG = {
    "rpc": os.getenv("RPC_URL"),
    "ws": os.getenv("WS_URL"),
    "slippage_bps": 50,
    "amount_to_swap": 0.001,  # Testing amount
    "take_profit": 1.5,
    "stop_loss": 0.9,
    "check_interval": 2,
    "auto_sell_delay": 300,
}

RATE_LIMIT = 5
last_timestamps = []
semaphore = asyncio.Semaphore(1)  #To prevents 429 errors.

SOL_MINT = WRAPPED_SOL_MINT
seen = set()

CURRENT_SOL = 0
keypair = None
pubkey = None
client = None


# === Utilities ===
def parse_ray_log(log):
    if "ray_log:" not in log:
        return None
    payload = log.split("ray_log:")[1].strip()     #Filtering The stream
    try:
        decoded = base64.b64decode(payload)
        token_a_amount, token_b_amount = struct.unpack_from("<QQ", decoded)
        return {
            "amount_in_raw": token_a_amount,
            "amount_out_raw": token_b_amount
        }
    except Exception as e:
        print("⚠️ Failed to parse ray_log:", e)
        logger.warning(f"Failed to parse ray_log: {e}")
        return None


def adjust_wrapped_sol_address(mint):
    result = mint + "2" if mint == WRAPPED_SOL_MINT else mint
    print(f"Adjusted wrapped sol address: {result}")
    logger.warning(f"Adjusted wrapped sol address: {result}")     
    return result


async def fetch_transaction(signature, retries=3, delay=1):
    headers = {"Content-Type": "application/json"}
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
    }

    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(HELIUS_HTTP, headers=headers, json=body) as resp:    #Name is self explanatory
                    if resp.status != 200:
                        print(f"⚠️ Failed to fetch tx: HTTP {resp.status}")
                        logger.warning(f"Failed to fetch tx: HTTP {resp.status}")
                        await asyncio.sleep(delay)
                        continue
                    result = await resp.json()
                    return result.get("result", {})
        except Exception as e:
            print(f"⚠️ Error fetching tx (attempt {attempt+1}): {e}")
            logger.warning(f"Error fetching tx (attempt {attempt+1}): {e}")
            await asyncio.sleep(delay)
    return None


async def wait_for_slot():
    now = time.monotonic()
    while last_timestamps and now - last_timestamps[0] > 1:
        last_timestamps.pop(0)
    while len(last_timestamps) >= RATE_LIMIT:
        await asyncio.sleep(0.01)                     #Prevents 429 errors still
        now = time.monotonic()
        while last_timestamps and now - last_timestamps[0] > 1:
            last_timestamps.pop(0)
    last_timestamps.append(time.monotonic())
    print("Waited for rate limit slot")
    logger.warning("Waited for rate limit slot")


async def rate_limited_rpc_call(coro_func, *args, **kwargs):
    await wait_for_slot()
    result = await coro_func(*args, **kwargs)
    print("Performed rate-limited RPC call")
    logger.warning("Performed rate-limited RPC call")
    return result               #Prevents 429 errors


async def request_airdrop_with_retry(client: AsyncClient, pubkey: Pubkey, lamports: int, max_retries=5):
    retry_delay = 2
    for attempt in range(1, max_retries + 1):              #Airdrops with extra anti- error 429 measures. Only use if on devnet please!
        try:
            resp = await rate_limited_rpc_call(client.request_airdrop, pubkey, lamports)
            print(f"Airdrop requested successfully on attempt {attempt}")
            logger.warning(f"Airdrop requested successfully on attempt {attempt}")
            return resp
        except SolanaRpcException as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                sleep_time = retry_delay + random.uniform(0, 1)
                print(f"⏳ Retrying airdrop in {sleep_time:.2f}s (attempt {attempt}/{max_retries})")
                logger.warning(f"Retrying airdrop in {sleep_time:.2f}s (attempt {attempt}/{max_retries})")
                await asyncio.sleep(sleep_time)
                retry_delay *= 2
            else:
                print(f"❌ Airdrop failed with non-retryable error: {e}")
                logger.warning(f"Airdrop failed with non-retryable error: {e}")
                raise e
    print("❌ Max retries exceeded for airdrop")
    logger.warning("Max retries exceeded for airdrop")
    raise Exception("Max retries exceeded for airdrop")


def get_sol_price():
    try:
        r = requests.get("https://price.jup.ag/v4/price?ids=SOL", timeout=5)
        r.raise_for_status()
        price = r.json()["data"]["SOL"]["price"]
        print(f"Got SOL price from Jupiter: {price}")
        logger.warning(f"Got SOL price from Jupiter: {price}")          #Gets current price of native SOL
        return price
    except Exception:
        print("🔁 Falling back to CoinGecko.")
        logger.warning("Falling back to CoinGecko.")
        fallback = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd")
        price = fallback.json()['solana']['usd']
        print(f"Got SOL price from CoinGecko fallback: {price}")
        logger.warning(f"Got SOL price from CoinGecko fallback: {price}")
        return price


def jupiter_quote(input_mint, output_mint, amount):
    url = "https://quote-api.jup.ag/v6/quote"
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": int(amount * 1e9),
        "slippageBps": CONFIG["slippage_bps"]
    }                                                    #Gets a quote from jupiter for swap
    r = requests.get(url, params=params)
    r.raise_for_status()
    data = r.json()
    if data.get("data"):
        print(f"Received Jupiter quote for {input_mint} → {output_mint}")
        logger.warning(f"Received Jupiter quote for {input_mint} → {output_mint}")
        return data["data"][0]
    print("❌ No quote available")
    logger.warning("No quote available")
    raise Exception("No quote available")


def jupiter_swap(quote):
    url = "https://quote-api.jup.ag/v6/swap"
    payload = {
        "route": quote,
        "userPublicKey": str(pubkey),
        "wrapUnwrapSOL": True,
        "feeAccount": None
    }
    r = requests.post(url, json=payload)             #Swaps...
    r.raise_for_status()
    print("Performed Jupiter swap request")
    logger.warning("Performed Jupiter swap request")
    return r.json()["swapTransaction"]


async def execute_swap(input_mint, output_mint, amount):
    print(f"🛠️ Swapping {amount} {input_mint} → {output_mint}")
    logger.warning(f"Swapping {amount} {input_mint} → {output_mint}")
    quote = jupiter_quote(input_mint, output_mint, amount)
    usd_value = (quote["inAmount"] / 1e9) * (quote["outAmount"] / quote["inAmount"]) * CURRENT_SOL      #Swaps

    if usd_value < 500:
        print(f"💧 Insufficient liquidity: ${usd_value:.2f}")
        logger.warning(f"Insufficient liquidity: ${usd_value:.2f}")
        return None

    tx_b64 = jupiter_swap(quote)
    tx_bytes = base64.b64decode(tx_b64)
    tx = Transaction.deserialize(tx_bytes)
    tx.sign_partial(keypair)

    try:
        txid = await rate_limited_rpc_call(client.send_transaction, tx, keypair, opts=TxOpts(skip_preflight=True))
        print("🔁 Swap executed:", txid.value)
        logger.warning(f"Swap executed: {txid.value}")
        return quote
    except RPCException as e:
        print("❌ Transaction failed:", e)
        logger.warning(f"Transaction failed: {e}")
        return None


async def monitor_trade(output_mint, entry_quote):
    entry_price = entry_quote["outAmount"] / entry_quote["inAmount"]
    print(f"📈 Entry price: {entry_price:.10f}")
    logger.warning(f"Entry price: {entry_price:.10f}")
    start = datetime.now()                                           #Monitors stream and determines when to swap
    while (datetime.now() - start).seconds < CONFIG["auto_sell_delay"]:
        try:
            q = jupiter_quote(output_mint, entry_quote["inputMint"], entry_quote["outAmount"] / 1e9)
            price = q["outAmount"] / entry_quote["outAmount"]

            print(f"📊 Current price: {price:.10f}")
            logger.warning(f"Current price: {price:.10f}")
            if price >= entry_price * CONFIG["take_profit"]:
                print("🎯 Take profit hit!")
                logger.warning("Take profit hit!")
                await execute_swap(output_mint, entry_quote["inputMint"], entry_quote["outAmount"] / 1e9)
                return
            if price <= entry_price * CONFIG["stop_loss"]:
                print("💔 Stop loss triggered.")
                logger.warning("Stop loss triggered.")
                await execute_swap(output_mint, entry_quote["inputMint"], entry_quote["outAmount"] / 1e9)
                return
        except Exception as e:
            print("⚠️ Error in monitor:", e)
            logger.warning(f"Error in monitor: {e}")

        await asyncio.sleep(CONFIG["check_interval"])


async def analyze_token(mint):
    async with aiohttp.ClientSession() as session:
        async with session.get("https://token.jup.ag/all") as resp:
            if resp.status != 200:
                print("❌ Jupiter token list unavailable")
                logger.warning("Jupiter token list unavailable")                        #Determine if token is worth it
                return {"score": 0, "reason": "Jupiter token list unavailable"}
            tokens = await resp.json()

    token = next((t for t in tokens if t["address"] == mint), None)
    if not token:
        print(f"❌ Token {mint} not found")
        logger.warning(f"Token {mint} not found")
        return {"score": 0, "reason": "Token not found"}

    score = 0
    flags = []

    if token.get("symbol"):
        score += 1
    else:
        flags.append("Missing symbol")

    if token.get("name") and any(kw in token["name"].upper() for kw in ["DOGE", "PEPE", "CAT"]):
        score += 1

    if token.get("decimals", 0) > 0:
        score += 1
    else:
        flags.append("No decimals or zero decimals")

    if token.get("extensions", {}).get("coingeckoId"):
        score += 1
    else:
        flags.append("No Coingecko ID")

    print(f"Token analysis for {mint}: score={score}, flags={flags}")
    logger.warning(f"Token analysis for {mint}: score={score}, flags={flags}")

    return {
        "score": score,
        "flags": flags,
        "token": token
    }


async def handle_transaction_update(tx_update):
    signature = tx_update.get("signature")
    if not signature or signature in seen:
        return
    seen.add(signature)
    print(f"New transaction signature: {signature}")
    logger.warning(f"New transaction signature: {signature}")

    tx_info = await fetch_transaction(signature)
    if not tx_info:
        print(f"⚠️ Transaction details not found for {signature}")             #Handle transactions (details, signatures etc.)
        logger.warning(f"Transaction details not found for {signature}")
        return

    logs = tx_info.get("meta", {}).get("logMessages", [])
    for log in logs:
        ray_log_data = parse_ray_log(log)
        if ray_log_data:
            print(f"Ray log parsed: {ray_log_data}")
            logger.warning(f"Ray log parsed: {ray_log_data}")
            # Implement your logic here for the parsed ray log


async def listen_for_transactions():
    async with websockets.connect(HELIUS_WS) as ws:
        subscribe_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [
                {"mentions": [TARGET_PROGRAM_ID]},
                {"commitment": "confirmed"}                          #Searches across TARGET_PROGRAM_ID and filters
            ]
        }
        await ws.send(json.dumps(subscribe_request))
        print("Subscribed to Helius logs")
        logger.warning("Subscribed to Helius logs")

        while True:
            try:
                message = await ws.recv()
                data = json.loads(message)

                if "method" in data and data["method"] == "logsNotification":
                    tx_update = data["params"]["result"]
                    await handle_transaction_update(tx_update)

            except Exception as e:
                print(f"⚠️ Websocket error: {e}")
                logger.warning(f"Websocket error: {e}")
                await asyncio.sleep(5)


async def main():
    global keypair, pubkey, client, CURRENT_SOL
    secret_json_str = os.getenv("WALLET_SECRET_JSON")
    if not secret_json_str:
        raise Exception("WALLET_SECRET_JSON environment variable not set")
    secret_key_list = json.loads(secret_json_str)  # Parse JSON array into list of ints
    secret_key_bytes = bytes(secret_key_list) 

    keypair = Keypair.from_bytes(secret_key_bytes)
    pubkey = keypair.pubkey()
    client = AsyncClient(CONFIG["rpc"], commitment=Confirmed)    #Executes everything.

    CURRENT_SOL = get_sol_price()
    print(f"Current SOL price set to {CURRENT_SOL}")
    logger.warning(f"Current SOL price set to {CURRENT_SOL}")

    # Optionally request airdrop if balance is low - example usage
    balance_resp = await client.get_balance(pubkey)
    balance = balance_resp.value if balance_resp else 0
    print(f"Current balance: {balance} lamports")
    logger.warning(f"Current balance: {balance} lamports")
    if balance < 1000000:
        if "devnet" in CONFIG['rpc']:
            await request_airdrop_with_retry(client, pubkey, 10000000)
        else:
            print("Balance low. Please fund!")
            logger.warning("Balance low. Please fund!")
    await listen_for_transactions()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down gracefully...")
        logger.warning("Shutting down gracefully...")    #This doesnt work.... Discord in general doesnt work


#What I need you to do Mischa:
#More error handling
#Make discord work
#Add sniper triger 
#Fix bugs (there are quite a few)
#I've done 80% of the work. You handle the rest nigga