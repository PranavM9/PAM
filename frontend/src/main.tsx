import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.tsx'
import './index.css'
import { installPressFeedback } from './lib/pressFeedback'

installPressFeedback()

// Light mode disabled for now; to restore, use the commented block below.
document.documentElement.dataset.theme = 'dark'
// try {
//   document.documentElement.dataset.theme = localStorage.getItem('pam-theme') === 'light' ? 'light' : 'dark'
// } catch {
//   document.documentElement.dataset.theme = 'dark'
// }

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 10_000 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
