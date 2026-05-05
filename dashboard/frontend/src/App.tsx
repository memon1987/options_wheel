import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import LayoutV2 from './components/v2/LayoutV2';
import ErrorBoundary from './components/ErrorBoundary';
import Dashboard from './pages/Dashboard';
import Positions from './pages/Positions';
import Trades from './pages/Trades';
import Performance from './pages/Performance';
import WheelCycles from './pages/WheelCycles';
import OverviewV2 from './pages/v2/Overview';
import SymbolDeepDiveV2 from './pages/v2/SymbolDeepDive';
import BotHealthV2 from './pages/v2/BotHealth';

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          {/* Legacy v1 — preserved during the FC-018 strangler migration. */}
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/positions" element={<Positions />} />
            <Route path="/trades" element={<Trades />} />
            <Route path="/performance" element={<Performance />} />
            <Route path="/cycles" element={<WheelCycles />} />
          </Route>

          {/* FC-018 v2 — wheel-centric rebuild. Replaces v1 routes incrementally. */}
          <Route element={<LayoutV2 />}>
            <Route path="/v2/overview" element={<OverviewV2 />} />
            <Route path="/v2/symbol" element={<SymbolDeepDiveV2 />} />
            <Route path="/v2/symbol/:underlying" element={<SymbolDeepDiveV2 />} />
            <Route path="/v2/bot-health" element={<BotHealthV2 />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
