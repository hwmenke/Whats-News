import yfinance as yf
import pandas as pd
import sys

def test_fetch(symbol="AAPL"):
    print(f"Testing fetch for {symbol}...")
    try:
        ticker = yf.Ticker(symbol)
        print("Ticker object created.")
        
        print("Fetching history...")
        # Use a short period to test connectivity
        raw = ticker.history(period="5d", interval="1d", auto_adjust=True)
        print(f"History returned. Shape: {raw.shape}")
        
        if raw.empty:
            print("ERROR: History is empty.")
            return
            
        print("Columns found:")
        print(raw.columns.tolist())
        
        print("First few rows:")
        print(raw.head())
        
        print("Testing ticker.info (this often hangs)...")
        # Try with a timeout if possible, but yfinance doesn't expose it easily here
        info = ticker.info
        print(f"Info retrieved. Name: {info.get('longName')}")
        
        print("Test SUCCESSFUL")
    except Exception as e:
        print(f"Test FAILED: {str(e)}")

if __name__ == "__main__":
    test_fetch()
