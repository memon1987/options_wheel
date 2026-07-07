import { pnlColor } from '../../utils/format';

// Shared stat tile used by the Overview stats cards (FC-031 review R2:
// one markup definition instead of per-card copies).
export default function Stat({ label, value, tone, hint, warn }: {
  label: string;
  value: string | React.ReactNode;
  tone?: number | null;
  hint?: string;
  warn?: boolean;
}) {
  return (
    <div title={hint}>
      <div className="text-xs uppercase tracking-wide text-gray-400">{label}</div>
      <div
        className={`text-base font-semibold mt-0.5 ${
          warn ? 'text-yellow-300' : tone !== undefined ? pnlColor(tone ?? null) : 'text-white'
        }`}
      >
        {value}
      </div>
    </div>
  );
}
