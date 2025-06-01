import pytest
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime

import services.robinhood_service as robinhood_service_mod
from domain.enums import BankKey, SyncType


@pytest.mark.asyncio
class TestRobinhoodService:

    @pytest.fixture(autouse=True)
    def setup(self):
        # Mock dependencies
        self.mock_config = MagicMock()
        self.mock_config.robinhood.get.side_effect = lambda key: {
            'username': 'test_user@example.com',
            'password': 'test_password'
        }.get(key)

        self.mock_sms_repo = AsyncMock()
        self.mock_chat_gpt_service = AsyncMock()
        self.mock_google_search_client = AsyncMock()
        self.mock_bank_service = AsyncMock()
        # Create service instance
        self.service = robinhood_service_mod.RobinhoodService(
            configuration=self.mock_config,
            inbound_sms_repository=self.mock_sms_repo,
            chat_gpt_service=self.mock_chat_gpt_service,
            google_search_client=self.mock_google_search_client,
            bank_service=self.mock_bank_service
        )

        # Add bank service dependency for testing sync functionality
        self.service._bank_service = self.mock_bank_service

    @patch('services.robinhood_service.r')
    async def test_login_success_without_mfa(self, mock_r):
        """Test successful login without MFA"""
        # Setup: mock r.login to succeed without raising exception
        mock_r.login.return_value = None

        # Execute
        result = await self.service.login()

        # Verify
        assert result['success'] is True
        assert result['mfa_required'] is False
        mock_r.login.assert_called_once_with(
            username='test_user@example.com',
            password='test_password'
        )

    @patch('services.robinhood_service.r')
    async def test_login_with_mfa_success(self, mock_r):
        """Test successful login with MFA"""
        # Setup: mock r.login to raise TwoFactorRequired first, then succeed
        mock_r.robinhood.exceptions.TwoFactorRequired = Exception
        mock_r.login.side_effect = [Exception("Two factor required"), None]

        # Mock SMS repository to return MFA token
        mock_message = MagicMock()
        mock_message.body = '123456'
        self.mock_sms_repo.get_messages.return_value = [mock_message]

        # Execute
        result = await self.service.login()

        # Verify
        assert result['success'] is True
        assert result['mfa_required'] is True
        assert mock_r.login.call_count == 2
        self.mock_sms_repo.get_messages.assert_awaited()

    @patch('services.robinhood_service.r')
    async def test_login_mfa_timeout(self, mock_r):
        """Test login fails when MFA token not received"""
        # Setup: mock r.login to raise TwoFactorRequired
        mock_r.robinhood.exceptions.TwoFactorRequired = Exception
        mock_r.login.side_effect = Exception("Two factor required")

        # Mock SMS repository to return no messages
        self.mock_sms_repo.get_messages.return_value = []

        # Execute
        result = await self.service.login()

        # Verify
        assert result['success'] is False
        assert result['mfa_required'] is True
        assert 'MFA token not received' in result['error']

    @patch('services.robinhood_service.r')
    async def test_get_portfolio_data_success(self, mock_r):
        """Test successful portfolio data retrieval"""
        # Setup: mock Robinhood API responses
        mock_r.profiles.load_account_profile.return_value = {
            'buying_power': '1000.00',
            'portfolio_cash': '500.00'
        }
        mock_r.profiles.load_portfolio_profile.return_value = {
            'total_return_today': '50.00',
            'total_equity': '5000.00'
        }
        mock_r.account.build_holdings.return_value = {
            'AAPL': {
                'quantity': '10',
                'average_buy_price': '150.00',
                'price': '155.00'
            }
        }
        mock_r.account.build_user_profile.return_value = {'user_id': 'test_user'}
        mock_r.orders.get_all_stock_orders.return_value = [
            {
                'side': 'buy',
                'quantity': '5',
                'price': '150.00',
                'state': 'filled',
                'symbol': 'AAPL'
            }
        ]
        mock_r.account.get_watchlist_by_name.return_value = ['AAPL', 'GOOGL']

        # Execute
        result = await self.service._get_portfolio_data()

        # Verify
        assert result['success'] is True
        assert 'data' in result
        portfolio_data = result['data']
        assert 'account_profile' in portfolio_data
        assert 'portfolio_profile' in portfolio_data
        assert 'holdings' in portfolio_data
        assert 'recent_orders' in portfolio_data
        assert 'watchlist' in portfolio_data

    @patch('services.robinhood_service.r')
    async def test_get_portfolio_data_orders_failure_graceful(self, mock_r):
        """Test portfolio data retrieval handles orders API failure gracefully"""
        # Setup: mock successful calls except orders
        mock_r.profiles.load_account_profile.return_value = {'buying_power': '1000.00'}
        mock_r.profiles.load_portfolio_profile.return_value = {'total_equity': '5000.00'}
        mock_r.account.build_holdings.return_value = {}
        mock_r.account.build_user_profile.return_value = {'user_id': 'test_user'}
        mock_r.orders.get_all_stock_orders.side_effect = Exception("API Error")
        mock_r.account.get_watchlist_by_name.return_value = []

        # Execute
        result = await self.service._get_portfolio_data()

        # Verify
        assert result['success'] is True
        assert result['data']['recent_orders'] == []  # Should fallback to empty list

    @patch('services.robinhood_service.r')
    async def test_get_portfolio_data_watchlist_failure_graceful(self, mock_r):
        """Test portfolio data retrieval handles watchlist API failure gracefully"""
        # Setup: mock successful calls except watchlist
        mock_r.profiles.load_account_profile.return_value = {'buying_power': '1000.00'}
        mock_r.profiles.load_portfolio_profile.return_value = {'total_equity': '5000.00'}
        mock_r.account.build_holdings.return_value = {}
        mock_r.account.build_user_profile.return_value = {'user_id': 'test_user'}
        mock_r.orders.get_all_stock_orders.return_value = []
        mock_r.account.get_watchlist_by_name.side_effect = Exception("API Error")

        # Execute
        result = await self.service._get_portfolio_data()

        # Verify
        assert result['success'] is True
        assert result['data']['watchlist'] == []  # Should fallback to empty list

    async def test_get_market_research_data_success(self):
        """Test successful market research data retrieval"""
        # Setup: mock Google search client responses
        self.mock_google_search_client.search_market_conditions.return_value = [
            {'title': 'Market Update', 'snippet': 'Market is up today'}
        ]
        self.mock_google_search_client.search_finance_news.return_value = [
            {'title': 'AAPL News', 'snippet': 'Apple announces new product'}
        ]
        self.mock_google_search_client.search_sector_analysis.return_value = [
            {'title': 'Tech Sector Analysis', 'snippet': 'Technology sector outlook'}
        ]

        portfolio_data = {
            'holdings': {'AAPL': {'quantity': '10'}}
        }

        # Execute
        result = await self.service._get_market_research_data(portfolio_data)

        # Verify
        assert 'market_conditions' in result
        assert 'stock_news' in result
        assert 'sector_analysis' in result
        assert len(result['market_conditions']) > 0
        assert 'AAPL' in result['stock_news']

    async def test_get_market_research_data_api_failures(self):
        """Test market research data retrieval handles API failures gracefully"""
        # Setup: mock Google search client to raise exceptions
        self.mock_google_search_client.search_market_conditions.side_effect = Exception("API Error")
        self.mock_google_search_client.search_finance_news.side_effect = Exception("API Error")
        self.mock_google_search_client.search_sector_analysis.side_effect = Exception("API Error")

        portfolio_data = {
            'holdings': {'AAPL': {'quantity': '10'}}
        }

        # Execute
        result = await self.service._get_market_research_data(portfolio_data)

        # Verify
        assert result['market_conditions'] == []
        assert result['stock_news'] == {}
        assert result['sector_analysis'] == []
        assert len(result['search_errors']) > 0

    def test_compile_daily_pulse_prompt(self):
        """Test daily pulse prompt compilation"""
        # Setup: mock portfolio data
        portfolio_data = {
            'portfolio_profile': {
                'total_return_today': '50.00',
                'total_equity': '5000.00'
            },
            'account_profile': {
                'buying_power': '1000.00'
            },
            'holdings': {
                'AAPL': {
                    'quantity': '10',
                    'average_buy_price': '150.00',
                    'price': '155.00',
                    'total_return_today_equity': '50.00',
                    'percentage': '3.33'
                }
            },
            'recent_orders': [
                {
                    'side': 'buy',
                    'quantity': '5',
                    'price': '150.00',
                    'state': 'filled',
                    'symbol': 'AAPL',
                    'created_at': '2024-01-01T10:00:00Z'
                }
            ]
        }

        market_research = {
            'market_conditions': [
                {'title': 'Market Update', 'snippet': 'Market is up today'}
            ]
        }

        # Execute
        result = self.service._compile_daily_pulse_prompt(portfolio_data, market_research)

        # Verify
        assert isinstance(result, str)
        assert 'PORTFOLIO OVERVIEW' in result
        assert 'CURRENT HOLDINGS' in result
        assert 'RECENT TRADING ACTIVITY' in result
        assert 'MARKET CONDITIONS' in result
        assert 'AAPL' in result

    def test_format_holdings_for_prompt(self):
        """Test holdings formatting for prompt"""
        holdings_summary = [
            {
                'symbol': 'AAPL',
                'quantity': '10',
                'average_buy_price': '150.00',
                'current_price': '155.00',
                'percentage_change': '3.33'
            }
        ]

        # Execute
        result = self.service._format_holdings_for_prompt(holdings_summary)

        # Verify
        assert 'AAPL: 10 shares' in result
        assert '$150.00' in result
        assert '$155.00' in result
        assert '3.33%' in result

    def test_format_holdings_for_prompt_empty(self):
        """Test holdings formatting with empty data"""
        # Execute
        result = self.service._format_holdings_for_prompt([])

        # Verify
        assert result == "No current holdings"

    def test_format_recent_activity_for_prompt(self):
        """Test recent activity formatting for prompt"""
        recent_activity = [
            {
                'side': 'buy',
                'quantity': '5',
                'instrument_symbol': 'AAPL',
                'price': '150.00',
                'state': 'filled'
            }
        ]

        # Execute
        result = self.service._format_recent_activity_for_prompt(recent_activity)

        # Verify
        assert 'BUY 5 AAPL' in result
        assert '$150.00' in result
        assert '(filled)' in result

    def test_format_recent_activity_for_prompt_empty(self):
        """Test recent activity formatting with empty data"""
        # Execute
        result = self.service._format_recent_activity_for_prompt([])

        # Verify
        assert result == "No recent trading activity"

    def test_format_market_research_for_prompt(self):
        """Test market research formatting for prompt"""
        market_research = {
            'market_conditions': [
                {
                    'title': 'Market Update Today',
                    'snippet': 'Markets showing positive momentum',
                    'source': 'Financial News'
                }
            ],
            'stock_news': {
                'AAPL': [
                    {
                        'title': 'Apple Announces New Product',
                        'snippet': 'Revolutionary new technology announced'
                    }
                ]
            },
            'sector_analysis': [
                {
                    'title': 'Technology Sector Outlook',
                    'snippet': 'Tech stocks continue to outperform',
                    'sector': 'technology'
                }
            ]
        }

        # Execute
        result = self.service._format_market_research_for_prompt(market_research)

        # Verify
        assert 'CURRENT MARKET CONDITIONS' in result
        assert 'Market Update Today' in result
        assert 'STOCK-SPECIFIC NEWS' in result
        assert 'AAPL News:' in result
        assert 'SECTOR ANALYSIS' in result
        assert 'Technology Sector Outlook' in result

    def test_format_market_research_for_prompt_empty(self):
        """Test market research formatting with empty data"""
        # Execute
        result = self.service._format_market_research_for_prompt(None)

        # Verify
        assert result == ""

    @patch('services.robinhood_service.r')
    async def test_get_account_info_success(self, mock_r):
        """Test successful account info retrieval"""
        # Setup
        mock_r.account.build_holdings.return_value = {
            'AAPL': {'quantity': '10', 'price': '155.00'}
        }

        # Execute
        result = await self.service.get_account_info()

        # Verify
        assert result['success'] is True
        assert 'data' in result

    @patch('services.robinhood_service.r')
    async def test_get_account_info_no_data(self, mock_r):
        """Test account info retrieval with no data"""
        # Setup
        mock_r.account.build_holdings.return_value = None

        # Execute
        result = await self.service.get_account_info()

        # Verify
        assert result['success'] is False
        assert 'No account information found' in result['error']

    @patch('services.robinhood_service.r')
    async def test_get_account_info_exception(self, mock_r):
        """Test account info retrieval with exception"""
        # Setup
        mock_r.account.build_holdings.side_effect = Exception("API Error")

        # Execute
        result = await self.service.get_account_info()

        # Verify
        assert result['success'] is False
        assert 'API Error' in result['error']

    @patch('services.robinhood_service.r')
    async def test_generate_daily_pulse_success(self, mock_r):
        """Test successful daily pulse generation"""
        # Setup: mock all dependencies
        mock_r.login.return_value = None
        mock_r.profiles.load_account_profile.return_value = {'buying_power': '1000.00'}
        mock_r.profiles.load_portfolio_profile.return_value = {'total_equity': '5000.00'}
        mock_r.account.build_holdings.return_value = {'AAPL': {'quantity': '10'}}
        mock_r.account.build_user_profile.return_value = {'user_id': 'test'}
        mock_r.orders.get_all_stock_orders.return_value = []
        mock_r.account.get_watchlist_by_name.return_value = []

        self.mock_google_search_client.search_market_conditions.return_value = []
        self.mock_chat_gpt_service.get_chat_completion.return_value = (
            "Daily pulse analysis", 100
        )

        # Execute
        result = await self.service.generate_daily_pulse()

        # Verify
        assert result['success'] is True
        assert 'data' in result
        assert 'analysis' in result['data']
        assert result['data']['analysis'] == "Daily pulse analysis"
        assert result['data']['token_usage'] == 100

    async def test_generate_daily_pulse_login_failure(self):
        """Test daily pulse generation with login failure"""
        # Setup: mock login to fail
        with patch.object(self.service, 'login') as mock_login:
            mock_login.return_value = {'success': False, 'error': 'Login failed'}

            # Execute
            result = await self.service.generate_daily_pulse()

            # Verify
            assert result['success'] is False
            assert 'Failed to login to Robinhood' in result['error']

    async def test_generate_daily_pulse_portfolio_data_failure(self):
        """Test daily pulse generation with portfolio data failure"""
        # Setup: mock login success but portfolio data failure
        with patch.object(self.service, 'login') as mock_login, \
                patch.object(self.service, '_get_portfolio_data') as mock_portfolio:

            mock_login.return_value = {'success': True}
            mock_portfolio.return_value = {'success': False, 'error': 'Portfolio error'}

            # Execute
            result = await self.service.generate_daily_pulse()

            # Verify
            assert result['success'] is False
            assert 'Failed to fetch portfolio data' in result['error']

    async def test_calculate_total_portfolio_value(self):
        """Test calculation of total portfolio value"""
        # Setup: mock portfolio data with holdings
        portfolio_data = {
            'holdings': {
                'AAPL': {
                    'quantity': '10',
                    'price': '155.00'
                },
                'GOOGL': {
                    'quantity': '5',
                    'price': '2800.00'
                }
            },
            'account_profile': {
                'portfolio_cash': '500.00'
            }
        }

        # Execute
        result = self.service.calculate_total_portfolio_value(portfolio_data)

        # Verify
        expected_value = (10 * 155.00) + (5 * 2800.00) + 500.00  # 1550 + 14000 + 500 = 16050
        assert result == expected_value

    async def test_calculate_total_portfolio_value_empty_holdings(self):
        """Test calculation with empty holdings"""
        # Setup: mock portfolio data with no holdings
        portfolio_data = {
            'holdings': {},
            'account_profile': {
                'portfolio_cash': '1000.00'
            }
        }

        # Execute
        result = self.service.calculate_total_portfolio_value(portfolio_data)

        # Verify
        assert result == 1000.00

    async def test_calculate_total_portfolio_value_missing_data(self):
        """Test calculation with missing data"""
        # Setup: mock portfolio data with missing fields
        portfolio_data = {
            'holdings': {
                'AAPL': {
                    'quantity': '10'
                    # Missing 'price'
                }
            },
            'account_profile': {}
        }

        # Execute
        result = self.service.calculate_total_portfolio_value(portfolio_data)

        # Verify - should handle missing data gracefully
        assert result == 0.0

    @patch('services.robinhood_service.r')
    async def test_sync_portfolio_balance_success(self, mock_r):
        """Test successful portfolio balance sync with bank service"""
        # Setup: mock successful login and portfolio data
        mock_r.login.return_value = None
        mock_r.profiles.load_account_profile.return_value = {'portfolio_cash': '500.00'}
        mock_r.profiles.load_portfolio_profile.return_value = {'total_equity': '5000.00'}
        mock_r.account.build_holdings.return_value = {
            'AAPL': {'quantity': '10', 'price': '155.00'}
        }
        mock_r.account.build_user_profile.return_value = {'user_id': 'test'}
        mock_r.orders.get_all_stock_orders.return_value = []
        mock_r.account.get_watchlist_by_name.return_value = []

        # Mock bank service capture_balance
        mock_balance = MagicMock()
        mock_balance.balance = 2050.00
        mock_balance.bank_key = 'robinhood'
        self.mock_bank_service.capture_balance.return_value = mock_balance

        # Execute
        result = await self.service.sync_portfolio_balance()

        # Verify
        assert result['success'] is True
        assert 'balance_captured' in result['data']

        # Verify bank service was called with correct parameters
        self.mock_bank_service.capture_balance.assert_awaited_once_with(
            bank_key='robinhood',
            balance=2050.00,  # 10 * 155.00 + 500.00
            tokens=0,
            message_bk=None,
            sync_type=SyncType.Robinhood
        )

    async def test_sync_portfolio_balance_login_failure(self):
        """Test portfolio balance sync with login failure"""
        # Setup: mock login failure
        with patch.object(self.service, 'login') as mock_login:
            mock_login.return_value = {'success': False, 'error': 'Login failed'}

            # Execute
            result = await self.service.sync_portfolio_balance()

            # Verify
            assert result['success'] is False
            assert 'Failed to login to Robinhood' in result['error']
            self.mock_bank_service.capture_balance.assert_not_awaited()

    async def test_sync_portfolio_balance_portfolio_data_failure(self):
        """Test portfolio balance sync with portfolio data failure"""
        # Setup: mock login success but portfolio data failure
        with patch.object(self.service, 'login') as mock_login, \
                patch.object(self.service, '_get_portfolio_data') as mock_portfolio:

            mock_login.return_value = {'success': True}
            mock_portfolio.return_value = {'success': False, 'error': 'Portfolio error'}

            # Execute
            result = await self.service.sync_portfolio_balance()

            # Verify
            assert result['success'] is False
            assert 'Failed to fetch portfolio data' in result['error']
            self.mock_bank_service.capture_balance.assert_not_awaited()

    async def test_sync_portfolio_balance_bank_service_failure(self):
        """Test portfolio balance sync with bank service failure"""
        # Setup: mock successful data retrieval but bank service failure
        with patch.object(self.service, 'login') as mock_login, \
                patch.object(self.service, '_get_portfolio_data') as mock_portfolio, \
                patch.object(self.service, 'calculate_total_portfolio_value') as mock_calc:

            mock_login.return_value = {'success': True}
            mock_portfolio.return_value = {
                'success': True,
                'data': {'holdings': {}, 'account_profile': {}}
            }
            mock_calc.return_value = 1000.00

            self.mock_bank_service.capture_balance.side_effect = Exception("Bank service error")

            # Execute
            result = await self.service.sync_portfolio_balance()

            # Verify
            assert result['success'] is False
            assert 'Bank service error' in result['error']

    async def test_order_symbol_extraction_from_instrument_data(self):
        """Test order symbol extraction when symbol not directly available"""
        # Setup: test order data processing
        orders = [
            {
                'side': 'buy',
                'quantity': '5',
                'price': '150.00',
                'state': 'filled',
                'instrument': {
                    'symbol': 'AAPL'
                }
                # No direct 'symbol' field
            }
        ]

        portfolio_data = {
            'portfolio_profile': {'total_return_today': '50.00'},
            'account_profile': {'buying_power': '1000.00'},
            'holdings': {},
            'recent_orders': orders
        }

        # Execute
        result = self.service._compile_daily_pulse_prompt(portfolio_data)

        # Verify that the symbol was extracted correctly
        assert 'AAPL' in result

    async def test_integration_full_daily_pulse_workflow(self):
        """Integration test for complete daily pulse workflow"""
        # This test covers the full workflow from login to pulse generation
        with patch('services.robinhood_service.r') as mock_r:
            # Setup comprehensive mocks
            mock_r.login.return_value = None
            mock_r.profiles.load_account_profile.return_value = {
                'buying_power': '1000.00',
                'portfolio_cash': '500.00'
            }
            mock_r.profiles.load_portfolio_profile.return_value = {
                'total_return_today': '50.00',
                'total_equity': '5000.00'
            }
            mock_r.account.build_holdings.return_value = {
                'AAPL': {
                    'quantity': '10',
                    'average_buy_price': '150.00',
                    'price': '155.00',
                    'total_return_today_equity': '50.00',
                    'percentage': '3.33'
                }
            }
            mock_r.account.build_user_profile.return_value = {'user_id': 'test_user'}
            mock_r.orders.get_all_stock_orders.return_value = [
                {
                    'side': 'buy',
                    'quantity': '5',
                    'price': '150.00',
                    'state': 'filled',
                    'symbol': 'AAPL',
                    'created_at': '2024-01-01T10:00:00Z'
                }
            ]
            mock_r.account.get_watchlist_by_name.return_value = ['AAPL', 'GOOGL']

            # Mock market research
            self.mock_google_search_client.search_market_conditions.return_value = [
                {'title': 'Market Update', 'snippet': 'Market is up today'}
            ]
            self.mock_google_search_client.search_finance_news.return_value = [
                {'title': 'AAPL News', 'snippet': 'Apple announces new product'}
            ]
            self.mock_google_search_client.search_sector_analysis.return_value = [
                {'title': 'Tech Analysis', 'snippet': 'Technology sector outlook'}
            ]

            # Mock ChatGPT response
            self.mock_chat_gpt_service.get_chat_completion.return_value = (
                "Comprehensive daily pulse analysis with market insights", 150
            )

            # Execute
            result = await self.service.generate_daily_pulse()

            # Verify comprehensive workflow
            assert result['success'] is True
            assert 'data' in result
            assert 'analysis' in result['data']
            assert 'portfolio_summary' in result['data']
            assert 'token_usage' in result['data']
            assert 'generated_at' in result['data']

            # Verify all API calls were made
            mock_r.login.assert_called_once()
            mock_r.profiles.load_account_profile.assert_called_once()
            mock_r.profiles.load_portfolio_profile.assert_called_once()
            mock_r.account.build_holdings.assert_called_once()
            mock_r.orders.get_all_stock_orders.assert_called_once()

            self.mock_google_search_client.search_market_conditions.assert_awaited_once()
            self.mock_google_search_client.search_finance_news.assert_awaited()
            self.mock_chat_gpt_service.get_chat_completion.assert_awaited_once()

    async def test_integration_portfolio_balance_sync_workflow(self):
        """Integration test for complete portfolio balance sync workflow"""
        with patch('services.robinhood_service.r') as mock_r:
            # Setup mocks for successful portfolio data retrieval
            mock_r.login.return_value = None
            mock_r.profiles.load_account_profile.return_value = {'portfolio_cash': '500.00'}
            mock_r.profiles.load_portfolio_profile.return_value = {'total_equity': '5000.00'}
            mock_r.account.build_holdings.return_value = {
                'AAPL': {'quantity': '10', 'price': '155.00'},
                'GOOGL': {'quantity': '2', 'price': '2800.00'}
            }
            mock_r.account.build_user_profile.return_value = {'user_id': 'test'}
            mock_r.orders.get_all_stock_orders.return_value = []
            mock_r.account.get_watchlist_by_name.return_value = []

            # Mock bank service
            mock_balance = MagicMock()
            mock_balance.balance = 7150.00  # 1550 + 5600 + 500
            mock_balance.bank_key = 'robinhood'
            self.mock_bank_service.capture_balance.return_value = mock_balance

            # Execute
            result = await self.service.sync_portfolio_balance()

            # Verify
            assert result['success'] is True
            assert result['data']['total_portfolio_value'] == 7150.00
            assert result['data']['balance_captured'].balance == 7150.00

            # Verify bank service integration
            self.mock_bank_service.capture_balance.assert_awaited_once_with(
                bank_key='robinhood',
                balance=7150.00,
                tokens=0,
                message_bk=None,
                sync_type=SyncType.Robinhood
            )
