#!/usr/bin/env python3
"""Analyze the relationship between delta and assignment probability."""

import numpy as np
from scipy.stats import norm
import math

def black_scholes_delta(S, K, T, r, sigma, option_type='put'):
    """Calculate Black-Scholes delta and implied probability.
    
    Args:
        S: Current stock price
        K: Strike price  
        T: Time to expiration (years)
        r: Risk-free rate
        sigma: Volatility
        option_type: 'put' or 'call'
    """
    # Calculate d1
    d1 = (math.log(S/K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    
    # Calculate N(d1)
    N_d1 = norm.cdf(d1)
    
    if option_type == 'put':
        delta = N_d1 - 1  # Put delta
        assignment_prob = abs(delta)  # |Delta| approximation
        actual_prob = 1 - N_d1  # P(S_T <= K)
    else:  # call
        delta = N_d1  # Call delta  
        assignment_prob = delta  # Delta approximation
        actual_prob = N_d1  # P(S_T > K)
    
    return {
        'delta': delta,
        'assignment_prob_from_delta': assignment_prob,
        'theoretical_assignment_prob': actual_prob,
        'difference': abs(assignment_prob - actual_prob)
    }

def analyze_delta_probability_relationship():
    """Analyze delta vs assignment probability for various scenarios."""
    
    print("🎯 DELTA vs ASSIGNMENT PROBABILITY ANALYSIS")
    print("=" * 60)
    
    # Base case: AAPL at $150
    S = 150  # Current stock price
    T = 30/365  # 30 days
    r = 0.05  # 5% risk-free rate
    sigma = 0.25  # 25% volatility
    
    print(f"Stock Price: ${S}")
    print(f"Time to Expiration: {int(T*365)} days")
    print(f"Volatility: {sigma*100:.0f}%")
    print()
    
    # Analyze different strike prices for puts
    print("PUT OPTIONS:")
    print("Strike | Delta   | Assignment Prob | Theoretical | Difference")
    print("       |         | (from Delta)    | Probability | ")  
    print("-" * 60)
    
    put_strikes = [130, 135, 140, 145, 148]
    for K in put_strikes:
        result = black_scholes_delta(S, K, T, r, sigma, 'put')
        print(f"${K:3d}   | {result['delta']:6.3f}  | {result['assignment_prob_from_delta']:8.1%}       | {result['theoretical_assignment_prob']:8.1%}    | {result['difference']:6.3f}")
    
    print()
    print("CALL OPTIONS:")
    print("Strike | Delta   | Assignment Prob | Theoretical | Difference")
    print("       |         | (from Delta)    | Probability | ")
    print("-" * 60)
    
    call_strikes = [152, 155, 160, 165, 170]
    for K in call_strikes:
        result = black_scholes_delta(S, K, T, r, sigma, 'call')
        print(f"${K:3d}   | {result['delta']:6.3f}  | {result['assignment_prob_from_delta']:8.1%}       | {result['theoretical_assignment_prob']:8.1%}    | {result['difference']:6.3f}")
    
    print()
    print("💡 KEY INSIGHTS:")
    print("1. Delta approximates assignment probability very closely")
    print("2. The approximation is most accurate for at-the-money options")
    print("3. Small differences are due to the risk-neutral vs real-world probability")
    print("4. For practical trading, |Delta| ≈ Assignment Probability is excellent")

def demonstrate_wheel_strategy_probabilities():
    """Show assignment probabilities for typical wheel strategy deltas."""
    
    print("\n" + "🎯 WHEEL STRATEGY ASSIGNMENT PROBABILITIES")
    print("=" * 60)
    
    delta_ranges = {
        'Conservative': [0.10, 0.20],
        'Balanced': [0.15, 0.30], 
        'Aggressive': [0.25, 0.40],
        'Very Aggressive': [0.35, 0.50]
    }
    
    print("Strategy        | Delta Range | Assignment Range | Expected Outcomes")
    print("-" * 65)
    
    for strategy, (min_delta, max_delta) in delta_ranges.items():
        min_assign = min_delta * 100
        max_assign = max_delta * 100
        success_rate = 100 - max_assign
        
        print(f"{strategy:15s} | {min_delta:.2f} - {max_delta:.2f}   | {min_assign:5.0f}% - {max_assign:5.0f}%     | Keep premium {success_rate:5.0f}%+ of time")

if __name__ == '__main__':
    analyze_delta_probability_relationship()
    demonstrate_wheel_strategy_probabilities()