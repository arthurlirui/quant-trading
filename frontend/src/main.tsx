import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { RefreshProvider } from './context/RefreshContext';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RefreshProvider>
      <App />
    </RefreshProvider>
  </React.StrictMode>
);
