import { Spinner } from "./Spinner";

export function Splash() {
  return (
    <div className="flex h-full min-h-screen flex-col items-center justify-center gap-4 bg-paper">
      <span className="font-serif text-xl font-semibold text-ink">ME-UY 4214</span>
      <Spinner />
    </div>
  );
}
