interface Position {
  symbol: string
  asset_class: string
  qty: string
  side: string
  market_value: string
  unrealized_pl: string
  cost_basis: string
}

interface PositionsTableProps {
  positions: Position[]
  compact?: boolean
}

// Calculate derived fields from available data
function calculateDerivedFields(pos: Position) {
  const qty = parseFloat(pos.qty)
  const costBasis = parseFloat(pos.cost_basis)
  const marketValue = parseFloat(pos.market_value)
  const unrealizedPl = parseFloat(pos.unrealized_pl)

  // Handle edge cases to avoid NaN/Infinity
  const avgEntryPrice = qty !== 0 ? costBasis / Math.abs(qty) : 0
  const currentPrice = qty !== 0 ? marketValue / Math.abs(qty) : 0
  const unrealizedPlpc = costBasis !== 0 ? unrealizedPl / Math.abs(costBasis) : 0

  return { avgEntryPrice, currentPrice, unrealizedPlpc }
}

export default function PositionsTable({ positions, compact = false }: PositionsTableProps) {
  const formatCurrency = (value: string | number) => {
    const num = typeof value === 'string' ? parseFloat(value) : value
    if (isNaN(num)) return '$0.00'
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(num)
  }

  const formatPercent = (value: number) => {
    if (isNaN(value)) return '0.00%'
    return `${(value * 100).toFixed(2)}%`
  }

  const parseSymbol = (symbol: string, assetClass: string) => {
    if (assetClass === 'us_option') {
      // Parse option symbol: MSFT250117P00380000
      const match = symbol.match(/^([A-Z]+)(\d{6})([PC])(\d{8})$/)
      if (match) {
        const [, underlying, expDate, type, strikeRaw] = match
        const year = `20${expDate.slice(0, 2)}`
        const month = expDate.slice(2, 4)
        const day = expDate.slice(4, 6)
        const strike = parseInt(strikeRaw) / 1000
        const optionType = type === 'P' ? 'Put' : 'Call'
        const expirationDate = `${year}-${month}-${day}`
        return {
          display: `${underlying} ${expirationDate} $${strike} ${optionType}`,
          underlying,
          strike,
          expiration: expirationDate,
          type: optionType,
        }
      }
    }
    return { display: symbol, underlying: symbol }
  }

  if (compact) {
    return (
      <div className="space-y-2">
        {positions.map((pos, index) => {
          const parsed = parseSymbol(pos.symbol, pos.asset_class)
          const pl = parseFloat(pos.unrealized_pl)
          const { avgEntryPrice, unrealizedPlpc } = calculateDerivedFields(pos)
          return (
            <div
              key={index}
              className="flex items-center justify-between p-3 bg-gray-700 rounded-lg"
            >
              <div>
                <p className="font-medium text-white">{parsed.display}</p>
                <p className="text-xs text-gray-400">
                  {pos.qty} @ {formatCurrency(avgEntryPrice)}
                </p>
              </div>
              <div className="text-right">
                <p className={pl >= 0 ? 'profit' : 'loss'}>{formatCurrency(pl)}</p>
                <p className={`text-xs ${pl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {formatPercent(unrealizedPlpc)}
                </p>
              </div>
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead className="bg-gray-700">
          <tr>
            <th className="table-cell table-header">Symbol</th>
            <th className="table-cell table-header text-right">Qty</th>
            <th className="table-cell table-header text-right">Entry</th>
            <th className="table-cell table-header text-right">Current</th>
            <th className="table-cell table-header text-right">P&L</th>
            <th className="table-cell table-header text-right">%</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-700">
          {positions.map((pos, index) => {
            const parsed = parseSymbol(pos.symbol, pos.asset_class)
            const pl = parseFloat(pos.unrealized_pl)
            const { avgEntryPrice, currentPrice, unrealizedPlpc } = calculateDerivedFields(pos)
            return (
              <tr key={index} className="hover:bg-gray-750">
                <td className="table-cell">
                  <div>
                    <p className="font-medium text-white">{parsed.underlying}</p>
                    {pos.asset_class === 'us_option' && parsed.type && (
                      <p className="text-xs text-gray-400">
                        ${parsed.strike} {parsed.type}
                      </p>
                    )}
                  </div>
                </td>
                <td className="table-cell text-right text-gray-300">{pos.qty}</td>
                <td className="table-cell text-right text-gray-300">
                  {formatCurrency(avgEntryPrice)}
                </td>
                <td className="table-cell text-right text-gray-300">
                  {formatCurrency(currentPrice)}
                </td>
                <td className={`table-cell text-right ${pl >= 0 ? 'profit' : 'loss'}`}>
                  {formatCurrency(pl)}
                </td>
                <td className={`table-cell text-right ${pl >= 0 ? 'profit' : 'loss'}`}>
                  {formatPercent(unrealizedPlpc)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
