interface StatusCardProps {
  title: string
  value: string
  subtitle?: string
  trend?: number
  trendLabel?: string
}

export default function StatusCard({ title, value, subtitle, trend, trendLabel }: StatusCardProps) {
  return (
    <div className="card">
      <p className="card-header">{title}</p>
      <p className="card-value text-white">{value}</p>
      {subtitle && <p className="text-xs text-gray-400 mt-1">{subtitle}</p>}
      {trend !== undefined && (
        <p className={`text-xs mt-1 ${trend >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          {trend >= 0 ? '↑' : '↓'} {Math.abs(trend * 100).toFixed(1)}%
          {trendLabel && <span className="text-gray-500 ml-1">{trendLabel}</span>}
        </p>
      )}
    </div>
  )
}
