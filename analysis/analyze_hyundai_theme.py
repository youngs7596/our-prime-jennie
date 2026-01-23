
import sys
import os
import logging
from datetime import datetime, timedelta
import pandas as pd

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.kis.gateway_client import KISGatewayClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HYUNDAI_GROUP = {
    "005380": "Hyundai Motor",
    "000270": "Kia",
    "012330": "Hyundai Mobis",
    "086280": "Hyundai Glovis",
    "064350": "Hyundai Rotem",
    "011210": "Hyundai Wia",
    "307950": "Hyundai Autoever",
    "000720": "Hyundai E&C",
    "004020": "Hyundai Steel",
    "214320": "Innocean"
}

def analyze_theme():
    # Use standard Gateway URL
    gateway = KISGatewayClient()
    
    print(f"\nAnalyzing Hyundai Motor Group Performance (Last 5 Days)")
    print("=" * 60)
    
    results = []
    
    for code, name in HYUNDAI_GROUP.items():
        try:
            # Fetch last 10 days to ensure we have enough for 5 days return
            data = gateway.get_stock_daily_prices(code, num_days_to_fetch=10)
            
            if data is None:
                print(f"Failed to fetch data for {name} ({code})")
                continue
                
            # Convert to DataFrame if it's a list
            if isinstance(data, list):
                if not data:
                    print(f"No data for {name} ({code})")
                    continue
                df = pd.DataFrame(data)
            else:
                if data.empty:
                    print(f"Empty data for {name} ({code})")
                    continue
                df = data
                
            # Ensure proper sorting (Oldest to Newest)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            
            if len(df) < 5:
                print(f"Not enough data for {name} ({code})")
                continue
                
            # Calculate returns
            last_price = df.iloc[-1]['price']
            prev_1d = df.iloc[-2]['price']
            prev_3d = df.iloc[-4]['price']  # 3 days ago
            prev_5d = df.iloc[-6]['price'] if len(df) >= 6 else df.iloc[0]['price']
            
            ret_1d = ((last_price - prev_1d) / prev_1d) * 100
            ret_3d = ((last_price - prev_3d) / prev_3d) * 100
            ret_5d = ((last_price - prev_5d) / prev_5d) * 100
            
            # Additional check: Daily Close Prices for last 5 days
            recent_prices = df.tail(5)[['date', 'price']].copy()
            recent_prices['date_str'] = recent_prices['date'].dt.strftime('%m-%d')
            
            results.append({
                'code': code,
                'name': name,
                'price': last_price,
                '1D (%)': ret_1d,
                '3D (%)': ret_3d,
                '5D (%)': ret_5d,
                'recent_closes': recent_prices.to_dict('records')
            })
            
        except Exception as e:
            logger.error(f"Error processing {name}: {e}")

    # Sort by 3D return (recent momentum)
    results.sort(key=lambda x: x['3D (%)'], reverse=True)
    
    # Print Table
    print(f"{'Name':<20} {'Price':<10} {'1D(%)':<8} {'3D(%)':<8} {'5D(%)':<8}")
    print("-" * 60)
    for res in results:
        print(f"{res['name']:<20} {res['price']:<10,.0f} {res['1D (%)']:>6.2f}   {res['3D (%)']:>6.2f}   {res['5D (%)']:>6.2f}")
        
    print("-" * 60)
    
    # Verify User's Hypothesis
    avg_3d = sum(r['3D (%)'] for r in results) / len(results) if results else 0
    up_count = sum(1 for r in results if r['3D (%)'] > 0)
    
    print(f"\nSummary:")
    print(f"Group Avg 3D Return: {avg_3d:.2f}%")
    print(f"Positive Movers: {up_count}/{len(results)}")
    
    if avg_3d > 2.0 and up_count > len(results) * 0.7:
        print("✅ Hypothesis Confirmed: The group is moving strongly together.")
    elif avg_3d > 5.0:
        print("🚀 Hypothesis Strong: Significant group rally detected.")
    else:
        print("⚠️ Mixed/Weak Signal: Group movement is not strongly synchronized or flat.")

if __name__ == "__main__":
    analyze_theme()
