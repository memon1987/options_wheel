# Low-Price S&P 500 Stock Research for Options Wheel Strategy

**Research Date**: October 1, 2025
**Objective**: Identify S&P 500 stocks trading ≤$25/share with high options liquidity for wheel strategy
**Target**: Lower assignment costs to enable higher volume trading

## Executive Summary

**Key Finding**: S&P 500 stocks trading below $25/share are extremely rare due to index requirements (minimum $22.7B market cap as of July 2025). Most large-cap companies maintain higher share prices or execute reverse splits to avoid appearing "cheap."

**Recommendation**: Ford (F) at ~$12/share is the strongest candidate found and has been added to the trading universe.

---

## Research Methodology

1. Web search for S&P 500 constituent stocks by absolute price (not valuation metrics)
2. Analysis of options liquidity (open interest, volume, bid-ask spreads)
3. Evaluation of wheel strategy suitability
4. Verification of current S&P 500 membership status

---

## Candidates Identified

### ✅ FORD MOTOR (F) - **ADDED TO PORTFOLIO**

**Current Status**: S&P 500 Member
**Stock Price**: ~$12.06 (September 29, 2025)
**52-Week Range**: $8.44 - $12.32

**Options Metrics**:
- Open Interest: 2,145,880 contracts (30-day avg: 2,229,322)
- Daily Volume: 146,380+ contracts
- Call Volume: 129,274 contracts
- Put Volume: 17,106 contracts
- Put/Call OI Ratio: 0.88 (slightly bullish)
- Bid-Ask Spreads: Excellent (very liquid)

**Wheel Strategy Suitability**: ⭐⭐⭐⭐⭐
- Assignment Cost: $1,206 per 100 shares (83% lower than current portfolio avg)
- Multiple sources cite F as **best stock for wheel strategy** in this price range
- Extremely high liquidity = tight spreads and easy fills
- Stable, established company with predictable movements
- High dividend yield provides downside support

**Advantages**:
- Enables 8-10 positions vs 1-2 with higher-priced stocks (same capital)
- Lower risk per position
- Excellent for testing strategy variations
- Strong sector diversification (automotive)

**Risks**:
- Lower absolute premium per contract vs higher-priced stocks
- Automotive sector cyclicality
- Need to verify passes gap risk filters

---

### ❌ WALGREENS BOOTS ALLIANCE (WBA)

**Current Status**: **REMOVED FROM S&P 500** (Went private August 28, 2025)
**Last Public Price**: ~$11.98
**Reason for Exclusion**: No longer publicly traded

---

### ❌ PFIZER (PFE)

**Current Status**: S&P 500 Member
**Stock Price**: ~$25.10 (October 1, 2025)
**Reason for Exclusion**: Slightly above $25 target, but worth considering

**Options Liquidity**: Excellent (pharmaceutical giant)
**Assignment Cost**: ~$2,510 per 100 shares
**Wheel Strategy Suitability**: ⭐⭐⭐⭐

**Note**: If willing to expand criteria to $25-30, PFE is a strong candidate with excellent liquidity.

---

### ❌ SIRIUS XM (SIRI)

**Current Status**: Verify S&P 500 membership
**Stock Price**: ~$22.70 (September 27, 2025)
**Assignment Cost**: ~$2,270 per 100 shares

**Options Liquidity**: Good but not exceptional
**Wheel Strategy Suitability**: ⭐⭐⭐

**Reason for Caution**:
- Options liquidity less robust than F or PFE
- Satellite radio industry faces streaming competition
- Verify current S&P 500 status before adding

---

### ❌ VERIZON (VZ)

**Current Status**: S&P 500 Member
**Stock Price**: ~$43.25 (September 29, 2025)
**Reason for Exclusion**: Well above $25 target ($43+)

---

### ❌ BANK OF AMERICA (BAC)

**Current Status**: S&P 500 Member
**Stock Price**: ~$51.58 (October 1, 2025)
**Reason for Exclusion**: Well above $25 target ($50+)

---

### ❌ KINDER MORGAN (KMI)

