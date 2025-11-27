interface Trade {
  timestamp: string
  symbol: string
  underlying: string
  strategy: string
  quantity: number
  strike_price: number
  expiration: string
  premium: number
  dte: number
  status: string
}

interface RecentTradesProps {
  trades: Trade[]
}

export default function RecentTrades({ trades }: RecentTradesProps) {
  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(value * 100) // Premium is per share, multiply by 100
  }

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    })
  }

  const getStrategyLabel = (strategy: string) => {
    switch (strategy) {
      case 'sell_put':
        return 'Sell Put'
      case 'sell_call':
        return 'Sell Call'
      case 'buy_to_close':
        return 'Close'
      default:
        return strategy
    }
  }

  const getStrategyColor = (strategy: string) => {
    switch (strategy) {
      case 'sell_put':
        return 'text-purple-400'
      case 'sell_call':
        return 'text-blue-400'
      case 'buy_to_close':
        return 'text-green-400'
      default:
        return 'text-gray-400'
    }
  }

  return (
    <div className="space-y-2">
      {trades.map((trade, index) => (
        <div
          key={index}
          className="flex items-center justify-between p-3 bg-gray-700 rounded-lg"
        >
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="font-medium text-white">
                {trade.underlying || trade.symbol}
              </span>
              <span className={`text-xs ${getStrategyColor(trade.strategy)}`}>
                {getStrategyLabel(trade.strategy)}
              </span>
            </div>
            <p className="text-xs text-gray-400">
              ${trade.strike_price?.toFixed(0)} • {trade.dte} DTE • {formatDate(trade.timestamp)}
            </p>
          </div>
          <div className="text-right">
            <p className="profit font-medium">{formatCurrency(trade.premium)}</p>
            <p className="text-xs text-gray-400">{trade.status}</p>
          </div>
        </div>
      ))}
    </div>
  )
}
