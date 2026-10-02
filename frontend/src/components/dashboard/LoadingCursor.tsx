// Terminal-style blinking cursor, replaces the bare "Loading…" placeholder
// text throughout the dashboard. Opacity-only animation, no color change.
export function LoadingCursor() {
  return (
    <span aria-hidden="true" style={{ animation: "blink-cursor 1s infinite" }}>
      _
    </span>
  );
}
