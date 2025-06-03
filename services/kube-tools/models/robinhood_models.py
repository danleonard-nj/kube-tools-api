from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from datetime import date


class Holding(BaseModel):
    price: str
    quantity: str
    average_buy_price: str
    equity: Optional[str] = None
    percent_change: Optional[str] = None
    intraday_percent_change: Optional[str] = None
    equity_change: Optional[str] = None
    type: Optional[str] = None
    name: Optional[str] = None
    id: Optional[str] = None
    pe_ratio: Optional[str] = None
    percentage: Optional[str] = None


class Order(BaseModel):
    id: str
    symbol: Optional[str] = None
    ref_id: Optional[str] = None
    url: Optional[str] = None
    account: Optional[str] = None
    user_uuid: Optional[str] = None
    position: Optional[str] = None
    cancel: Optional[Any] = None
    instrument: Optional[Any] = None
    instrument_id: Optional[str] = None
    cumulative_quantity: Optional[str] = None
    average_price: Optional[str] = None
    fees: Optional[str] = None
    sec_fees: Optional[str] = None
    taf_fees: Optional[str] = None
    cat_fees: Optional[str] = None
    gst_fees: Optional[str] = None
    state: Optional[str] = None
    derived_state: Optional[str] = None
    pending_cancel_open_agent: Optional[Any] = None
    type: Optional[str] = None
    side: Optional[str] = None
    time_in_force: Optional[str] = None
    trigger: Optional[str] = None
    price: Optional[str] = None
    stop_price: Optional[str] = None
    quantity: Optional[str] = None
    reject_reason: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_transaction_at: Optional[str] = None
    executions: Optional[List[Any]] = None
    extended_hours: Optional[bool] = None
    market_hours: Optional[str] = None
    override_dtbp_checks: Optional[bool] = None
    override_day_trade_checks: Optional[bool] = None
    response_category: Optional[Any] = None
    stop_triggered_at: Optional[Any] = None
    last_trail_price: Optional[Any] = None
    last_trail_price_updated_at: Optional[Any] = None
    last_trail_price_source: Optional[Any] = None
    dollar_based_amount: Optional[dict] = None
    total_notional: Optional[dict] = None
    executed_notional: Optional[dict] = None
    investment_schedule_id: Optional[Any] = None
    is_ipo_access_order: Optional[bool] = None
    ipo_access_cancellation_reason: Optional[Any] = None
    ipo_access_lower_collared_price: Optional[Any] = None
    ipo_access_upper_collared_price: Optional[Any] = None
    ipo_access_upper_price: Optional[Any] = None
    ipo_access_lower_price: Optional[Any] = None
    is_ipo_access_price_finalized: Optional[bool] = None
    is_visible_to_user: Optional[bool] = None
    has_ipo_access_custom_price_limit: Optional[bool] = None
    is_primary_account: Optional[bool] = None
    order_form_version: Optional[int] = None
    preset_percent_limit: Optional[str] = None
    order_form_type: Optional[str] = None
    last_update_version: Optional[int] = None
    placed_agent: Optional[str] = None
    is_editable: Optional[bool] = None
    replaces: Optional[Any] = None
    user_cancel_request_state: Optional[str] = None
    tax_lot_selection_type: Optional[str] = None
    position_effect: Optional[str] = None


class PortfolioProfile(BaseModel):
    url: Optional[str] = None
    account: Optional[str] = None
    start_date: Optional[str] = None
    market_value: Optional[str] = None
    equity: Optional[str] = None
    extended_hours_market_value: Optional[str] = None
    extended_hours_equity: Optional[str] = None
    extended_hours_portfolio_equity: Optional[str] = None
    last_core_market_value: Optional[str] = None
    last_core_equity: Optional[str] = None
    last_core_portfolio_equity: Optional[str] = None
    excess_margin: Optional[str] = None
    excess_maintenance: Optional[str] = None
    excess_margin_with_uncleared_deposits: Optional[str] = None
    excess_maintenance_with_uncleared_deposits: Optional[str] = None
    equity_previous_close: Optional[str] = None
    portfolio_equity_previous_close: Optional[str] = None
    adjusted_equity_previous_close: Optional[str] = None
    adjusted_portfolio_equity_previous_close: Optional[str] = None
    withdrawable_amount: Optional[str] = None
    unwithdrawable_deposits: Optional[str] = None
    unwithdrawable_grants: Optional[str] = None
    is_primary_account: Optional[bool] = None


