import asyncio
import websockets
import json
import requests
import time
from datetime import datetime
from typing import Dict, List, Optional

class TONWalletTracker:
    def __init__(self, wallet_address: str):
        self.wallet_address = wallet_address
        self.last_lt = None  # Last logical time to track new transactions
        self.processed_hashes = set()  # To avoid duplicate processing

        # TON API endpoints
        self.api_base = "https://toncenter.com/api/v2"
        self.websocket_url = "wss://tonapi.io/v2/websocket"

    def get_transactions_history(self, limit: int = 10) -> List[Dict]:
        """Get recent transactions for the wallet"""
        url = f"{self.api_base}/getTransactions"
        params = {
            "address": self.wallet_address,
            "limit": limit,
            "to_lt": 0,
            "archival": "true"
        }

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("ok"):
                return data.get("result", [])
            else:
                print(f"API Error: {data.get('error', 'Unknown error')}")
                return []

        except requests.RequestException as e:
            print(f"Request error: {e}")
            return []

    def format_transaction(self, tx: Dict) -> str:
        """Format transaction for display"""
        utime = tx.get("utime", 0)
        timestamp = datetime.fromtimestamp(utime).strftime("%Y-%m-%d %H:%M:%S")

        tx_hash = tx.get("transaction_id", {}).get("hash", "N/A")
        lt = tx.get("transaction_id", {}).get("lt", "N/A")

        # Extract transaction details
        in_msg = tx.get("in_msg", {})
        out_msgs = tx.get("out_msgs", [])

        # Format incoming message
        incoming_value = 0
        incoming_source = "N/A"
        if in_msg and in_msg.get("value"):
            incoming_value = int(in_msg.get("value", 0)) / 1e9  # Convert from nanotons to TON
            incoming_source = in_msg.get("source", "N/A")

        # Format outgoing messages
        outgoing_info = []
        for out_msg in out_msgs:
            if out_msg.get("value"):
                value = int(out_msg.get("value", 0)) / 1e9
                destination = out_msg.get("destination", "N/A")
                outgoing_info.append(f"  → {destination}: {value:.6f} TON")

        # Transaction fees
        total_fees = int(tx.get("total_fees", 0)) / 1e9

        result = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 Time: {timestamp}
