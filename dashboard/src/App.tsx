import { useEffect, useState } from "react";
import { ClaimPage } from "./ClaimPage";
import { Instructions } from "./Instructions";
import { Queue } from "./Queue";

function useHash() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const update = () => {
      setHash(window.location.hash);
    };
    window.addEventListener("hashchange", update);
    return () => {
      window.removeEventListener("hashchange", update);
    };
  }, []);
  return hash;
}

function Page({ hash }: Readonly<{ hash: string }>) {
  const claimId = /^#\/claims\/([^/]+)$/.exec(hash)?.[1];
  if (claimId) return <ClaimPage claimId={decodeURIComponent(claimId)} />;
  if (hash === "#/instructions") return <Instructions />;
  return <Queue />;
}

export function App() {
  const hash = useHash();
  const onInstructions = hash === "#/instructions";

  return (
    <>
      <header className="header">
        <a className="brand" href="#/">
          UnderCover <span className="tagline">claims desk</span>
        </a>
        <nav aria-label="Main">
          <a href="#/" aria-current={onInstructions ? undefined : "page"}>
            Queue
          </a>
          <a
            href="#/instructions"
            aria-current={onInstructions ? "page" : undefined}
          >
            Agent instructions
          </a>
        </nav>
      </header>
      <main>
        <Page hash={hash} />
      </main>
    </>
  );
}
