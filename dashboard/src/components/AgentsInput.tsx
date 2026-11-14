// How many claim agents a dispatch or an evaluation works with at once. The field
// keeps what was typed, so it can be emptied while typing; the form reads the
// number when it is sent, and the browser checks it is from 1 to MOST_AGENTS.
export const MOST_AGENTS = 25;
export const DEFAULT_AGENTS = "3";

export function AgentsInput({
  value,
  onChange,
}: Readonly<{ value: string; onChange: (agents: string) => void }>) {
  return (
    <label>
      Claim agents at once
      <input
        type="number"
        min={1}
        max={MOST_AGENTS}
        required
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      />
    </label>
  );
}
