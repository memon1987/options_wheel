interface LoadingStateProps {
  message?: string;
}

export default function LoadingState({ message = 'Loading...' }: LoadingStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mb-4"></div>
      <p className="text-gray-400 text-sm">{message}</p>
    </div>
  );
}
