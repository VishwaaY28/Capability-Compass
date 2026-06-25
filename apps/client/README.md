# Compass Master Client

Frontend application for the Compass Master system built with React, TypeScript, and Vite.

## Prerequisites

- Node.js 18+ and npm/pnpm/yarn
- Backend API server running on `http://localhost:8005`

## Installation

```bash
npm install
# or
pnpm install
# or
yarn install
```

## Configuration

The `.env` file contains:
```
VITE_API_BASE_URL=http://localhost:8005
VITE_PORT=8500
```

Adjust these if your backend runs on a different port.

## Development

Start the frontend server:
```bash
cd apps/client
npm run dev
```

The app will be available at `http://localhost:8500`

Start the backend server:
```bash
cd apps/server/src
python main.py
```

## Building for Production

```bash
npm run build
```

The built files will be in the `dist/` directory.

## Preview Production Build

```bash
npm run preview
```

## Project Structure

```
src/
├── main.tsx                # Application entry point
├── components/             # Reusable React components
│   ├── ErrorBoundary.tsx   # Error boundary wrapper
│   ├── Sidebar.tsx         # Navigation sidebar
│   └── visualizer/         # Graph visualization components
├── hooks/                  # Custom React hooks
│   ├── useCapability.ts    # Capability CRUD operations
│   ├── useResearch.tsx     # LLM research functionality
│   └── useCompassChat.ts   # Chat interface
├── pages/                  # Page components
│   ├── Hero.tsx            # Landing page
│   ├── compassMaster.tsx   # Capability management
│   ├── compassVisualizer.tsx # Graph visualization
│   └── researchAgent.tsx   # LLM-powered search
└── utils/                  # Utility functions
    └── constants.ts        # API endpoints and constants
```

## Features

- **Capability Management**: Create and manage business capabilities, processes, and subprocesses
- **Graph Visualization**: Interactive Neo4j graph visualization using @neo4j-nvl
- **LLM Research**: AI-powered intelligent search across capabilities
- **CSV Export**: Export capability hierarchies to CSV

## Technologies

- React 19
- TypeScript
- Vite
- TailwindCSS
- Neo4j NVL (graph visualization)
- React Router
- React Hot Toast (notifications)

## Linting & Formatting

```bash
npm run lint
npm run format
```

## Deployment

1. Build the production bundle:
```bash
npm run build
```

2. Deploy the `dist/` folder to your hosting service (Vercel, Netlify, etc.)

3. Configure environment variables on your hosting platform

4. Ensure the backend API is accessible from your production domain

## Browser Support

- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)
