import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useApi } from '../hooks/useApi';

interface AccountData {
  paper_trading?: boolean;
}

const navItems = [
  { path: '/', label: 'Dashboard' },
  { path: '/positions', label: 'Positions' },
  { path: '/trades', label: 'Trades' },
  { path: '/performance', label: 'Performance' },
  { path: '/cycles', label: 'Wheel Cycles' },
];

export default function Layout() {
  const [menuOpen, setMenuOpen] = useState(false);
  const { data: account } = useApi<AccountData>('/api/live/account', { refreshInterval: 60_000 });

  const isPaperTrading = account?.paper_trading ?? false;

  return (
    <div className="min-h-screen bg-gray-900">
      {/* Mobile Header */}
      <header className="lg:hidden fixed top-0 left-0 right-0 z-50 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-bold text-white">Options Wheel</h1>
            {isPaperTrading && (
              <span className="px-2 py-0.5 bg-yellow-900 text-yellow-300 text-xs font-medium rounded">
                PAPER
              </span>
            )}
          </div>
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="p-2 text-gray-400 hover:text-white"
            aria-label="Toggle menu"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {menuOpen ? (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              )}
            </svg>
          </button>
        </div>

        {menuOpen && (
          <nav className="px-4 py-2 bg-gray-800 border-t border-gray-700">
            {navItems.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === '/'}
                onClick={() => setMenuOpen(false)}
                className={({ isActive }) =>
                  `block py-3 px-4 rounded-lg mb-1 transition-colors ${
                    isActive ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-700'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>

      {/* Desktop Sidebar */}
      <aside className="hidden lg:flex lg:flex-col lg:fixed lg:inset-y-0 lg:w-60 bg-gray-800 border-r border-gray-700">
        <div className="p-6">
          <h1 className="text-xl font-bold text-white">Options Wheel</h1>
          <p className="text-sm text-gray-400 mt-1">Trading Dashboard</p>
          {isPaperTrading && (
            <span className="inline-block mt-2 px-2 py-0.5 bg-yellow-900 text-yellow-300 text-xs font-medium rounded">
              PAPER TRADING
            </span>
          )}
        </div>

        <nav className="flex-1 px-4">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) =>
                `flex items-center py-3 px-4 rounded-lg mb-1 transition-colors ${
                  isActive ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-700'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Main Content */}
      <main className="lg:pl-60 pt-16 lg:pt-0">
        <div className="p-4 lg:p-6 max-w-7xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
