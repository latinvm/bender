from trader.bitvavo import BitvavoClient
from trader.config import get_config
from trader.market import MarketOperations

def main():
    # Initialize
    config = get_config()
    client = BitvavoClient(api_key=config.api_key, api_secret=config.api_secret)
    market_ops = MarketOperations(client)
    
    # Example market to monitor
    market = 'BTC-EUR'
    
    # Basic market information
    print(f"\n=== {market} Market Info ===")
    market_info = market_ops.get_market_info(market)
    print(f"Market status: {market_info['status']}")
    print(f"Base precision: {market_info['pricePrecision']}")
    
    # Current order book
    print(f"\n=== {market} Order Book ===")
    book = market_ops.get_book(market, 5)  # Get top 5 orders
    print("\nTop 5 Bids:")
    for bid in book['bids']:
        print(f"Price: €{bid[0]}, Amount: {bid[1]}")
    print("\nTop 5 Asks:")
    for ask in book['asks']:
        print(f"Price: €{ask[0]}, Amount: {ask[1]}")
    
    # Get account balance if authenticated
    try:
        balances = market_ops.get_balance()
        print("\n=== Account Balances ===")
        for balance in balances:
            if float(balance['available']) > 0:  # Only show assets with balance
                print(f"{balance['symbol']}: {balance['available']} (In order: {balance['inOrder']})")
    except Exception as e:
        print("\nCouldn't get balance - probably using public API key")

if __name__ == "__main__":
    main()