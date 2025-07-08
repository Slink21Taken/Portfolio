import requests
import os
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import joblib
import time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv()
CMC_API_KEY= os.getenv("API_KEY")



# ========== UTILITY FUNCTIONS ==========

def safe_float(val, fallback=0.0):
    try:
        return float(val) if val not in [None, '', 'null'] else fallback
    except (TypeError, ValueError):
        return fallback

# ========== DATA FETCHING ==========

def fetch_coinlore():
    url = "https://api.coinlore.net/api/tickers/"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()['data']

def fetch_coingecko():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        'vs_currency': 'usd',
        'order': 'market_cap_desc',
        'per_page': 100,
        'page': 1,
        'sparkline': False
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()

def fetch_coinmarketcap(api_key):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': api_key
    }
    params = {
        'start': '1',
        'limit': '100',
        'convert': 'USD'
    }
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()['data']

# Optional: If you want full CoinGecko details with platforms
def fetch_coingecko_detailed(limit=100):
    url_list = "https://api.coingecko.com/api/v3/coins/list"
    response = requests.get(url_list)
    response.raise_for_status()
    coin_list = response.json()[:limit]

    detailed_data = []
    for coin in coin_list:
        try:
            url_detail = f"https://api.coingecko.com/api/v3/coins/{coin['id']}"
            res = requests.get(url_detail, params={'localization': 'false'})
            if res.status_code == 200:
                data = res.json()
                detailed_data.append(data)
                time.sleep(1.2)  # Respect CoinGecko rate limit
        except Exception as e:
            print(f"⚠️ Error fetching {coin['id']}: {e}")
    return detailed_data

# ========== FILTER FUNCTION ==========

def is_recent_solana_memecoin_dex_focused(coin):
    # Simplified placeholder, since /markets endpoint lacks 'platforms'
    categories = coin.get('categories', [])
    return any('solana' in c.lower() for c in categories)

# ========== PREPROCESSING ==========

def preprocess_combined(cl_data, cg_data, cmc_data):
    combined = []

    for cg in cg_data:
        symbol = cg.get('symbol', '').lower()
        if not symbol:
            continue

        cl_match = next((cl for cl in cl_data if cl['symbol'].lower() == symbol), None)
        cmc_match = next((c for c in cmc_data if c['symbol'].lower() == symbol), None)

        if cl_match and cmc_match:
            try:
                raw_categories = cg.get('categories', [])
                normalized_cat = next((c for c in raw_categories if c), "Uncategorized")

                cg_liquidity = safe_float(cg.get('circulating_supply')) / max(safe_float(cg.get('total_supply'), 1), 1)
                cg_market_cap = safe_float(cg.get('market_cap'))
                cg_change = safe_float(cg.get('price_change_percentage_24h'))

                cl_liquidity = safe_float(cl_match.get('csupply')) / max(safe_float(cl_match.get('tsupply'), 1), 1)
                cl_market_cap = safe_float(cl_match.get('market_cap_usd'))
                cl_change = safe_float(cl_match.get('percent_change_24h'))

                cmc_quote = cmc_match.get('quote', {}).get('USD', {})
                cmc_liquidity = safe_float(cmc_match.get('circulating_supply')) / max(safe_float(cmc_match.get('max_supply'), 1), 1)
                cmc_market_cap = safe_float(cmc_quote.get('market_cap'))
                cmc_change = safe_float(cmc_quote.get('percent_change_24h'))

                category_map = {
                        "Meme": 1,
                        "Stablecoin": 2,
                        "Privacy": 3,
                        "DeFi": 4,
                        "NFT": 5,
                        "AI": 6,
                        "Gaming": 7,
                        "Layer1": 8,
                        "Uncategorized": 0
                    }
                raw_categories = cg.get('categories', [])
                normalized_cat = next((c for c in raw_categories if c), "Uncategorized")
                category_id = category_map.get(normalized_cat, 0)

                entry = {
                    'liquidity_avg': (cg_liquidity + cl_liquidity + cmc_liquidity) / 3,
                    'market_cap_avg': (cg_market_cap + cl_market_cap + cmc_market_cap) / 3,
                    'volume_change_avg': (cg_change + cl_change + cmc_change) / 300,
                    'market_cap_spread': max(cg_market_cap, cl_market_cap, cmc_market_cap) - min(cg_market_cap, cl_market_cap, cmc_market_cap),
                    'liquidity_spread': max(cg_liquidity, cl_liquidity, cmc_liquidity) - min(cg_liquidity, cl_liquidity, cmc_liquidity),
                    'investment_grade': int(cg_liquidity > 0.7 and cg_market_cap > 50_000_000),
                    'category': category_id
                }

                combined.append(entry)
            except Exception as e:
                print(f"⚠️ Error processing {symbol}: {e}")

    df = pd.DataFrame(combined)
    if df.empty:
        print("⚠️ No valid data found during preprocessing.")
    return df

# ========== TRAINING ==========

def train_and_save(df):
    if df.empty:
        print("⚠️ No data passed the filter. Check filtering logic or expand criteria.")
        return

    print("📊 Class distribution:\n", df['investment_grade'].value_counts())

    X = df.drop('investment_grade', axis=1)
    y = df['investment_grade']
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X, y)
    joblib.dump(model, 'crypto_investment_model.pkl')
    print("✅ Model saved as crypto_investment_model.pkl")

# ========== MAIN SCRIPT ==========

if __name__ == "__main__":
    print("🚀 Fetching data...")
    try:
        coinlore = fetch_coinlore()
        coinmarketcap = fetch_coinmarketcap(CMC_API_KEY)

        # If using detailed fetch, replace cg_all with filtered detailed data
        cg_all = fetch_coingecko_detailed(limit = 100)
        cg_all = [c for c in cg_all if is_recent_solana_memecoin_dex_focused(c)]

        cg_filtered = cg_all  # You can filter based on some heuristic if needed

        print(f"✅ CoinGecko entries fetched: {len(cg_filtered)}")

        df = preprocess_combined(coinlore, cg_filtered, coinmarketcap)
        print(df.head())

        train_and_save(df)

    except Exception as e:
        print(f"❌ Fatal error: {e}")
