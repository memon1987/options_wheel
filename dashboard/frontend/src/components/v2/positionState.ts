// Shared position-state derivation for the FC-018 scorecard and the
// FC-022 SymbolUniverseTable.
//
// FC-031: uses the view's open_put_count/open_call_count split instead of
// guessing "any open option + shares = call". Falls back to the old
// heuristic when the split fields are absent (older API payloads).
// Note: outcome='open' means "no close event ingested yet" — subject to
// activities-ingest lag (~15 min market hours).

import type { ScorecardRow } from '../../types/v2';

export type PositionStateLabel =
  | 'Long + Short Call'
  | 'Long Stock + Short Put'
  | 'Long Stock'
  | 'Short Put'
  | 'Short Call?'
  | 'Cash';

type StateFields = Pick<ScorecardRow, 'current_shares' | 'open_count'> &
  Partial<Pick<ScorecardRow, 'open_put_count' | 'open_call_count'>>;

export const positionState = (row: StateFields): PositionStateLabel => {
  const shares = row.current_shares ?? 0;
  const openPuts = row.open_put_count ?? null;
  const openCalls = row.open_call_count ?? null;

  if (openPuts !== null || openCalls !== null) {
    const puts = openPuts ?? 0;
    const calls = openCalls ?? 0;
    if (shares > 0 && calls > 0) return 'Long + Short Call';
    if (shares > 0 && puts > 0) return 'Long Stock + Short Put';
    if (shares > 0) return 'Long Stock';
    if (puts > 0) return 'Short Put';
    // A short call with no shares should not happen (naked-call gate) —
    // surface it rather than mislabel it.
    if (calls > 0) return 'Short Call?';
    return 'Cash';
  }

  // Legacy heuristic (no split fields in payload).
  const open = row.open_count ?? 0;
  if (shares > 0) return open > 0 ? 'Long + Short Call' : 'Long Stock';
  if (open > 0) return 'Short Put';
  return 'Cash';
};

export const stateColor = (state: PositionStateLabel): string => {
  switch (state) {
    case 'Long + Short Call':      return 'text-purple-300';
    case 'Long Stock + Short Put': return 'text-purple-300';
    case 'Long Stock':             return 'text-blue-300';
    case 'Short Put':              return 'text-green-300';
    case 'Short Call?':            return 'text-red-300';
    default:                       return 'text-gray-400';
  }
};
