import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import { AppBoundary } from './lib/lazyChunk.jsx';
import './styles.css';

createRoot(document.getElementById('root')).render(<AppBoundary><App /></AppBoundary>);
