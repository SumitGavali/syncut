import type { Segment } from '@/store/useStore';

const segIndex = (t: number, segs: Segment[]) => segs.findIndex((s) => t >= s.start && t < s.end);

/**
 * Who is "on" at time t?
 * The AI segment decides by default. A manual override at timestamp k wins from k until
 * the end of the AI segment that contained k (or until the next override).
 */
export function getActiveCamera(
  t: number,
  segments: Segment[],
  overrides: Record<number, string>,
): string | null {
  const keys = Object.keys(overrides).map(Number).filter((k) => k <= t).sort((a, b) => a - b);
  const k = keys[keys.length - 1];
  if (k !== undefined && segIndex(k, segments) === segIndex(t, segments)) return overrides[k];
  const i = segIndex(t, segments);
  return i >= 0 ? segments[i].camera : null;
}
