import clsx from "clsx";
import type { ReactNode } from "react";

export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={clsx("card", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({ title, hint, actions, className }: { title: ReactNode; hint?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={clsx("flex flex-wrap items-end justify-between gap-3 border-b border-line px-4 py-3 sm:px-5", className)}>
      <div className="min-w-0">
        <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
        {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

type Tone = "neutral" | "long" | "short" | "warn" | "accent";
const tones: Record<Tone, string> = {
  neutral: "border-line bg-raised text-muted",
  long: "border-long/30 bg-long/10 text-long",
  short: "border-short/30 bg-short/10 text-short",
  warn: "border-warn/30 bg-warn/10 text-warn",
  accent: "border-accent/30 bg-accent/10 text-accent",
};

export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide", tones[tone], className)}>
      {children}
    </span>
  );
}

export function Stat({ label, value, sub, tone, className }: { label: ReactNode; value: ReactNode; sub?: ReactNode; tone?: "long" | "short" | "warn"; className?: string }) {
  return (
    <div className={clsx("min-w-0", className)}>
      <div className="label">{label}</div>
      <div className={clsx("num mt-1.5 truncate text-xl font-semibold tracking-tight sm:text-2xl", tone === "long" && "text-long", tone === "short" && "text-short", tone === "warn" && "text-warn")}>
        {value}
      </div>
      {sub && <div className="mt-1 truncate text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-raised", className)} />;
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      {icon && <div className="mb-3 text-faint">{icon}</div>}
      <div className="text-sm font-medium text-ink">{title}</div>
      {children && <div className="mt-1 max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Segmented<T extends string | number>({ value, options, onChange, size = "md" }: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-raised p-0.5" role="tablist">
      {options.map((o) => (
        <button
          key={String(o.value)}
          role="tab"
          aria-selected={o.value === value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "rounded-md font-medium transition",
            size === "sm" ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-sm",
            o.value === value ? "bg-surface text-ink shadow-sm ring-1 ring-line" : "text-muted hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Select({ value, onChange, children, className, label }: { value: string; onChange: (v: string) => void; children: ReactNode; className?: string; label: string }) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className={clsx("input w-auto py-1.5 pr-8", className)}>
      {children}
    </select>
  );
}

export function Dot({ tone, pulse }: { tone: "long" | "short" | "warn" | "muted"; pulse?: boolean }) {
  const color = { long: "bg-long", short: "bg-short", warn: "bg-warn", muted: "bg-faint" }[tone];
  return <span className={clsx("inline-block h-2 w-2 rounded-full", color, pulse && "animate-pulseDot")} />;
}
