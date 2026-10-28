# Indicator direction audit (v2)

High score = expensive (valuation), greedy (sentiment), stressed (macro risk). Price/relative level and concentration are separate, raw historical ranks. Signs are modelling assumptions, not causal laws.

| Metric / source | Block | High observed value means | Score at percentile 90 | Fields |
|---|---|---|---:|---|
| us_gdp / GDP | not scored in v2 | US Nominal GDP, billions USD, quarterly. | N/A | — |
| buffett_indicator / sp500_div_gdp | not scored in v2 | LEGACY S&P 500 index-level / nominal GDP proxy; NOT market capitalization / GDP. Historical percentile equivalence is not established. Excluded from v2 valuation. | N/A | — |
| equity_risk_premium / earnings_yield_minus_10y | valuation | Equity Risk Premium proxy: S&P 500 earnings yield minus 10Y Treasury. Negative = stocks priced for returns below cash; historically a warning. | 10 | overall |
| hy_minus_ig_oas / hy_minus_ig | sentiment | Junk minus IG credit spread. Widening = credit market punishing weaker balance sheets first; often leads equity drawdowns. | 10 | overall, finance |
| hy_minus_ig_oas / hy_minus_ig | macro_risk | Junk minus IG credit spread. Widening = credit market punishing weaker balance sheets first; often leads equity drawdowns. | 90 | overall |
| ny_fed_recession_prob / RECPROUSM156N | macro_risk | NY Fed 12-month-ahead recession probability from the yield curve. >30% has historically preceded every modern US recession. | 90 | overall, finance |
| sofr / SOFR | macro_risk | Secured Overnight Financing Rate. Spikes flag dollar-funding stress; typical level mirrors Fed Funds. | 90 | finance |
| shiller_cape_us / shiller-pe | valuation | Shiller cyclically-adjusted P/E (CAPE). Long-horizon US valuation. | 90 | overall |
| sp500_pe / s-p-500-pe-ratio | valuation | S&P 500 trailing P/E. | 90 | overall |
| sp500_div_yield / s-p-500-dividend-yield | valuation | S&P 500 dividend yield (%). Inversely related to expensiveness. | 10 | overall |
| sp500_close / ^GSPC | not scored in v2 | S&P 500 spot price reference. | N/A | — |
| stoxx600_close / ^STOXX | not scored in v2 | Stoxx Europe 600 spot price reference. | N/A | — |
| nasdaq_close / ^IXIC | not scored in v2 | Nasdaq Composite spot price reference. Tech-heavy US benchmark. | N/A | — |
| spy / SPY | not scored in v2 | Cap-weighted S&P 500 ETF. | N/A | — |
| rsp / RSP | not scored in v2 | Equal-weighted S&P 500 ETF. | N/A | — |
| rsp_spy_ratio / rsp_div_spy | price_momentum | RSP/SPY ratio. Rising = broadening rally; falling = narrow Mag-7 leadership. | 90 | overall |
| sp500_top10_share / top_10_share | concentration | Sum of weights of top 10 S&P 500 names (%). High = narrow market — 'when 5 stocks do all the lifting'. | 90 | overall |
| sp500_mag7_share / mag7_share | concentration | Combined S&P 500 weight of Mag-7 (NVDA, MSFT, GOOGL+GOOG, AMZN, META, AAPL, TSLA). Concentration risk gauge. | 90 | overall |
| nvda_sp500_share / nvda_share | concentration | Nvidia's weight in the S&P 500 (%). Single-name concentration: how much of the index *is* one chip company. | 90 | ai |
| vix / ^VIX | sentiment | 30-day implied vol on S&P 500. High = fear. | 10 | overall, defense, defensive |
| vvix / ^VVIX | sentiment | Vol of vol. Tail-risk pricing. | 10 | overall |
| move / ^MOVE | sentiment | ICE BofA MOVE — bond-market vol. Often leads VIX. | 10 | overall |
| cnn_fear_greed / default | sentiment | CNN Fear & Greed composite (0=panic, 100=euphoria). | 90 | overall, ai, energy |
| aaii_bull_bear_spread /  | sentiment | AAII weekly Bull-Bear spread (% bullish minus % bearish). Direct retail-investor positioning. Extreme positives mark retail-greed peaks; extreme negatives mark capitulation troughs. | 90 | overall |
| naaim_exposure /  | sentiment | NAAIM Exposure Index — mean equity exposure (-200% to +200%) reported weekly by active managers. Currently disabled — see comment in metrics.yaml to re-enable. | 90 | overall |
| hy_oas_us / BAMLH0A0HYM2 | sentiment | ICE BofA US High Yield OAS. Best single credit-stress gauge. | 10 | overall, finance |
| hy_oas_us / BAMLH0A0HYM2 | macro_risk | ICE BofA US High Yield OAS. Best single credit-stress gauge. | 90 | overall, ai, finance, defensive |
| ig_oas_us / BAMLC0A0CM | sentiment | ICE BofA US Investment Grade OAS. | 10 | overall |
| us_10y / DGS10 | macro_risk | US 10Y Treasury yield. | 90 | construction |
| us_2s10s / T10Y2Y | macro_risk | 10Y - 2Y. Inversion is the classic recession signal. | 10 | overall, finance |
| us_3m10y / T10Y3M | macro_risk | 10Y - 3M. Strongest historical recession signal. | 10 | overall, finance |
| us_real_10y / DFII10 | macro_risk | 10Y TIPS real yield. | 90 | overall, ai, defensive |
| us_5y5y_breakeven / T5YIFR | not scored in v2 | 5y5y forward breakeven. Long-horizon inflation expectations. | N/A | — |
| dxy / DTWEXBGS | macro_risk | Trade-weighted broad USD index. Strong USD = global liquidity tightening. | 90 | overall, ai, energy |
| us_unemployment / UNRATE | not scored in v2 | US unemployment rate. | N/A | — |
| us_initial_claims / ICSA | not scored in v2 | Initial unemployment claims, weekly. | N/A | — |
| gpr_daily /  | macro_risk | Caldara & Iacoviello Geopolitical Risk Index, daily. | 90 | overall, energy, defense, defensive |
| smh / SMH | price_momentum | VanEck Semiconductor ETF — AI-cycle proxy. | 90 | ai |
| nvda / NVDA | price_momentum | Nvidia spot. Single-name concentration risk. | 90 | ai |
| xlk / XLK | sentiment | Tech sector ETF spot. | 90 | ai |
| xlu / XLU | not scored in v2 | Utilities ETF spot. Power-demand proxy + defensive. | N/A | — |
| xlk_xlu_ratio / xlk_div_xlu | sentiment | XLK/XLU. Rising = AI optimism dominating; falling = rotation toward power scarcity. | 90 | ai |
| arkk / ARKK | sentiment | ARK Innovation ETF — speculative-pulse retail proxy. | 90 | ai |
| housing_starts / HOUST | macro_risk | US new privately-owned housing starts. | 10 | construction |
| building_permits / PERMIT | macro_risk | US building permits — leading indicator for starts. | 10 | construction |
| mortgage_30y / MORTGAGE30US | macro_risk | 30-year fixed mortgage rate. High = housing demand crushed. | 90 | construction |
| itb / ITB | price_momentum | iShares US Home Construction ETF. | 90 | construction |
| xhb / XHB | sentiment | SPDR Homebuilders ETF — sentiment-flavored basket. | 90 | construction |
| lumber / LBR=F | macro_risk | Lumber futures. High = costs squeezing margins. | 90 | construction |
| xlf / XLF | price_momentum | Financials sector ETF. | 90 | finance |
| kre / KRE | price_momentum | Regional banks ETF — duration/credit canary. | 90 | finance |
| kbe / KBE | price_momentum | SPDR Bank ETF (broad US banks). | 90 | finance |
| eufn / EUFN | price_momentum | iShares MSCI Europe Financials ETF. | 90 | finance |
| brent / BZ=F | price_momentum | Brent crude front-month. | 90 | energy |
| wti / CL=F | price_momentum | WTI crude front-month. | 90 | energy |
| nat_gas_us / DHHNGSP | not scored in v2 | Henry Hub natural gas spot. | N/A | — |
| ttf_gas_eu / TTF=F | macro_risk | Dutch TTF natural gas — the European gas benchmark. Spikes here drive Euro-area inflation and industrial cost shock; a key Iran-war / Russia-supply read-through. | 90 | energy |
| ttf_gas_eu / TTF=F | price_momentum | Dutch TTF natural gas — the European gas benchmark. Spikes here drive Euro-area inflation and industrial cost shock; a key Iran-war / Russia-supply read-through. | 90 | energy |
| xle / XLE | price_momentum | Energy sector ETF. | 90 | energy |
| xop / XOP | price_momentum | Oil & gas E&P ETF. | 90 | energy |
| ita / ITA | price_momentum | iShares US Aerospace & Defense ETF. | 90 | defense |
| lmt / LMT | price_momentum | Lockheed Martin spot. | 90 | defense |
| rtx / RTX | price_momentum | RTX Corp (Raytheon). | 90 | defense |
| gold / GC=F | price_momentum | Gold front-month. Safe-haven gauge. | 90 | defensive |
| silver / SI=F | price_momentum | Silver front-month. | 90 | defensive |
| copper / HG=F | sentiment | Copper front-month — Dr. Copper. | 90 | energy |
| gold_copper_ratio / gold_div_copper | macro_risk | Gold/Copper. Rising = recession risk pricing. | 90 | overall |
| gold_oil_ratio / gold_div_brent | macro_risk | Gold/Brent. Rising = energy-stress / hard-asset rotation. | 90 | energy |
| tlt / TLT | price_momentum | iShares 20+ Year Treasury ETF — duration safe haven. | 90 | defensive |
| xlp / XLP | price_momentum | Consumer staples ETF. | 90 | defensive |
| xlv / XLV | price_momentum | Healthcare ETF. | 90 | defensive |
| chf_usd / CHF=X | sentiment | USD/CHF. Lower = stronger Swiss franc = safe-haven flow. | 90 | defensive |
| btc_usd / BTC-USD | sentiment | Bitcoin USD spot — speculative pulse, NOT a safe-haven proxy here. | 90 | overall |
| mstr / MSTR | sentiment | MicroStrategy — BTC-leverage proxy. Extreme-greed indicator. | 90 | overall |
| de_10y / IRLTLT01DEM156N | not scored in v2 | Germany 10Y Bund yield (monthly avg from FRED). | N/A | — |
| it_10y / IRLTLT01ITM156N | not scored in v2 | Italy 10Y BTP yield. | N/A | — |
| italy_bund_spread / italy_minus_bund | macro_risk | Italy 10Y minus Germany 10Y. Eurozone fragmentation gauge. | 90 | finance |
| eu_hy_oas / BAMLHE00EHYIOAS | sentiment | ICE BofA Euro HY OAS. | 10 | finance |
| eu_hicp_yoy / CP0000EZ19M086NEST | not scored in v2 | Eurozone HICP, YoY proxy (FRED publishes index level — interpret accordingly). | N/A | — |
| eur_usd / EURUSD=X | macro_risk | EUR/USD spot. Falling = USD strength = global liquidity tightening; rising = the opposite. | 10 | overall |
| us_equity_market_cap / BOGZ1LM883164115Q | not scored in v2 | Federal Reserve Financial Accounts: all domestic sectors, public corporate equities, liability market value; millions USD, NSA. Excludes private equities; quarterly market cap, not an index. | N/A | — |
| us_market_cap_gdp / us_market_cap_div_gdp | valuation | Domestic public corporate equity market cap / nominal GDP (SAAR), percent. Quarterly aligned periods; revised data, not a point-in-time backtest. Missing cap/GDP inputs remain N/A. | 90 | overall |
