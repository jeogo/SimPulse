#!/usr/bin/env python3
"""
SimPulse Test Data Generator
Creates fake data for testing the verification system
"""

import sys
import os
from datetime import datetime, timedelta
import random

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db

def create_test_data():
    """Create comprehensive test data for verification testing"""
    
    print("🚀 Starting SimPulse Test Data Creation...")
    
    # Test configurations
    test_amounts = [1000, 500, 2000]  # Three test amounts
    test_phone = "0123456789"
    test_imei = "TEST123456789IMEI"
    
    try:
        # 1. Create test modem
        print("📱 Creating test modem...")
        modem_id = db.add_modem(test_imei)
        print(f"✅ Created modem with ID: {modem_id}")
        
        # 2. Create test SIM
        print("📞 Creating test SIM...")
        sim_id = db.add_sim(modem_id, test_phone, "1000.00")
        print(f"✅ Created SIM with ID: {sim_id}")
        
        # 3. Create test group
        print("📁 Creating test group...")
        from core.group_manager import group_manager
        group_id = group_manager.auto_create_group_for_modem(modem_id, test_imei)
        print(f"✅ Created group with ID: {group_id}")
        
        # 4. Create test telegram user
        print("👤 Creating test telegram user...")
        test_telegram_id = 123456789  # Fake telegram ID
        user_id = db.add_telegram_user(test_telegram_id, "Test User", test_phone)
        
        # Approve the user and assign to group
        db.update_telegram_user_status(test_telegram_id, 'approved', group_id)
        print(f"✅ Created and approved telegram user with ID: {user_id}")
        
        # 5. Create test SMS messages for each scenario
        print("📨 Creating test SMS messages...")
        
        base_time = datetime.now()
        
        # Scenario 1: Valid recharge SMS (1000 DZD)
        valid_sms_time = base_time - timedelta(minutes=30)
        valid_sms = f"Vous avez rechargé votre solde avec succès. Montant: 1000.00 DZD. Nouveau solde: 2000.00 DZD le {valid_sms_time.strftime('%d/%m/%Y')} {valid_sms_time.strftime('%H:%M:%S')}."
        
        db.add_sms(sim_id, "7711198105108105115", valid_sms, valid_sms_time)
        print(f"✅ Created VALID recharge SMS for 1000 DZD at {valid_sms_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Scenario 2: SCB/Activated balance SMS (500 DZD) - Should be rejected
        scb_sms_time = base_time - timedelta(minutes=45)
        scb_sms = f"Cher Mr/Mrs, votre solde SCB Sama Mix de 500.00 DZD est ajoutée à votre compte et est valable jusqu'au {(scb_sms_time + timedelta(days=30)).strftime('%d/%m/%Y')}. Pour plus d'informations contactez le service client."
        
        db.add_sms(sim_id, "7711198105108105115", scb_sms, scb_sms_time)
        print(f"✅ Created SCB/Sama Mix SMS for 500 DZD at {scb_sms_time.strftime('%Y-%m-%d %H:%M:%S')} (Should be REJECTED)")
        
        # Scenario 3: Another valid recharge SMS (2000 DZD)
        valid_sms_time2 = base_time - timedelta(minutes=60)
        valid_sms2 = f"Vous avez rechargé votre solde avec succès. Montant: 2000.00 DZD. Nouveau solde: 3000.00 DZD le {valid_sms_time2.strftime('%d/%m/%Y')} {valid_sms_time2.strftime('%H:%M:%S')}."
        
        db.add_sms(sim_id, "7711198105108105115", valid_sms2, valid_sms_time2)
        print(f"✅ Created VALID recharge SMS for 2000 DZD at {valid_sms_time2.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Scenario 4: Bonus SMS (should be rejected)
        bonus_sms_time = base_time - timedelta(minutes=15)
        bonus_sms = f"Félicitations! Vous avez reçu un Bonus de 100.00 DZD valable jusqu'au {(bonus_sms_time + timedelta(days=7)).strftime('%d/%m/%Y')}. Merci pour votre fidélité."
        
        db.add_sms(sim_id, "7711198105108105115", bonus_sms, bonus_sms_time)
        print(f"✅ Created BONUS SMS for 100 DZD at {bonus_sms_time.strftime('%Y-%m-%d %H:%M:%S')} (Should be REJECTED)")
        
        # 6. Print test instructions
        print("\n" + "="*80)
        print("🎯 TEST DATA CREATED SUCCESSFULLY!")
        print("="*80)
        print(f"📱 Test Phone Number: {test_phone}")
        print(f"👤 Test Telegram ID: {test_telegram_id}")
        print(f"📁 Test Group ID: {group_id}")
        print(f"🆔 Test SIM ID: {sim_id}")
        print("\n📋 TEST SCENARIOS:")
        print(f"1️⃣  VALID RECHARGE: 1000 DZD at {valid_sms_time.strftime('%Y-%m-%d %H:%M')} ✅ Should SUCCEED")
        print(f"2️⃣  SCB/SAMA MIX: 500 DZD at {scb_sms_time.strftime('%Y-%m-%d %H:%M')} ❌ Should be REJECTED")
        print(f"3️⃣  VALID RECHARGE: 2000 DZD at {valid_sms_time2.strftime('%Y-%m-%d %H:%M')} ✅ Should SUCCEED")
        print(f"4️⃣  BONUS MESSAGE: 100 DZD at {bonus_sms_time.strftime('%Y-%m-%d %H:%M')} ❌ Should be REJECTED")
        
        print("\n🧪 HOW TO TEST:")
        print("1. Start the bot")
        print("2. Use /start command with the test telegram ID")
        print("3. Try 'التحقق من الرصيد' with these test cases:")
        print(f"   • Amount: 1000, Date: {valid_sms_time.strftime('%Y-%m-%d')}, Time: {valid_sms_time.strftime('%H:%M')} → Should SUCCEED")
        print(f"   • Amount: 500, Date: {scb_sms_time.strftime('%Y-%m-%d')}, Time: {scb_sms_time.strftime('%H:%M')} → Should be REJECTED (SCB)")
        print(f"   • Amount: 2000, Date: {valid_sms_time2.strftime('%Y-%m-%d')}, Time: {valid_sms_time2.strftime('%H:%M')} → Should SUCCEED")
        print(f"   • Amount: 100, Date: {bonus_sms_time.strftime('%Y-%m-%d')}, Time: {bonus_sms_time.strftime('%H:%M')} → Should be REJECTED (Bonus)")
        print(f"   • Amount: 999, Date: {valid_sms_time.strftime('%Y-%m-%d')}, Time: {valid_sms_time.strftime('%H:%M')} → Should FAIL (No match)")
        
        print("\n💡 Test different time margins by using times ±3 minutes from the SMS times.")
        print("="*80)
        
    except Exception as e:
        print(f"❌ Error creating test data: {e}")
        return False
        
    return True

def cleanup_test_data():
    """Clean up existing test data"""
    print("🧹 Cleaning up existing test data...")
    
    try:
        # Delete test SMS
        with db.get_connection() as conn:
            conn.execute("DELETE FROM sms WHERE sim_id IN (SELECT id FROM sims WHERE phone_number = '0123456789')")
            
            # Delete test verifications
            conn.execute("DELETE FROM balance_verifications WHERE telegram_user_id IN (SELECT id FROM telegram_users WHERE telegram_id = 123456789)")
            
            # Delete test telegram user
            conn.execute("DELETE FROM telegram_users WHERE telegram_id = 123456789")
            
            # Delete test groups
            conn.execute("DELETE FROM groups WHERE modem_id IN (SELECT id FROM modems WHERE imei = 'TEST123456789IMEI')")
            
            # Delete test SIMs
            conn.execute("DELETE FROM sims WHERE modem_id IN (SELECT id FROM modems WHERE imei = 'TEST123456789IMEI')")
            
            # Delete test modem
            conn.execute("DELETE FROM modems WHERE imei = 'TEST123456789IMEI'")
            
            conn.commit()
            
        print("✅ Test data cleaned up successfully!")
        
    except Exception as e:
        print(f"❌ Error cleaning up test data: {e}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='SimPulse Test Data Generator')
    parser.add_argument('--cleanup', action='store_true', help='Clean up existing test data')
    parser.add_argument('--create', action='store_true', help='Create new test data')
    
    args = parser.parse_args()
    
    if args.cleanup:
        cleanup_test_data()
    elif args.create:
        cleanup_test_data()  # Clean first
        create_test_data()
    else:
        # Default: clean and create
        cleanup_test_data()
        create_test_data()