class AccountProfile(BaseModel):
    url: Optional[str] = None
    portfolio_cash: Optional[str] = None
    can_downgrade_to_cash: Optional[str] = None
    user: Optional[str] = None
    account_number: Optional[str] = None
    type: Optional[str] = None
    brokerage_account_type: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deactivated: Optional[bool] = None
    deposit_halted: Optional[bool] = None
    withdrawal_halted: Optional[bool] = None
    only_position_closing_trades: Optional[bool] = None
    buying_power: Optional[str] = None
    onbp: Optional[str] = None
    cash_available_for_withdrawal: Optional[str] = None
    cash_available_for_withdrawal_without_margin: Optional[str] = None
    cash: Optional[str] = None
    amount_eligible_for_deposit_cancellation: Optional[str] = None
    cash_held_for_orders: Optional[str] = None
    uncleared_deposits: Optional[str] = None
    sma: Optional[str] = None
    sma_held_for_orders: Optional[str] = None
    unsettled_funds: Optional[str] = None
    unsettled_debit: Optional[str] = None
    crypto_buying_power: Optional[str] = None
    max_ach_early_access_amount: Optional[str] = None
    cash_balances: Optional[Any] = None
    margin_balances: Optional[dict] = None
    sweep_enabled: Optional[bool] = None
    sweep_enrolled: Optional[bool] = None
    instant_eligibility: Optional[dict] = None
    option_level: Optional[str] = None
    is_pinnacle_account: Optional[bool] = None
    rhs_account_number: Optional[int] = None
    state: Optional[str] = None
    active_subscription_id: Optional[Any] = None
    locked: Optional[bool] = None
    permanently_deactivated: Optional[bool] = None
    ipo_access_restricted: Optional[bool] = None
    ipo_access_restricted_reason: Optional[Any] = None
    received_ach_debit_locked: Optional[bool] = None
    drip_enabled: Optional[bool] = None
    eligible_for_fractionals: Optional[bool] = None
    eligible_for_drip: Optional[bool] = None
    eligible_for_cash_management: Optional[bool] = None
    cash_management_enabled: Optional[bool] = None
    option_trading_on_expiration_enabled: Optional[bool] = None
    cash_held_for_options_collateral: Optional[str] = None
    fractional_position_closing_only: Optional[bool] = None
    user_id: Optional[str] = None
    equity_trading_lock: Optional[str] = None
    option_trading_lock: Optional[str] = None
    disable_adt: Optional[bool] = None
    management_type: Optional[str] = None
    dynamic_instant_limit: Optional[str] = None
    affiliate: Optional[str] = None
    second_trade_suitability_completed: Optional[bool] = None
    has_futures_account: Optional[bool] = None
    is_default: Optional[bool] = None
    car_valid_until: Optional[str] = None
    nickname: Optional[str] = None
    ref_id: Optional[str] = None


class PortfolioData(BaseModel):
    account_profile: AccountProfile
    portfolio_profile: PortfolioProfile
    holdings: Dict[str, Holding]
    positions: Any
    recent_orders: List[Order]
    watchlist: List[Any]
    historical_equity: Optional[List[Dict[str, Any]]] = None


class Article(BaseModel):
    title: str
    snippet: Optional[str] = None
    link: Optional[str] = None
    source: Optional[str] = None
    content: Optional[str] = None
    sector: Optional[str] = None


class MarketResearch(BaseModel):
    market_conditions: List[Article]
    stock_news: Dict[str, List[Article]]
    sector_analysis: List[Article]
    search_errors: List[str]


class DebugReport(BaseModel):
    portfolio_data: PortfolioData
    market_research: MarketResearch
    prompts: Dict[str, Any]
    gpt_analysis: str
    sources: Dict[str, Any]