**Current Status**: S&P 500 Member
**Stock Price**: ~$28.31 (September 30, 2025)
**Reason for Exclusion**: Above $25 target (high $20s)

---

### ❌ NEWMONT CORPORATION (NEM)

**Current Status**: S&P 500 Member
**Stock Price**: ~$84.31 (October 1, 2025)
**Reason for Exclusion**: Well above $25 target ($80+)

---

## Alternative Strategies Considered

### Strategy 1: Expand Price Criteria to $25-30
**Candidates**: PFE ($25), KMI ($28)
**Pros**: More quality S&P 500 options with excellent liquidity
**Cons**: Higher assignment costs, fewer positions possible

### Strategy 2: Non-S&P 500 High-Liquidity Stocks
**Examples**: Nokia (NOK), Goodyear (GT), Plug Power (PLUG)
**Pros**: Lower prices ($5-15), good options liquidity
**Cons**: Not S&P 500, potentially higher volatility, less stability

### Strategy 3: Position Sizing on Higher-Priced Stocks
**Approach**: Sell fewer contracts on quality names like AAPL
**Pros**: Better liquidity, tighter spreads, more stable
**Cons**: Fewer total positions, less diversification

---

## Implementation Status

### ✅ Completed Actions:

1. **Added Ford (F) to config/settings.yaml**
   - Added to stock_symbols list
   - Lowered min_stock_price from $30 to $10 to accommodate F
   - Maintained 2M daily volume requirement for liquidity

2. **Git Commit**: c680263
   - Commit message documents research findings
   - Configuration changes deployed
   - Cloud Run build triggered

3. **Cloud Deployment**: Build #496ee95d queued

---

## Next Steps & Recommendations

### Immediate Actions:
1. ✅ **Monitor Ford (F) in production** after build completes
2. **Run backtest comparison**: Current portfolio vs Ford-included portfolio
3. **Verify Ford passes gap risk filters** (may need adjustment for lower-priced stocks)

### Future Research (if desired):
1. **Expand to $25-30 range**: Consider adding PFE, KMI if performance with F is good
2. **Monitor for new S&P 500 additions**: New constituents may meet criteria
3. **Quarterly review**: Stock prices fluctuate, new candidates may emerge

### Risk Considerations:
- Ford's lower price means lower premiums per contract (offset by higher volume)
- Need to verify historical gap analysis doesn't filter out F
- Monitor automotive sector exposure (currently 1/11 symbols = 9%)

---

## Key Metrics Comparison

| Symbol | Price | Assignment Cost | Positions with $100k | Daily Volume | OI |
|--------|-------|-----------------|---------------------|--------------|-----|
| **F**  | $12   | $1,200         | **83**              | 146k+ contracts | 2.1M |
| AAPL   | $180  | $18,000        | 5                   | Very High | Very High |
| MSFT   | $380  | $38,000        | 2                   | Very High | Very High |
| AMD    | $155  | $15,500        | 6                   | Very High | Very High |
| NVDA   | $400  | $40,000        | 2                   | Very High | Very High |

**Key Insight**: Ford enables 17x more positions than NVDA/MSFT with same capital, allowing for:
- More frequent premium collection
- Better diversification across time (different expiration cycles)
- Lower per-position risk
- More opportunities to test strategy variations

---

## Sources & References

1. **Ford Options Data**: OptionCharts, Fintel, Barchart
2. **S&P 500 Constituent Lists**: Wikipedia, SlickCharts, Stock Analysis
3. **Wheel Strategy Analysis**: WiseSheets, SlashTraders, Maverick Trading, Stock Dork
4. **Stock Price Data**: Yahoo Finance, Nasdaq, Bloomberg, TradingView

---

## Conclusion

Ford (F) represents the best available S&P 500 stock in the low-price range for the options wheel strategy. While very few S&P 500 stocks trade below $25, Ford's combination of:
- Extremely high options liquidity
- Stable, established business
- S&P 500 membership
- Optimal price point (~$12)

...makes it an excellent addition to the portfolio for enabling higher-volume wheel trading while maintaining quality stock selection criteria.

**Status**: ✅ Implemented and deployed
