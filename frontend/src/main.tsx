import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.tsx';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { ErrorBoundary } from './components/ErrorBoundary.tsx';
import { ApiError } from './services/apiClient.ts';
import { AuthProvider } from './providers/AuthProvider.tsx';
import { ThemeProvider } from './providers/ThemeProvider.tsx';
import './styles/App.css';
import './styles/integration.css';
import './styles/typography.css';
import './styles/design-system.css';
import './styles/messaging.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) =>
        failureCount < 1 &&
        (!(error instanceof ApiError) || error.status >= 500 || error.status === 429),
      retryDelay: (_attempt, error) =>
        error instanceof ApiError && error.retryAfter !== undefined
          ? error.retryAfter * 1000
          : 1000,
      refetchOnWindowFocus: false,
    },
    mutations: { retry: false },
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <QueryClientProvider client={queryClient}>
          <ThemeProvider>
            <AuthProvider>
              <App />
            </AuthProvider>
          </ThemeProvider>
        </QueryClientProvider>
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>
);
