import streamlit as st
import yfinance as yf
import pandas as pd

st.set_page_config(page_title="Stock Analyzer", layout="wide")

# --- Custom CSS ---
st.markdown("""
<style>
    /* Center the search bar */
    .search-container {
        display: flex;
        justify-content: center;
        margin-top: 2rem;
        margin-bottom: 2rem;
    }
    /* Pillar card styling */
    .pillar-card {
        border-radius: 8px;
        padding: 0.6rem;
        text-align: center;
        color: white;
        min-height: 70px;
    }
    .pillar-pass { background-color: #16a34a; }
    .pillar-fail { background-color: #dc2626; }
    .pillar-stable { background-color: #eab308; }
    .pillar-na   { background-color: #6b7280; }
    .pillar-card h3 { margin: 0 0 0.3rem 0; font-size: 0.75rem; }
    .pillar-card .value { font-size: 1.1rem; font-weight: 700; }
    .pillar-card .label { font-size: 0.65rem; opacity: 0.9; margin-top: 0.2rem; }
    /* Special styling for DNA tile */
    .pillar-card h3:has(+ .value:contains("🧬")) { font-size: 0.75rem; }
    .pillar-card .value { line-height: 1.3; }
    /* Badge */
    .badge {
        display: inline-block;
        padding: 0.5rem 1.5rem;
        border-radius: 999px;
        font-weight: 700;
        font-size: 1.1rem;
        color: white;
    }
    .badge-pass { background-color: #16a34a; }
    .badge-fail { background-color: #dc2626; }
</style>
""", unsafe_allow_html=True)

# --- Title ---
st.markdown("<h1 style='text-align:center;'>Stock Analyzer</h1>", unsafe_allow_html=True)
st.markdown(
    "<p style='text-align:center; color:gray;'>Enter a ticker to check if it's a Quality Compounder</p>",
    unsafe_allow_html=True,
)

# --- Search Bar ---
col_left, col_mid, col_right = st.columns([1, 2, 1])
with col_mid:
    ticker_input = st.text_input(
        "Search",
        placeholder="Enter a ticker like AAPL, MSFT, GOOG...",
        label_visibility="collapsed",
    )


@st.cache_data(ttl=600, show_spinner="Fetching data...")
def fetch_data(symbol: str):
    """Fetch all needed data from yfinance for a given ticker."""
    tk = yf.Ticker(symbol)
    info = tk.info
    if not info or info.get("quoteType") is None:
        return None, None, None
    financials = tk.financials  # annual income statement
    balance = tk.balance_sheet  # annual balance sheet
    return info, financials, balance


def safe_get(d, key, default=None):
    """Safely retrieve a value from a dict, returning default if missing or None."""
    if d is None:
        return default
    val = d.get(key)
    return val if val is not None else default


def compute_growth(financials: pd.DataFrame):
    """Compute year-over-year revenue growth rates from the income statement.

    Returns a list of (year_label, growth_rate) tuples, most recent first,
    and a boolean indicating whether growth is consistently > 10%.
    """
    if financials is None or financials.empty:
        return None, None
    revenue_row = None
    for label in ["Total Revenue", "Revenue"]:
        if label in financials.index:
            revenue_row = financials.loc[label]
            break
    if revenue_row is None:
        return None, None

    # Sort by date ascending
    revenue_row = revenue_row.dropna().sort_index()
    if len(revenue_row) < 2:
        return None, None

    growths = []
    values = revenue_row.values
    dates = revenue_row.index
    for i in range(1, len(values)):
        if values[i - 1] != 0:
            rate = (values[i] - values[i - 1]) / abs(values[i - 1])
            year_label = f"{dates[i - 1].year}-{dates[i].year}"
            growths.append((year_label, rate))

    if not growths:
        return None, None

    consistent = all(g >= 0.10 for _, g in growths)
    return growths, consistent


