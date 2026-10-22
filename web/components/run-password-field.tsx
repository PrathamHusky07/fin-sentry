"use client";

import { useId } from "react";

/**
 * The run password field shared by the forms that start an investigation. The value lives in
 * the parent form's state only while the form is open. It is sent in a request header on
 * submit and is never written to the URL, to storage or to a log.
 */
export function RunPasswordField({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div>
      <label
        htmlFor={id}
        className="text-text-primary block text-base font-medium"
      >
        Run password
      </label>
      <p
        id={`${id}-help`}
        className="text-text-secondary mt-0.5 max-w-prose text-base sm:text-sm"
      >
        Starting an investigation spends model calls, so it needs the password
        the project operator set on the gateway. A wrong one starts nothing.
      </p>
      <input
        id={id}
        name="run-password"
        type="password"
        autoComplete="off"
        spellCheck={false}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        aria-describedby={`${id}-help`}
        className="border-border-strong bg-background text-text-primary focus-visible:outline-accent mt-2 min-h-11 w-full max-w-xs rounded-lg border px-3 font-mono text-base"
      />
    </div>
  );
}
