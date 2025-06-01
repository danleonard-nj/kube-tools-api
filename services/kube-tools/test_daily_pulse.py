#!/usr/bin/env python3
"""
Test script for Robinhood Daily Pulse functionality
"""

from data.sms_inbound_repository import InboundSMSRepository
from services.chat_gpt_service import ChatGptService
from services.robinhood_service import RobinhoodService
from framework.configuration import Configuration
import asyncio
import sys
import os

# Add the parent directory to the path to import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_daily_pulse():
    """Test the daily pulse generation"""
    print("Testing Robinhood Daily Pulse Generation...")

    try:
        # Mock configuration - replace with actual config loading
        config = Configuration.from_file('config.dev.json')

        # Mock dependencies - you would normally inject these properly
        # For testing purposes, we'll create mock objects
        mock_sms_repo = None  # Would need proper implementation
        mock_chat_service = None  # Would need proper implementation

        # Create service instance
        service = RobinhoodService(
            configuration=config,
            inbound_sms_repository=mock_sms_repo,
            chat_gpt_service=mock_chat_service
        )

        # Test the daily pulse generation
        result = await service.generate_daily_pulse()

        print(f"Result: {result}")

        if result.get('success'):
            print("✅ Daily pulse generated successfully!")
            print(f"Analysis: {result['data']['analysis'][:200]}...")
        else:
            print(f"❌ Failed to generate daily pulse: {result.get('error')}")

    except Exception as e:
        print(f"❌ Error during test: {str(e)}")

if __name__ == "__main__":
    # Note: This is a basic test script
    # In a real scenario, you would need proper dependency injection
    # and configuration setup
    print("Note: This test requires proper DI container setup")
    print("Use this as a reference for testing the implementation")
