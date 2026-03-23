import { FiAlertTriangle } from 'react-icons/fi';

const Error: React.FC = () => (
  <main className="w-screen h-screen flex flex-col items-center justify-center bg-gradient-to-br from-red-50 to-white">
    <div className="bg-white rounded-2xl shadow-lg p-10 flex flex-col items-center border border-red-100">
      <FiAlertTriangle className="w-12 h-12 text-red-500 mb-4" />
      <h1 className="text-3xl font-bold text-red-700 mb-2">Something went wrong</h1>
      <p className="text-neutral-600 mb-6">
        An unexpected error occurred. Please try again or contact support.
      </p>
      <a
        href="/"
        className="px-6 py-3 bg-primary text-white rounded-lg font-medium hover:bg-primary/90 transition"
      >
        Go Home
      </a>
    </div>
  </main>
);

export default Error;
