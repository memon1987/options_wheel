import { useParams, Link } from 'react-router-dom';

export default function SymbolDeepDive() {
  const { underlying } = useParams<{ underlying?: string }>();

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">
          By Symbol{underlying ? `: ${underlying.toUpperCase()}` : ''}
        </h1>
        <p className="text-gray-400 mt-1">FC-018 v2 dashboard preview — placeholder.</p>
      </header>

      <div className="rounded-lg border border-purple-700 bg-purple-900/20 p-5">
        <h2 className="text-lg font-semibold text-purple-200">Under construction</h2>
        <p className="text-sm text-gray-300 mt-2">
          This page is the wheel-centric heart of the new dashboard. One symbol at a time, full
          history. See
          {' '}<a href="https://github.com/memon1987/options_wheel/blob/main/docs/plans/fc-018.md#page-2--per-symbol-drilldown-v2symbolunderlying"
                 className="text-purple-300 underline hover:text-purple-200"
                 target="_blank"
                 rel="noopener noreferrer">plan §Page 2</a>.
        </p>
      </div>

      <section className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white mb-3">Coming in this view</h3>
        <ul className="text-sm text-gray-300 space-y-2 list-disc list-inside">
          <li>ACB walk chart — adjusted cost basis over time, annotated with each event</li>
          <li>Cycle table — every wheel cycle on this symbol with annualized return</li>
          <li>Decision quality histogram — % of max profit captured at close</li>
          <li>Trade log — chronological event stream</li>
          <li>Phase timing — days in CSP / CC / waiting</li>
          <li>vs-buy-and-hold for this symbol — actual wheel contribution against synthetic B&amp;H</li>
        </ul>
      </section>

      {!underlying && (
        <section className="rounded-lg border border-gray-700 bg-gray-800 p-5">
          <h3 className="text-base font-semibold text-white mb-3">No symbol selected</h3>
          <p className="text-sm text-gray-300 mb-3">
            Once Page 1 (Overview) lands, click any row in the per-symbol scorecard to deep-dive
            into that symbol. For now, navigate manually — e.g.,
            {' '}<Link to="/v2/symbol/AMD" className="text-purple-300 underline hover:text-purple-200">/v2/symbol/AMD</Link>.
          </p>
        </section>
      )}
    </div>
  );
}
