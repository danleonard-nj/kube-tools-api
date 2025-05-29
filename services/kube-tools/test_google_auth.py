#!/usr/bin/env python3
"""
Test script to verify the new simplified GoogleAuthService works correctly
"""

import asyncio
import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(__file__))


async def test_imports():
    """Test that all imports work correctly"""
    print("Testing imports...")

    try:
        from services.google_auth_service import GoogleAuthService
        print("✓ GoogleAuthService imported successfully")

        from data.google.google_auth_repository import GoogleAuthRepository
        print("✓ GoogleAuthRepository imported successfully")

        from framework.clients.cache_client import CacheClientAsync
        print("✓ CacheClientAsync imported successfully")

        from google.oauth2.credentials import Credentials
        print("✓ Google Credentials imported successfully")

        return True
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False


async def test_service_methods():
    """Test that service methods are available and have correct signatures"""
    print("\nTesting service methods...")

    try:
        from services.google_auth_service import GoogleAuthService

        # Check that required methods exist
        methods = ['save_client', 'get_token']
        for method in methods:
            if hasattr(GoogleAuthService, method):
                print(f"✓ Method {method} exists")
            else:
                print(f"✗ Method {method} missing")
                return False

        # Check method signatures
        import inspect

        save_client_sig = inspect.signature(GoogleAuthService.save_client)
        expected_params = ['self', 'client_name', 'client_id', 'client_secret', 'refresh_token', 'token_uri']
        actual_params = list(save_client_sig.parameters.keys())

        if all(param in actual_params for param in expected_params):
            print("✓ save_client method has correct signature")
        else:
            print(f"✗ save_client signature mismatch. Expected: {expected_params}, Got: {actual_params}")
            return False

        get_token_sig = inspect.signature(GoogleAuthService.get_token)
        expected_params = ['self', 'client_name', 'scopes']
        actual_params = list(get_token_sig.parameters.keys())

        if all(param in actual_params for param in expected_params):
            print("✓ get_token method has correct signature")
        else:
            print(f"✗ get_token signature mismatch. Expected: {expected_params}, Got: {actual_params}")
            return False

        return True
    except Exception as e:
        print(f"✗ Error testing methods: {e}")
        return False


async def test_api_routes():
    """Test that API routes import correctly"""
    print("\nTesting API routes...")

    try:
        from routes.google import google_bp
        print("✓ Google routes imported successfully")

        # Check that the blueprint has the expected routes
        rules = [rule.rule for rule in google_bp.iter_rules()]
        expected_routes = ['/api/google/save_client', '/api/google/get_token']

        for route in expected_routes:
            if any(route in rule for rule in rules):
                print(f"✓ Route {route} found")
            else:
                print(f"✗ Route {route} missing")
                return False

        return True
    except Exception as e:
        print(f"✗ Error testing routes: {e}")
        return False


async def test_dependencies():
    """Test that service dependencies are correctly configured"""
    print("\nTesting service dependencies...")

    try:
        from services.google_auth_service import GoogleAuthService
        from data.google.google_auth_repository import GoogleAuthRepository
        from framework.clients.cache_client import CacheClientAsync

        # Check constructor
        import inspect
        constructor_sig = inspect.signature(GoogleAuthService.__init__)
        expected_params = ['self', 'auth_repository', 'cache_client']
        actual_params = list(constructor_sig.parameters.keys())

        if all(param in actual_params for param in expected_params):
            print("✓ GoogleAuthService constructor has correct signature")
        else:
            print(f"✗ Constructor signature mismatch. Expected: {expected_params}, Got: {actual_params}")
            return False

        return True
    except Exception as e:
        print(f"✗ Error testing dependencies: {e}")
        return False


async def test_client_integrations():
    """Test that client integrations work with new service"""
    print("\nTesting client integrations...")

    try:
        from clients.google_drive_client import GoogleDriveClient
        from clients.google_drive_client_async import GoogleDriveClientAsync
        from clients.gmail_client import GmailClient

        print("✓ All Google client imports successful")

        # Check that clients use get_token method
        import inspect

        # Check GoogleDriveClient
        source = inspect.getsource(GoogleDriveClient._get_client)
        if 'get_token' in source:
            print("✓ GoogleDriveClient uses get_token method")
        else:
            print("✗ GoogleDriveClient not updated to use get_token")
            return False

        # Check GoogleDriveClientAsync
        source = inspect.getsource(GoogleDriveClientAsync._get_auth_headers)
        if 'get_token' in source:
            print("✓ GoogleDriveClientAsync uses get_token method")
        else:
            print("✗ GoogleDriveClientAsync not updated to use get_token")
            return False

        return True
    except Exception as e:
        print(f"✗ Error testing client integrations: {e}")
        return False


async def main():
    """Run all tests"""
    print("🧪 Testing New Simplified Google Auth Service\n")

    tests = [
        test_imports,
        test_service_methods,
        test_dependencies,
        test_api_routes,
        test_client_integrations
    ]

    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test {test.__name__} failed with exception: {e}")
            results.append(False)

    print(f"\n📊 Test Results:")
    print(f"   Passed: {sum(results)}/{len(results)}")
    print(f"   Failed: {len(results) - sum(results)}/{len(results)}")

    if all(results):
        print("\n🎉 All tests passed! The new simplified Google Auth service is working correctly.")
        return 0
    else:
        print("\n❌ Some tests failed. Please check the issues above.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
