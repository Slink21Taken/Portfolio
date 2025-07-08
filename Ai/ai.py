import os
import requests
import pandas as pd
import joblib
import discord
import asyncio
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from get_things import (
    preprocess_combined,
    fetch_coinlore,
    fetch_coingecko,
    fetch_coinmarketcap,
    CMC_API_KEY
)
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# ========== CONFIG ==========
CHANNEL_ID = """123456789101112"""  # Replace with your actual channel ID
MODEL_PATH = "crypto_investment_model.pkl"

# ========== DISCORD SETUP ==========
intents = discord.Intents.default()
client = discord.Client(intents=intents)

# ========== UTILITIES ==========
async def send_terminal_messages(msg: str):
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    if not channel:
        print("⚠️ Channel not found.")
        return

    await channel.send(msg)

# ========== PREDICTION WORKFLOW ==========
async def run_predictions():
    print("🤖 Running predictions...")

    try:
        model = joblib.load(MODEL_PATH)
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        await send_terminal_messages("❌ Could not load prediction model.")
        return

    try:
        cl_data = fetch_coinlore()
        cg_data = fetch_coingecko()
        cmc_data = fetch_coinmarketcap(CMC_API_KEY)
        df = preprocess_combined(cl_data, cg_data, cmc_data)
    except Exception as e:
        print(f"❌ Failed to fetch or preprocess data: {e}")
        await send_terminal_messages("❌ Data fetch/preprocess error.")
        return

    if df.empty:
        await send_terminal_messages("⚠️ No valid coins to predict.")
        return

    try:
        X = df.drop(columns=['investment_grade'])
        preds = model.predict(X)
        probs = model.predict_proba(X)
    except Exception as e:
        await send_terminal_messages(f"❌ Prediction failed: {e}")
        return

    coin_symbols = [coin['symbol'].lower() for coin in cg_data]
    coin_names = [coin['name'] for coin in cg_data]
    categories = df.get('category', ["Uncategorized"] * len(df)).tolist()


    results = []
    for idx, pred in enumerate(preds):
        try:
            name = coin_names[idx] if idx < len(coin_names) else f"Coin {idx}"
            confidence = round(probs[idx][1] * 100, 2)
            label = "🔥 Worth It" if pred == 1 else "❌ Skip"
            category = categories[idx] if idx < len(categories) else "Uncategorized"
            results.append(f"{name} ({category}): {label} ({confidence}% confident)")

        except Exception as e:
            results.append(f"⚠️ Error with index {idx}: {e}")

    # Batch send results (avoid spam)
    batch_size = 10
    for i in range(0, len(results), batch_size):
        msg = "\n".join(results[i:i + batch_size])
        await send_terminal_messages(msg)
        await asyncio.sleep(1.5)  # Sleep to respect Discord rate limits

# ========== DISCORD HOOK ==========
@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    await run_predictions()
    await client.close()  # Exit after sending predictions (optional)

# ========== RUN ==========
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ DISCORD_BOT_TOKEN environment variable not set.")
    else:
        client.run(DISCORD_TOKEN)
