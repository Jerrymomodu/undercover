import { type SyntheticEvent, useState } from "react";

export interface Submitting {
  submit: (event: SyntheticEvent<HTMLFormElement>) => void;
  sending: boolean;
  error?: string;
}

// Sends a form's request, keeping whether it is on its way and why it failed.
// `onSent` runs once the backend accepts it.
export function useSubmit<T>(
  send: () => Promise<T>,
  onSent: (result: T) => void,
  failure: string,
): Submitting {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setSending(true);
    setError(undefined);
    send()
      .then(onSent, (reason: unknown) => {
        setError(reason instanceof Error ? reason.message : failure);
      })
      .finally(() => {
        setSending(false);
      });
  }

  return { submit, sending, error };
}
