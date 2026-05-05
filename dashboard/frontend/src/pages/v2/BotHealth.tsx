export default function BotHealth() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">Bot Health</h1>
        <p className="text-gray-400 mt-1">FC-018 v2 dashboard preview — placeholder.</p>
      </header>

      <div className="rounded-lg border border-purple-700 bg-purple-900/20 p-5">
        <h2 className="text-lg font-semibold text-purple-200">Under construction</h2>
        <p className="text-sm text-gray-300 mt-2">
          Operational debugging view — what the bot has been doing and where it's been blocked. See
          {' '}<a href="https://github.com/memon1987/options_wheel/blob/main/docs/plans/fc-018.md#page-3--bot-health-v2bot-health"
                 className="text-purple-300 underline hover:text-purple-200"
                 target="_blank"
                 rel="noopener noreferrer">plan §Page 3</a>.
        </p>
      </div>

      <section className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white mb-3">Coming in this view</h3>
        <ul className="text-sm text-gray-300 space-y-2 list-disc list-inside">
          <li>Gate hit counts — filtering pipeline stages 1-9 over rolling 7d / 30d windows</li>
          <li>Recent errors — last 50 with frequency rollup by error type and component</li>
          <li>Scan cadence — last-N successful scans, runs, monitors; anomaly flags</li>
          <li>Ingest health (FC-012) — last successful run of /ingest-activities and /ingest-portfolio-history</li>
        </ul>
      </section>
    </div>
  );
}
