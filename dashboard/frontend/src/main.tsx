import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import { installGlobalErrorHandlers } from './utils/errorReporter';

// Install global error handlers before rendering
installGlobalErrorHandlers();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
