import { Link } from 'react-router-dom';

export default function Overview() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">Overview</h1>
        <p className="text-gray-400 mt-1">FC-018 v2 dashboard preview — placeholder.</p>
      </header>

      <div className="rounded-lg border border-purple-700 bg-purple-900/20 p-5">
        <h2 className="text-lg font-semibold text-purple-200">Under construction</h2>
        <p className="text-sm text-gray-300 mt-2">
          This page will show portfolio-level performance and a per-symbol scorecard. See
          {' '}<a href="https://github.com/memon1987/options_wheel/blob/main/docs/plans/fc-018.md"
                 className="text-purple-300 underline hover:text-purple-200"
                 target="_blank"
                 rel="noopener noreferrer">docs/plans/fc-018.md</a> for the full plan.
        </p>
      </div>

      <section className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white mb-3">Coming in this view</h3>
        <ul className="text-sm text-gray-300 space-y-2 list-disc list-inside">
          <li>Headline KPIs: NLV, XIRR-on-NLV, cumulative net P&amp;L (premium − unrealized), days running</li>
          <li>Equity curve over time</li>
          <li>Monthly stacked premium bars (put / call / stock-gain split)</li>
          <li>Stress row: max simultaneous-assignment mark-to-market</li>
          <li>Per-symbol scorecard table — sortable, with vs-buy-and-hold delta column</li>
          <li>Action panel: open positions needing attention</li>
        </ul>
      </section>

      <section className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white mb-3">For comparison</h3>
        <p className="text-sm text-gray-300 mb-3">
          The current legacy pages remain available while v2 is built:
        </p>
        <div className="flex flex-wrap gap-2">
          <Link to="/" className="text-sm px-3 py-1.5 rounded border border-gray-600 text-gray-300 hover:bg-gray-700">
            Legacy Dashboard
          </Link>
          <Link to="/performance" className="text-sm px-3 py-1.5 rounded border border-gray-600 text-gray-300 hover:bg-gray-700">
            Legacy Performance
          </Link>
        </div>
      </section>
    </div>
  );
}
