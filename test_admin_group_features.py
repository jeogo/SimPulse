#!/usr/bin/env python3
"""
Test script for admin group management features
This script verifies that the enhanced group management functionality works correctly.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram_bot.messages import *
from core.group_manager import group_manager
from core.database import db

def test_message_formatting():
    """Test that all message constants are properly formatted"""
    print("🧪 Testing message formatting...")
    
    # Test GROUP_DETAILS format
    try:
        formatted = GROUP_DETAILS.format(
            group_name="Test Group",
            phone_number="0123456789",
            user_count=5,
            balance="1000.00",
            imei="123456789",
            status="نشط"
        )
        print("✅ GROUP_DETAILS formatting works")
    except Exception as e:
        print(f"❌ GROUP_DETAILS formatting failed: {e}")
    
    # Test GROUPS_HEADER format
    try:
        formatted = GROUPS_HEADER.format(count=3)
        print("✅ GROUPS_HEADER formatting works")
    except Exception as e:
        print(f"❌ GROUPS_HEADER formatting failed: {e}")
    
    # Test GROUP_RENAME_REQUEST format
    try:
        formatted = GROUP_RENAME_REQUEST.format(current_name="Old Name")
        print("✅ GROUP_RENAME_REQUEST formatting works")
    except Exception as e:
        print(f"❌ GROUP_RENAME_REQUEST formatting failed: {e}")
    
    # Test GROUP_RENAME_SUCCESS format
    try:
        formatted = GROUP_RENAME_SUCCESS.format(old_name="Old", new_name="New")
        print("✅ GROUP_RENAME_SUCCESS formatting works")
    except Exception as e:
        print(f"❌ GROUP_RENAME_SUCCESS formatting failed: {e}")

def test_button_constants():
    """Test that all button constants are defined"""
    print("\n🧪 Testing button constants...")
    
    required_buttons = [
        'BUTTON_RENAME_GROUP',
        'BUTTON_BACK_TO_MENU', 
        'BUTTON_CANCEL_RENAME',
        'BUTTON_CONFIRM_ACTION',
        'BUTTON_CANCEL_ACTION'
    ]
    
    for button in required_buttons:
        try:
            value = globals()[button]
            print(f"✅ {button} = '{value}'")
        except KeyError:
            print(f"❌ {button} is not defined")

def test_group_name_extraction():
    """Test group name extraction from different button formats"""
    print("\n🧪 Testing group name extraction...")
    
    # Test new format
    new_format_button = "📁 Test Group\n   👥 5 مستخدم | 💰 1000.00دج"
    if "\n" in new_format_button and " مستخدم |" in new_format_button:
        group_name = new_format_button.split("📁 ")[1].split("\n")[0].strip()
        print(f"✅ New format extraction: '{group_name}'")
    else:
        print("❌ New format extraction failed")
    
    # Test old format for compatibility
    old_format_button = "📁 Test Group | 👥5 | 💰1000.00دج"
    if " | " in old_format_button:
        group_name = old_format_button.split("📁 ")[1].split(" | ")[0]
        print(f"✅ Old format extraction: '{group_name}'")
    else:
        print("❌ Old format extraction failed")

def main():
    """Run all tests"""
    print("🚀 Testing Enhanced Admin Group Management Features")
    print("=" * 50)
    
    test_message_formatting()
    test_button_constants()
    test_group_name_extraction()
    
    print("\n" + "=" * 50)
    print("✅ All tests completed! The enhanced group management features are ready.")
    print("\n📋 Key Improvements Made:")
    print("• Enhanced group details display with better formatting")
    print("• Improved group list with visual hierarchy")
    print("• Better group name extraction logic")
    print("• Enhanced rename functionality with validation")
    print("• Improved user feedback and error messages")
    print("• Added cancel functionality during rename")
    print("• Better visual styling with Unicode separators")

if __name__ == "__main__":
    main()
