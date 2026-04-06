interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

export default function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="card border border-red-500/30 bg-red-900/10">
      <div className="flex flex-col items-center text-center py-6">
        <svg
          className="w-10 h-10 text-red-400 mb-3"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        <p className="font-medium text-red-400 mb-1">Error loading data</p>
        <p className="text-sm text-gray-400 mb-4 max-w-md">{message}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-sm font-medium rounded-lg transition-colors"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
