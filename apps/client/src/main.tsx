import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import './index.css'
import Hero from './pages/Hero';
import DashLayout from './layouts/DashLayout';
import CompassMaster from './pages/compassMaster';
import CompassView from './pages/compassView';
import CompassVisualizer from './pages/compassVisualizer';
import CompassChat from './pages/compassChat';
import CompassIngestion from './pages/compassIngestion';
import Error from './pages/Error';
import ResearchAgent from './pages/researchAgent';
import ErrorBoundary from './components/ErrorBoundary';

const router = createBrowserRouter([
  {
    path: '/',
    element: <Hero />,
    errorElement: <Error />,
  },
  {
    path: '/dashboard',
    element: <DashLayout />,
    errorElement: <Error />,
    children: [
      {
        index: true,
        element: <CompassMaster />,
        errorElement: <Error />,
      },
      {
        path: 'capabilities',
        element: <CompassMaster />,
        errorElement: <Error />,
      },
      {
        path: 'compass-ingestion',
        element: <CompassIngestion />,
        errorElement: <Error />,
      },
      {
        path: 'research-agent',
        element: <ResearchAgent />,
        errorElement: <Error />,
      },
      {
        path: 'compass-chat',
        element: <CompassChat />,
        errorElement: <Error />,
      },
      {
        path: 'compass-view',
        element: <CompassView />,
        errorElement: <Error />,
      },
      {
        path: 'compass-visualizer',
        element: <CompassVisualizer />,
        errorElement: <Error />,
      },
    ],
  },
],{
  basename: '/Capability-Compass'
    });
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <RouterProvider router={router} />
    </ErrorBoundary>
  </StrictMode>,
)
