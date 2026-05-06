// Shared position-state derivation for the FC-018 scorecard and the
// FC-022 SymbolUniverseTable.

import type { ScorecardRow } from '../../types/v2';

export type PositionStateLabel =
  | 'Long + Short Call'
  | 'Long Stock'
  | 'Short Put'
  | 'Cash';

export const positionState = (row: Pick<ScorecardRow, 'current_shares' | 'open_count'>): PositionStateLabel => {
  const shares = row.current_shares ?? 0;
  const open = row.open_count ?? 0;
  if (shares > 0) return open > 0 ? 'Long + Short Call' : 'Long Stock';
  if (open > 0) return 'Short Put';
  return 'Cash';
};

export const stateColor = (state: PositionStateLabel): string => {
  switch (state) {
    case 'Long + Short Call': return 'text-purple-300';
    case 'Long Stock':        return 'text-blue-300';
    case 'Short Put':         return 'text-green-300';
    default:                  return 'text-gray-400';
  }
};
