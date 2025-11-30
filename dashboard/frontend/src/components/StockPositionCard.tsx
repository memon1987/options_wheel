import { LineChart, Line, ResponsiveContainer } from 'recharts'

interface StockPositionCardProps {
  symbol: string
  shares: number
  costBasis: number
  currentPrice: number
  unrealizedPL: number
  unrealizedPLPct: number
  daysHeld: number
  historicalData: Array<{ date: string; unrealized_pl: number }>
}

export default function StockPositionCard({
  symbol,
  shares,
  costBasis,
  currentPrice,
  unrealizedPL,
  unrealizedPLPct,
  daysHeld,
  historicalData,
}: StockPositionCardProps) {
  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)
  }

  const formatPrice = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value)
  }

  const isPositive = unrealizedPL >= 0

  return (
    <div className="card">
      <div className="flex justify-between items-start mb-3">
        <div>
          <h3 className="text-xl font-bold text-white">{symbol}</h3>
          <p className="text-sm text-gray-400">{shares} shares</p>
        </div>
        <div className="text-right">
          <span className={`text-lg font-semibold ${isPositive ? 'profit' : 'loss'}`}>
            {formatCurrency(unrealizedPL)}
          </span>
          <p className={`text-sm ${isPositive ? 'profit' : 'loss'}`}>
            {isPositive ? '+' : ''}{(unrealizedPLPct * 100).toFixed(2)}%
          </p>
        </div>
      </div>

      {/* Sparkline Chart */}
      {historicalData.length > 1 && (
        <div className="h-16 mb-3">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={historicalData}>
              <Line
                type="monotone"
                dataKey="unrealized_pl"
                stroke={isPositive ? '#10B981' : '#EF4444'}
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <p className="text-gray-400">Cost Basis</p>
          <p className="text-white">{formatPrice(costBasis)}</p>
        </div>
        <div>
          <p className="text-gray-400">Current Price</p>
          <p className="text-white">{formatPrice(currentPrice)}</p>
        </div>
        <div>
          <p className="text-gray-400">Total Value</p>
          <p className="text-white">{formatCurrency(currentPrice * shares)}</p>
        </div>
        <div>
          <p className="text-gray-400">Days Held</p>
          <p className="text-white">{daysHeld}</p>
        </div>
      </div>
    </div>
  )
}
