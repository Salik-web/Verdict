// Tiny shared bits so every screen surfaces errors + raw shapes the same way.
// Deliberately not a component library — just three helpers.
import type { ApiResult } from "./api";

/** Loud red box for a failed request: status line + response body. */
export function ErrorBox({ result }: { result: ApiResult | null }) {
  if (!result || result.ok || result.error == null) return null;
  return (
    <pre className="my-2 whitespace-pre-wrap border border-red-400 bg-red-50 p-2 text-xs text-red-900">
      HTTP {result.status}
      {"\n"}
      {result.error}
    </pre>
  );
}

/** Raw JSON dump for verifying shapes next to a rendered view. */
export function Json({ data }: { data: unknown }) {
  return (
    <pre className="my-2 max-h-96 overflow-auto border border-gray-300 bg-gray-50 p-2 text-xs">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

/** A labelled block with a heading. */
export function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-8 border border-gray-300 p-4">
      <h2 className="mb-3 text-lg font-bold">{title}</h2>
      {children}
    </section>
  );
}