🔗 Hash: {tx_hash}
📊 LT: {lt}
💰 Fees: {total_fees:.6f} TON
"""

        if incoming_value > 0:
            result += f"📥 INCOMING: {incoming_value:.6f} TON from {incoming_source}\n"

        if outgoing_info:
            result += "📤 OUTGOING:\n" + "\n".join(outgoing_info) + "\n"

        return result

    async def check_new_transactions(self):
        """Check for new transactions periodically"""
        print(f"🔍 Checking for new transactions on wallet: {self.wallet_address}")

        # Get initial transactions to set baseline
        initial_txs = self.get_transactions_history(limit=1)
        if initial_txs:
            self.last_lt = initial_txs[0].get("transaction_id", {}).get("lt")
            for tx in initial_txs:
                tx_hash = tx.get("transaction_id", {}).get("hash")
                if tx_hash:
                    self.processed_hashes.add(tx_hash)

        print(f"✅ Monitoring started. Last LT: {self.last_lt}")
        print("=" * 60)

        while True:
            try:
                # Get recent transactions
                transactions = self.get_transactions_history(limit=20)

                new_transactions = []
                for tx in transactions:
                    tx_hash = tx.get("transaction_id", {}).get("hash")
                    tx_lt = tx.get("transaction_id", {}).get("lt")

                    # Check if this is a new transaction
                    if (tx_hash and tx_hash not in self.processed_hashes and
                        (self.last_lt is None or int(tx_lt) > int(self.last_lt))):
                        new_transactions.append(tx)
                        self.processed_hashes.add(tx_hash)

                # Process new transactions (newest first)
                if new_transactions:
                    new_transactions.sort(key=lambda x: int(x.get("transaction_id", {}).get("lt", 0)))

                    for tx in new_transactions:
                        print("🚨 NEW TRANSACTION DETECTED!")
                        print(self.format_transaction(tx))

                        # Update last_lt
                        tx_lt = tx.get("transaction_id", {}).get("lt")
                        if tx_lt and (self.last_lt is None or int(tx_lt) > int(self.last_lt)):
                            self.last_lt = tx_lt

                # Wait before next check
                await asyncio.sleep(5)  # Check every 5 seconds

            except Exception as e:
                print(f"❌ Error checking transactions: {e}")
                await asyncio.sleep(10)  # Wait longer on error

    async def websocket_monitor(self):
        """Monitor transactions via websocket (alternative method)"""
        retry_count = 0
        max_retries = 3

        while retry_count < max_retries:
            try:
                print(f"🔌 Attempting websocket connection (attempt {retry_count + 1}/{max_retries})...")

                # Use a more reliable websocket endpoint
                ws_url = "wss://scaleton.io/ws"

                # Subscribe to account updates
                subscribe_message = {
                    "id": 1,
                    "jsonrpc": "2.0",
                    "method": "subscribe",
                    "params": {
                        "accounts": [self.wallet_address]
                    }
                }

                async with websockets.connect(
                    ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=10
                ) as websocket:
                    print("✅ Websocket connected!")

                    # Send subscription
                    await websocket.send(json.dumps(subscribe_message))
                    print("📡 Subscription sent")

                    # Listen for messages with timeout
                    try:
                        async for message in websocket:
                            try:
                                data = json.loads(message)
                                print(f"📨 Websocket message: {data}")

                                # Process websocket data here
                                if data.get("method") == "account_update":
                                    print("🔄 Account update received, checking for new transactions...")
                                    # Trigger a transaction check
                                    await self.check_single_update()

                            except json.JSONDecodeError as e:
                                print(f"❌ JSON decode error: {e}")

                    except websockets.exceptions.ConnectionClosed:
                        print("🔌 Websocket connection closed")
                        raise

            except Exception as e:
                print(f"❌ Websocket error: {e}")
                retry_count += 1
                if retry_count < max_retries:
                    print(f"🔄 Retrying in 5 seconds...")
                    await asyncio.sleep(5)
                else:
                    print("🔄 Max retries reached, falling back to polling method...")
                    raise

    async def check_single_update(self):
        """Check for new transactions once"""
        try:
            transactions = self.get_transactions_history(limit=5)

            new_transactions = []
            for tx in transactions:
                tx_hash = tx.get("transaction_id", {}).get("hash")
                tx_lt = tx.get("transaction_id", {}).get("lt")

                if (tx_hash and tx_hash not in self.processed_hashes and
                    (self.last_lt is None or int(tx_lt) > int(self.last_lt))):
                    new_transactions.append(tx)
                    self.processed_hashes.add(tx_hash)

            if new_transactions:
                new_transactions.sort(key=lambda x: int(x.get("transaction_id", {}).get("lt", 0)))

                for tx in new_transactions:
                    print("🚨 NEW TRANSACTION DETECTED!")
                    print(self.format_transaction(tx))

                    tx_lt = tx.get("transaction_id", {}).get("lt")
                    if tx_lt and (self.last_lt is None or int(tx_lt) > int(self.last_lt)):
                        self.last_lt = tx_lt

        except Exception as e:
            print(f"❌ Error in single update check: {e}")

    async def start_monitoring(self):
        """Start monitoring with improved fallback methods"""
        print("🚀 Starting TON Wallet Transaction Tracker")
        print(f"👛 Wallet: {self.wallet_address}")
        print("=" * 60)

        # Initialize with recent transactions
        print("🔄 Initializing with recent transactions...")
        await self.check_single_update()

        # Try websocket with shorter timeout, then use polling
        try:
            await asyncio.wait_for(self.websocket_monitor(), timeout=10)
        except (asyncio.TimeoutError, Exception) as e:
            if not isinstance(e, asyncio.TimeoutError):
                print(f"⚠️  Websocket failed: {e}")
            print("🔄 Using reliable polling method...")
            await self.check_new_transactions()

async def main():
    # The wallet address you provided
    wallet_address = "UQBfuEnLEUF8JEbXpknjmxGqeZsNR2CX9MIJfZVi99M1OCEF"

    # Create tracker instance
    tracker = TONWalletTracker(wallet_address)

    # Start monitoring
    try:
        await tracker.start_monitoring()
    except KeyboardInterrupt:
        print("\n👋 Monitoring stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    # Install required packages:
    # pip install websockets requests

    print("TON Wallet Transaction Tracker")
    print("Required packages: websockets, requests")
    print("Install with: pip install websockets requests")
    print()

    asyncio.run(main())
