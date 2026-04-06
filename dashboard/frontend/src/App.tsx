import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import Dashboard from './pages/Dashboard';
import Positions from './pages/Positions';
import Trades from './pages/Trades';
import Performance from './pages/Performance';
import WheelCycles from './pages/WheelCycles';

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/positions" element={<Positions />} />
            <Route path="/trades" element={<Trades />} />
            <Route path="/performance" element={<Performance />} />
            <Route path="/cycles" element={<WheelCycles />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
