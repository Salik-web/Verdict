import Link from "next/link";

export default function Home() {
  return (
    <div>
      <h1 className="mb-3 text-xl font-bold">GEO backend test harness</h1>
      <p className="mb-2 text-sm">
        Throwaway click-through harness. Every screen reads the real TS API with
        session cookies. Follow the nav in order:
      </p>
      <ol className="list-inside list-decimal text-sm">
        <li>
          <Link href="/login" className="text-blue-700 underline">
            Login
          </Link>{" "}
          — sign up / log in
        </li>
        <li>
          <Link href="/setup" className="text-blue-700 underline">
            Setup
          </Link>{" "}
          — competitors, prompts, facts, then run a scan
        </li>
        <li>
          <Link href="/scans" className="text-blue-700 underline">
            Scans
          </Link>{" "}
          — watch a scan reach <code>completed</code>
        </li>
        <li>
          <Link href="/dashboard" className="text-blue-700 underline">
            Dashboard
          </Link>{" "}
          — the share-of-voice leaderboard
        </li>
      </ol>
    </div>
  );
}
