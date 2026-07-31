import math
from typing import Dict, Any

def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function (CDF)."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def _norm_pdf(x: float) -> float:
    """Standard normal probability density function (PDF)."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

def black_scholes(s: float, k: float, t: float, r: float, sigma: float, option_type: str = "call") -> float:
    """
    Black-Scholes European Options Pricing Model.
    :param s: Spot price of underlying asset
    :param k: Strike price
    :param t: Time to expiration in years (e.g. 1 day = 1/365)
    :param r: Risk-free interest rate (e.g. 0.05)
    :param sigma: Annualized Implied Volatility (e.g. 0.65 for 65% IV)
    :param option_type: 'call' or 'put'
    :return: Option premium price
    """
    if t <= 0 or sigma <= 0 or s <= 0 or k <= 0:
        if option_type.lower() == "call":
            return max(0.0, s - k)
        else:
            return max(0.0, k - s)

    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)

    if option_type.lower() == "call":
        price = s * _norm_cdf(d1) - k * math.exp(-r * t) * _norm_cdf(d2)
    else:
        price = k * math.exp(-r * t) * _norm_cdf(-d2) - s * _norm_cdf(-d1)

    return max(0.0, price)

def calculate_greeks(s: float, k: float, t: float, r: float, sigma: float, option_type: str = "call") -> Dict[str, float]:
    """
    Calculates Options Greeks: Delta, Gamma, Theta (per day), Vega (per 1% IV change).
    """
    if t <= 0 or sigma <= 0 or s <= 0 or k <= 0:
        delta = 1.0 if (option_type == "call" and s > k) else (-1.0 if (option_type == "put" and s < k) else 0.0)
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)

    pdf_d1 = _norm_pdf(d1)

    # Gamma (Same for Call & Put)
    gamma = pdf_d1 / (s * sigma * math.sqrt(t))

    # Vega (Same for Call & Put, per 1% change in IV)
    vega = (s * pdf_d1 * math.sqrt(t)) / 100.0

    if option_type.lower() == "call":
        delta = _norm_cdf(d1)
        theta_annual = -(s * pdf_d1 * sigma) / (2 * math.sqrt(t)) - r * k * math.exp(-r * t) * _norm_cdf(d2)
    else:
        delta = _norm_cdf(d1) - 1.0
        theta_annual = -(s * pdf_d1 * sigma) / (2 * math.sqrt(t)) + r * k * math.exp(-r * t) * _norm_cdf(-d2)

    # Convert annual Theta to daily Theta (1/365)
    theta_daily = theta_annual / 365.0

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta_daily, 4),
        "vega": round(vega, 4)
    }

def move_contract_fair_value(s: float, t_days: float, iv_annual: float) -> Dict[str, float]:
    """
    Calculates Delta Exchange MOVE (MV) contract theoretical fair value.
    Payoff of a MOVE contract approx equals expected absolute price change: E[|S_T - S_0|]
    Theoretical formula: S * sigma * sqrt(T_years) * sqrt(2/pi)
    """
    t_years = t_days / 365.0
    if t_years <= 0 or iv_annual <= 0 or s <= 0:
        return {"fair_value": 0.0, "lower_bound": s, "upper_bound": s}

    expected_move = s * iv_annual * math.sqrt(t_years) * math.sqrt(2.0 / math.pi)
    
    return {
        "fair_value": round(expected_move, 2),
        "expected_move_pct": round((expected_move / s) * 100.0, 2),
        "lower_bound": round(s - expected_move, 2),
        "upper_bound": round(s + expected_move, 2)
    }
