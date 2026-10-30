import type { ReactNode } from "react";

import type { Check } from "../types";

export function StepHeader({ title, desc }: { title: string; desc: string }) {
  return (
    <header className="step-head">
      <h1>{title}</h1>
      <p>{desc}</p>
    </header>
  );
}

export function CheckList({ items }: { items: Check[] }) {
  return (
    <ul className="checks">
      {items.map((check) => (
        <li key={check.key} className={check.status}>
          <span className="dot" />
          <div>
            <strong>
              {check.label}
              {check.required && <em>必选</em>}
            </strong>
            <p>{check.detail}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function Actions({ children }: { children: ReactNode }) {
  return <div className="actions">{children}</div>;
}

export function Banner({
  kind,
  children,
}: {
  kind: "ok" | "warn" | "error";
  children: ReactNode;
}) {
  return <div className={`banner ${kind}`}>{children}</div>;
}

export function Spinner({ label }: { label: string }) {
  return (
    <div className="loading">
      <span className="spin" />
      {label}
    </div>
  );
}

export function errorText(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return JSON.stringify(error);
}
