import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import LayoutV2 from './components/v2/LayoutV2';
import ErrorBoundary from './components/ErrorBoundary';
import OverviewV2 from './pages/v2/Overview';
import SymbolDeepDiveV2 from './pages/v2/SymbolDeepDive';
import BotHealthV2 from './pages/v2/BotHealth';

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          {/* FC-018 v2 — the canonical dashboard. */}
          <Route element={<LayoutV2 />}>
            <Route path="/v2/overview" element={<OverviewV2 />} />
            <Route path="/v2/symbol" element={<SymbolDeepDiveV2 />} />
            <Route path="/v2/symbol/:underlying" element={<SymbolDeepDiveV2 />} />
            <Route path="/v2/bot-health" element={<BotHealthV2 />} />
          </Route>

          {/* PR F cutover (FC-018): legacy paths now redirect to v2. */}
          {/* Old page components (Dashboard / Positions / Trades / Performance / */}
          {/* WheelCycles) are no longer imported here; they remain in src/pages/   */}
          {/* until PR G archives them. */}
          <Route path="/"             element={<Navigate to="/v2/overview"    replace />} />
          <Route path="/positions"    element={<Navigate to="/v2/overview"    replace />} />
          <Route path="/trades"       element={<Navigate to="/v2/overview"    replace />} />
          <Route path="/performance"  element={<Navigate to="/v2/overview"    replace />} />
          <Route path="/cycles"       element={<Navigate to="/v2/symbol"      replace />} />

          {/* Catch-all: anything else lands on v2 Overview. */}
          <Route path="*" element={<Navigate to="/v2/overview" replace />} />
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