def compute_roic(info, financials, balance):
    """Calculate ROIC = EBIT * (1 - tax_rate) / (Equity + Debt).

    Tries to pull EBIT from financials and equity/debt from the balance sheet.
    Falls back to info dict fields when available.
    """
    # --- EBIT ---
    ebit = None
    if financials is not None and not financials.empty:
        for label in ["EBIT", "Operating Income"]:
            if label in financials.index:
                ebit = financials.loc[label].dropna()
                if not ebit.empty:
                    ebit = ebit.iloc[0]  # most recent year
                    break
                ebit = None
    if ebit is None:
        ebit = safe_get(info, "ebitda")  # rough fallback
        if ebit is not None:
            da = safe_get(info, "totalDepreciation", 0)
            ebit = ebit - da if da else ebit

    # --- Tax Rate ---
    tax_rate = None
    if financials is not None and not financials.empty:
        tax_provision = None
        pretax = None
        for label in ["Tax Provision", "Income Tax Expense"]:
            if label in financials.index:
                tax_provision = financials.loc[label].dropna()
                if not tax_provision.empty:
                    tax_provision = tax_provision.iloc[0]
                    break
                tax_provision = None
        for label in ["Pretax Income", "Income Before Tax"]:
            if label in financials.index:
                pretax = financials.loc[label].dropna()
                if not pretax.empty:
                    pretax = pretax.iloc[0]
                    break
                pretax = None
        if tax_provision is not None and pretax is not None and pretax != 0:
            tax_rate = tax_provision / pretax
    if tax_rate is None:
        tax_rate = 0.21  # default US corporate rate

    # --- Equity & Debt ---
    equity = None
    debt = None
    if balance is not None and not balance.empty:
        for label in [
            "Stockholders Equity",
            "Total Stockholder Equity",
            "Stockholders' Equity",
            "Total Equity Gross Minority Interest",
        ]:
            if label in balance.index:
                eq = balance.loc[label].dropna()
                if not eq.empty:
                    equity = eq.iloc[0]
                    break
        for label in ["Total Debt", "Long Term Debt", "Total Non Current Liabilities Net Minority Interest"]:
            if label in balance.index:
                d = balance.loc[label].dropna()
                if not d.empty:
                    debt = d.iloc[0]
                    break
    if equity is None:
        equity = safe_get(info, "bookValue")
        shares = safe_get(info, "sharesOutstanding")
        if equity is not None and shares is not None:
            equity = equity * shares
    if debt is None:
        debt = safe_get(info, "totalDebt", 0)

    if ebit is None or equity is None:
        return None
    invested = (equity or 0) + (debt or 0)
    if invested == 0:
        return None
    nopat = ebit * (1 - tax_rate)
    return nopat / invested


def compute_cagr(financials: pd.DataFrame):
    """Calculate CAGR from annual revenue data.

    Uses up to 5 years of data if available, otherwise uses max available years.
    Returns (cagr_rate, num_years) or (None, None) if insufficient data.
    """
    if financials is None or financials.empty:
        return None, None

    revenue_row = None
    for label in ["Total Revenue", "Revenue"]:
        if label in financials.index:
            revenue_row = financials.loc[label]
            break
    if revenue_row is None:
        return None, None

    # Sort by date ascending and get available years
    revenue_row = revenue_row.dropna().sort_index()
    if len(revenue_row) < 2:
        return None, None

    # Use up to 5 years, or max available
    years_available = len(revenue_row)
    start_value = revenue_row.iloc[0]
    end_value = revenue_row.iloc[-1]
    n = years_available - 1  # number of periods

    if start_value <= 0 or end_value <= 0:
        return None, None

    cagr = (end_value / start_value) ** (1 / n) - 1
    return cagr, n


