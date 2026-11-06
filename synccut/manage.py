import argparse
import sys
from synccut.api.db import get_db_connection # Adjust based on your db setup

def upgrade_user(email: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Find the user
    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    if not user:
        print(f" User {email} not found.")
        return

    user_id = user[0]

    # 2. Update or Insert Subscription
    cursor.execute("""
        INSERT INTO subscriptions (user_id, tier, expires_at)
        VALUES (%s, 'pro', NOW() + INTERVAL '30 days')
        ON CONFLICT (user_id) DO UPDATE 
        SET tier = 'pro', expires_at = NOW() + INTERVAL '30 days'
    """, (user_id,))
    
    conn.commit()
    cursor.close()
    conn.close()
    print(f" Successfully upgraded {email} to PRO for 30 days.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SyncCut Admin CLI")
    parser.add_argument("--upgrade", type=str, help="Email of the user to upgrade")
    args = parser.parse_args()

    if args.upgrade:
        upgrade_user(args.upgrade)
    else:
        print("Usage: python -m synccut.manage --upgrade user@example.com")