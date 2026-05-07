import '@testing-library/jest-dom';

// jsdom doesn't implement ResizeObserver, which Recharts' ResponsiveContainer
// uses on mount. Stub it so chart components can be rendered in tests.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).ResizeObserver = (globalThis as any).ResizeObserver ?? ResizeObserverStub;