def render_pillar(col, title, value_str, detail, passed, status_override=None):
    """Render a single pillar card.

    passed can be:
    - None: N/A (gray)
    - True: PASS (green)
    - False: FAIL (red)
    - "stable": Stable (yellow)
    """
    if status_override:
        css_class = status_override
        status = status_override.upper()
    elif passed is None:
        css_class = "pillar-na"
        status = "N/A"
    elif passed == "stable":
        css_class = "pillar-stable"
        status = "STABLE"
    elif passed:
        css_class = "pillar-pass"
        status = "PASS"
    else:
        css_class = "pillar-fail"
        status = "FAIL"
    with col:
        st.markdown(
            f"""
            <div class="pillar-card {css_class}">
                <h3>{title}</h3>
                <div class="value">{value_str}</div>
                <div class="label">{detail} · {status}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# --- Main Logic ---
if ticker_input:
    symbol = ticker_input.strip().upper()
    info, financials, balance = fetch_data(symbol)

    if info is None:
        st.error(f"Could not find data for ticker **{symbol}**. Please check the symbol and try again.")
    else:
        company_name = safe_get(info, "longName", symbol)
        st.markdown(
            f"<h1 style='text-align:center; font-size:2.5rem; font-weight:800; margin:1rem 0;'>"
            f"{company_name} <span style='color:#6b7280;'>({symbol})</span></h1>",
            unsafe_allow_html=True,
        )

        # --- 1. Quality (Net Profit Margin) ---
        margin = safe_get(info, "profitMargins")
        if margin is not None:
            margin_pct = margin * 100
            quality_str = f"{margin_pct:.1f}%"
            # 3-level: >20% green, 10-20% yellow, <10% red
            if margin_pct > 20:
                quality_status = "pillar-pass"
                quality_label = "Excellent Profitability"
                quality_pass = True
            elif margin_pct >= 10:
                quality_status = "pillar-stable"
                quality_label = "Good Profitability"
                quality_pass = "stable"
            else:
                quality_status = "pillar-fail"
                quality_label = "Poor Margins"
                quality_pass = False
        else:
            quality_str = "—"
            quality_pass = None
            quality_status = None
            quality_label = "N/A"

        # --- 2. Skin in the Game (Insider Holdings) ---
        insider = safe_get(info, "heldPercentInsiders")
        if insider is not None:
            insider_pct = insider * 100
            skin_str = f"{insider_pct:.1f}%"
            # 3-level: >5% green, 2-5% yellow, <2% red
            if insider_pct > 5:
                skin_status = "pillar-pass"
                skin_label = "Strong Ownership"
                skin_pass = True
            elif insider_pct >= 2:
                skin_status = "pillar-stable"
                skin_label = "Moderate Ownership"
                skin_pass = "stable"
            else:
                skin_status = "pillar-fail"
                skin_label = "Weak Ownership"
                skin_pass = False
        else:
            skin_str = "—"
            skin_pass = None
            skin_status = None
            skin_label = "N/A"

        # --- 3. No Debt (Cash vs Debt) ---
        total_cash = safe_get(info, "totalCash")
        total_debt = safe_get(info, "totalDebt")
        if total_cash is not None and total_debt is not None:
            cash_b = total_cash / 1e9
            debt_b = total_debt / 1e9
            no_debt_str = f"${cash_b:.1f}B vs ${debt_b:.1f}B"
            # 3-level: Cash > 1.5x Debt green, Cash > Debt yellow, Cash < Debt red
            if total_debt == 0 or (total_cash / total_debt) > 1.5:
                no_debt_status = "pillar-pass"
                no_debt_label = "Fortress Balance Sheet"
                no_debt_pass = True
            elif total_cash > total_debt:
                no_debt_status = "pillar-stable"
                no_debt_label = "Healthy Net Cash"
                no_debt_pass = "stable"
            else:
                no_debt_status = "pillar-fail"
                no_debt_label = "Net Debt Position"
                no_debt_pass = False
        else:
            no_debt_str = "—"
            no_debt_pass = None
            no_debt_status = None
            no_debt_label = "N/A"

        # --- 4. Growth (Revenue Growth YoY) ---
        growths, growth_consistent = compute_growth(financials)
        if growths is not None:
            latest_growth = growths[-1][1] * 100
            growth_str = f"{latest_growth:.1f}%"
            # 3-level: >15% green, 8-15% yellow, <8% red
            if latest_growth > 15:
                growth_status = "pillar-pass"
                growth_label = "High Growth"
                growth_pass = True
            elif latest_growth >= 8:
                growth_status = "pillar-stable"
                growth_label = "Moderate Growth"
                growth_pass = "stable"
            else:
                growth_status = "pillar-fail"
                growth_label = "Slow Growth"
                growth_pass = False
        else:
            # Fallback to info['revenueGrowth']
            rev_growth = safe_get(info, "revenueGrowth")
            if rev_growth is not None:
                rev_growth_pct = rev_growth * 100
                growth_str = f"{rev_growth_pct:.1f}%"
                if rev_growth_pct > 15:
                    growth_status = "pillar-pass"
                    growth_label = "High Growth"
                    growth_pass = True
                elif rev_growth_pct >= 8:
                    growth_status = "pillar-stable"
                    growth_label = "Moderate Growth"
                    growth_pass = "stable"
                else:
                    growth_status = "pillar-fail"
                    growth_label = "Slow Growth"
                    growth_pass = False
            else:
                growth_str = "—"
                growth_pass = None
                growth_status = None
                growth_label = "N/A"

        # --- 5. ROIC (Return on Invested Capital) ---
        roic = compute_roic(info, financials, balance)
        if roic is not None:
            roic_pct = roic * 100
            roic_str = f"{roic_pct:.1f}%"
            # 3-level: >20% green, 12-20% yellow, <12% red
            if roic_pct > 20:
                roic_status = "pillar-pass"
                roic_label = "Exceptional Returns"
                roic_pass = True
            elif roic_pct >= 12:
                roic_status = "pillar-stable"
                roic_label = "Good Returns"
                roic_pass = "stable"
            else:
                roic_status = "pillar-fail"
                roic_label = "Poor Returns"
                roic_pass = False
        else:
            roic_str = "—"
            roic_pass = None
            roic_status = None
            roic_label = "N/A"

        # --- 6. Earnings Growth (Quarterly) ---
        earnings_growth = safe_get(info, "earningsQuarterlyGrowth")
        if earnings_growth is not None:
            earnings_pct = earnings_growth * 100
            earnings_str = f"{earnings_pct:.1f}%"
            # Interpret: >15% excellent, 0-10% stable, <0 red
            if earnings_pct > 15:
                earnings_status = "pillar-pass"
                earnings_label = "Excellent · Growth Machine"
            elif earnings_pct >= 0:
                earnings_status = "pillar-stable"
                earnings_label = "Stable · Mature Company"
            else:
                earnings_status = "pillar-fail"
                earnings_label = "Watch Out · Losing Profitability"
        else:
            earnings_str = "—"
            earnings_status = None
            earnings_label = "N/A"

        # --- 7. CAGR (Compound Annual Growth Rate) ---
        cagr, cagr_years = compute_cagr(financials)
        if cagr is not None:
            cagr_pct = cagr * 100
            cagr_str = f"{cagr_pct:.1f}%"
            cagr_label = f"{cagr_years}Y CAGR"
            # Color coding: <5% red, 5-12% yellow, >12% green
            if cagr_pct > 12:
                cagr_status = "pillar-pass"
                cagr_pass = True
            elif cagr_pct >= 5:
                cagr_status = "pillar-stable"
                cagr_pass = "stable"
            else:
                cagr_status = "pillar-fail"
                cagr_pass = False
        else:
            cagr_str = "—"
            cagr_pass = None
            cagr_status = None
            cagr_label = "N/A"

        # --- 8. Stock DNA (Classification) ---
        # Fetch additional data for DNA classification
        pe_ratio = safe_get(info, "trailingPE")
        div_yield = safe_get(info, "dividendYield")

        dna_categories = []

        # Quality Compounder: ROIC > 18% AND Net Margin > 15%
        if roic is not None and margin is not None:
            roic_pct_val = roic * 100
            margin_pct_val = margin * 100
            if roic_pct_val > 18 and margin_pct_val > 15:
                dna_categories.append("Quality Compounder")

        # Aggressive Growth: Revenue Growth > 20% AND P/E > 35
        if pe_ratio is not None and pe_ratio > 35:
            # Check revenue growth
            rev_growth_val = None
            if growths is not None:
                rev_growth_val = growths[-1][1] * 100
            else:
                rev_g = safe_get(info, "revenueGrowth")
                if rev_g is not None:
                    rev_growth_val = rev_g * 100
            if rev_growth_val is not None and rev_growth_val > 20:
                dna_categories.append("Aggressive Growth")

        # Classic Value: P/E < 15 AND Net Margin > 8% AND P/E > 0
        if pe_ratio is not None and pe_ratio > 0 and pe_ratio < 15:
            if margin is not None and (margin * 100) > 8:
                dna_categories.append("Classic Value")

        # Income Play: Dividend Yield > 3%
        if div_yield is not None and (div_yield * 100) > 3:
            dna_categories.append("Income Play")

        # Cyclical/Mature: Revenue Growth 0-5% AND ROIC 8-12%
        rev_growth_for_cyclical = None
        if growths is not None:
            rev_growth_for_cyclical = growths[-1][1] * 100
        else:
            rev_g = safe_get(info, "revenueGrowth")
            if rev_g is not None:
                rev_growth_for_cyclical = rev_g * 100

        if rev_growth_for_cyclical is not None and roic is not None:
            roic_pct_val = roic * 100
            if 0 <= rev_growth_for_cyclical <= 5 and 8 <= roic_pct_val <= 12:
                dna_categories.append("Cyclical/Mature")

        # Speculative: Earnings Growth < 0 AND (P/E is N/A OR P/E > 50)
        if earnings_growth is not None and earnings_growth < 0:
            if pe_ratio is None or pe_ratio > 50:
                dna_categories.append("Speculative")

        # Determine final DNA label
        if len(dna_categories) == 0:
            dna_label = "Unclassified/Market Average"
            dna_str = "🧬 " + dna_label
            dna_status = "pillar-na"
        elif len(dna_categories) == 1:
            dna_label = dna_categories[0]
            dna_str = "🧬 " + dna_label
            # Color based on category
            if "Quality Compounder" in dna_label:
                dna_status = "pillar-pass"
            elif "Speculative" in dna_label:
                dna_status = "pillar-fail"
            elif "Income Play" in dna_label or "Classic Value" in dna_label:
                dna_status = "pillar-stable"
            else:
                dna_status = "pillar-stable"
        else:
            # Multiple categories - pick strongest or combine
            if "Quality Compounder" in dna_categories:
                dna_label = "Quality Compounder"
                dna_status = "pillar-pass"
            elif "Aggressive Growth" in dna_categories:
                dna_label = "Aggressive Growth"
                dna_status = "pillar-pass"
            else:
                dna_label = " + ".join(dna_categories[:2])  # Show top 2
                dna_status = "pillar-stable"
            dna_str = "🧬 " + dna_label

        # --- Summary Badge ---
        # Check if all metrics are green (pillar-pass)
        all_statuses = [quality_status, skin_status, no_debt_status, growth_status, roic_status, earnings_status, cagr_status]
        all_green = all(s == "pillar-pass" for s in all_statuses if s is not None)
        has_data = any(s is not None for s in all_statuses)

        if has_data and all_green:
            st.markdown(
                '<div style="text-align:center; margin-bottom:1.5rem;">'
                '<span class="badge badge-pass">Quality Compounder</span></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div style="text-align:center; margin-bottom:1.5rem;">'
                '<span class="badge badge-fail">Not a Compounder</span></div>',
                unsafe_allow_html=True,
            )

        # --- Pillar Cards ---
        # Row 1
        cols_row1 = st.columns(4)
        render_pillar(cols_row1[0], "Quality", quality_str, quality_label, None, status_override=quality_status)
        render_pillar(cols_row1[1], "Skin in the Game", skin_str, skin_label, None, status_override=skin_status)
        render_pillar(cols_row1[2], "No Debt", no_debt_str, no_debt_label, None, status_override=no_debt_status)
        render_pillar(cols_row1[3], "Growth", growth_str, growth_label, None, status_override=growth_status)

        st.markdown("<div style='margin: 0.8rem 0;'></div>", unsafe_allow_html=True)

        # Row 2
        cols_row2 = st.columns(4)
        render_pillar(cols_row2[0], "ROIC", roic_str, roic_label, None, status_override=roic_status)
        render_pillar(cols_row2[1], "Earnings Growth", earnings_str, earnings_label, None, status_override=earnings_status)
        render_pillar(cols_row2[2], "CAGR", cagr_str, cagr_label, None, status_override=cagr_status)
        render_pillar(cols_row2[3], "Stock DNA", dna_str, dna_label, None, status_override=dna_status)

        # --- Growth Detail Table ---
        if growths:
            st.markdown("### Revenue Growth History")
            growth_df = pd.DataFrame(growths, columns=["Period", "Growth Rate"])
            growth_df["Growth Rate"] = growth_df["Growth Rate"].apply(lambda x: f"{x * 100:.1f}%")
            st.dataframe(growth_df, use_container_width=True, hide_index=True)

        # --- Warnings for missing data ---
        missing = []
        if quality_status is None:
            missing.append("Net Profit Margin")
        if skin_status is None:
            missing.append("Insider Holdings")
        if no_debt_status is None:
            missing.append("Cash/Debt")
        if growth_status is None:
            missing.append("Revenue Growth")
        if roic_status is None:
            missing.append("ROIC")
        if earnings_status is None:
            missing.append("Earnings Growth")
        if cagr_status is None:
            missing.append("CAGR")
        if missing:
            st.warning(f"Data unavailable for: {', '.join(missing)}. These pillars could not be evaluated.")
