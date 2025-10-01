# Research & Experiments

This directory contains experimental features, research projects, and exploratory analysis that may or may not make it into production.

## Purpose

- Test new trading strategies
- Experiment with different approaches
- Analyze historical performance
- Prototype new features
- Document research findings

## Directory Structure

### `experiments/`
Active experiments and prototypes:

- **`monday_only_backtesting/`** - Research on Monday-only trade execution strategy
  - Analyzes if executing trades only on Mondays improves risk-adjusted returns
  - Includes trade-by-trade analysis tools
  - Results and findings documented

## Guidelines

1. **Experimental Code**: Code here may not follow all production standards
2. **Documentation**: Each experiment should have its own README
3. **Isolation**: Experiments should not affect production code
4. **Graduation**: Successful experiments can be promoted to `src/` or `tools/`

## Moving to Production

If an experiment proves valuable:
1. Refactor to production standards
2. Add comprehensive tests
3. Document in main docs/
4. Move to appropriate directory (src/ or tools/)
5. Update configuration as needed

## Archive

Completed experiments that didn't make it to production can be archived in a separate branch or documented here for future reference.
