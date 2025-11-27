import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { useState, useEffect } from 'react'
import Dashboard from './pages/Dashboard'
import Trades from './pages/Trades'
import Positions from './pages/Positions'
import Performance from './pages/Performance'
import Settings from './pages/Settings'
import WheelCycles from './pages/WheelCycles'
import Calendar from './pages/Calendar'
import Filtering from './pages/Filtering'

function App() {
  const [menuOpen, setMenuOpen] = useState(false)

  // Close menu when route changes
  useEffect(() => {
    setMenuOpen(false)
  }, [])

  const navItems = [
    { path: '/', label: 'Dashboard', icon: '📊' },
    { path: '/positions', label: 'Positions', icon: '📈' },
    { path: '/trades', label: 'Trades', icon: '📋' },
    { path: '/cycles', label: 'Wheel Cycles', icon: '🔄' },
    { path: '/calendar', label: 'Calendar', icon: '📅' },
    { path: '/performance', label: 'Performance', icon: '💰' },
    { path: '/filtering', label: 'Filtering', icon: '🔍' },
    { path: '/settings', label: 'Settings', icon: '⚙️' },
  ]

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-900">
        {/* Mobile Header */}
        <header className="lg:hidden fixed top-0 left-0 right-0 z-50 bg-gray-800 border-b border-gray-700">
          <div className="flex items-center justify-between px-4 py-3">
            <h1 className="text-lg font-bold text-white">Options Wheel</h1>
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className="p-2 text-gray-400 hover:text-white"
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

          {/* Mobile Navigation */}
          {menuOpen && (
            <nav className="px-4 py-2 bg-gray-800 border-t border-gray-700">
              {navItems.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  onClick={() => setMenuOpen(false)}
                  className={({ isActive }) =>
                    `block py-3 px-4 rounded-lg mb-1 ${
                      isActive
                        ? 'bg-blue-600 text-white'
                        : 'text-gray-300 hover:bg-gray-700'
                    }`
                  }
                >
                  <span className="mr-3">{item.icon}</span>
                  {item.label}
                </NavLink>
              ))}
            </nav>
          )}
        </header>

        {/* Desktop Sidebar */}
        <aside className="hidden lg:flex lg:flex-col lg:fixed lg:inset-y-0 lg:w-64 bg-gray-800 border-r border-gray-700">
          <div className="p-6">
            <h1 className="text-xl font-bold text-white">Options Wheel</h1>
            <p className="text-sm text-gray-400 mt-1">Trading Dashboard</p>
          </div>

          <nav className="flex-1 px-4">
            {navItems.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) =>
                  `flex items-center py-3 px-4 rounded-lg mb-1 ${
                    isActive
                      ? 'bg-blue-600 text-white'
                      : 'text-gray-300 hover:bg-gray-700'
                  }`
                }
              >
                <span className="mr-3">{item.icon}</span>
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="p-4 border-t border-gray-700">
            <div className="text-xs text-gray-500">
              Last updated: {new Date().toLocaleTimeString()}
            </div>
          </div>
        </aside>

        {/* Main Content */}
        <main className="lg:pl-64 pt-16 lg:pt-0">
          <div className="p-4 lg:p-6">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/positions" element={<Positions />} />
              <Route path="/trades" element={<Trades />} />
              <Route path="/cycles" element={<WheelCycles />} />
              <Route path="/calendar" element={<Calendar />} />
              <Route path="/performance" element={<Performance />} />
              <Route path="/filtering" element={<Filtering />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </div>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App
